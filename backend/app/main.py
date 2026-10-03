"""CLI de demo del nucleo determinista: Terraform/documentos -> evidencia -> criterios ->
agregados -> Tier -> persistencia -> reevaluacion -> comparacion.

No es la API (doc 04 §6, deliberadamente pospuesta). Cada evaluacion se guarda en SQLite por
defecto (ver app/core/db.py) para poder reevaluar y comparar sin levantar Postgres/Redis:

    uv run python -m app.main run --terraform tests/fixtures/terraform/good \
        --documents tests/fixtures/documents --org "Empresa Demo"
    uv run python -m app.main list
    uv run python -m app.main reevaluate <assessment_id>
    uv run python -m app.main compare <assessment_id_a> <assessment_id_b>
    uv run python -m app.main plans <assessment_id>
    uv run python -m app.main events "Empresa Demo" \
        tests/fixtures/scenarios/e1b_fallos_sin_alerta.jsonl
    uv run python -m app.main incidents "Empresa Demo" --plans
    uv run python -m app.main eval-ai --confirm-live-ai

Sin `DEEPSEEK_API_KEY` configurada (shell o backend/.env), la extraccion documental se omite
y el sistema sigue funcionando con los criterios tecnicos (doc 05 §7, principio de degradacion).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.ai.client import build_default_client
from app.ai.golden_eval import evaluate_extraction, format_report
from app.ai.guard import check_live_ai_guard
from app.core import assessment_service as svc
from app.core.db import build_engine, build_session_factory, ensure_schema
from app.evaluation import aggregation, tier
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology, load_methodology
from app.models.tables import Assessment, Source

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def _abort(message: str) -> None:
    print(f"ATENCION: {message}", file=sys.stderr)
    raise SystemExit(1)


def _open_session() -> Session:
    engine = build_engine()
    ensure_schema(engine)
    return build_session_factory(engine)()


def _print_report(methodology: Methodology, results: list[CriterionResult]) -> None:
    print("Resultados por criterio:")
    for result in sorted(results, key=lambda r: r.criterion_id):
        titulo = methodology.criterios[result.criterion_id].titulo
        print(
            f"  {result.criterion_id} [{result.estado.value:24s}] "
            f"{result.final_score} — {titulo}"
        )
        print(f"      {result.explanation}")

    categorias = aggregation.aggregate_by_categoria(methodology, results)
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    glob = aggregation.aggregate_global(methodology, funciones)

    print("\nAgregado por categoria:")
    for agg in categorias:
        print(f"  {agg.ref}: score={agg.score} cobertura={agg.cobertura} {agg.conteo_estados}")

    print("\nAgregado por funcion:")
    for agg in funciones:
        print(f"  {agg.ref}: score={agg.score} cobertura={agg.cobertura} {agg.conteo_estados}")

    print(f"\nGlobal: score={glob.score} cobertura={glob.cobertura} {glob.conteo_estados}")

    tier_estimate = tier.estimate_tier(methodology.settings.tier, results)
    print(f"\nTier estimado: {tier_estimate.justificacion}")
    if tier_estimate.faltantes:
        print("  Falta para el siguiente nivel: " + "; ".join(tier_estimate.faltantes))


def _build_ai_client_if_needed(ai_requested: bool):
    if not ai_requested:
        return None
    client = build_default_client()
    ia_activa = type(client).__name__ != "NullAIClient"
    print(f"IA: {'activa (DeepSeek)' if ia_activa else 'no configurada'}.")
    return client


def cmd_run(args: argparse.Namespace) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")

    ai_requested = args.documents is not None or args.ai_adjust
    guard_error = check_live_ai_guard(
        ai_requested, os.environ.get("DEEPSEEK_API_KEY"), args.confirm_live_ai
    )
    if guard_error:
        _abort(guard_error)

    client = _build_ai_client_if_needed(ai_requested)
    session = _open_session()
    assessment = svc.run_assessment(
        session,
        methodology,
        org_name=args.org,
        scope=args.scope,
        terraform_path=args.terraform,
        ansible_path=args.ansible,
        documents_path=args.documents,
        ai_client=client,
        apply_ai_adjustment=args.ai_adjust,
        context=json.loads(args.context),
    )
    results = svc.load_criterion_results(session, assessment.id)
    print(f"\nAssessment guardado: {assessment.id} (org={args.org})\n")
    _print_report(methodology, results)


def cmd_eval_ai(args: argparse.Namespace) -> None:
    """TS-02: mide la extraccion U1 real contra el golden set anotado (docs/05 §8)."""

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        _abort("eval-ai mide al modelo real: configura DEEPSEEK_API_KEY (shell o backend/.env).")
    guard_error = check_live_ai_guard(True, api_key, args.confirm_live_ai)
    if guard_error:
        _abort(guard_error)

    methodology = load_methodology(REPO_ROOT / "methodology")
    report = evaluate_extraction(_build_ai_client_if_needed(True), methodology, args.golden_dir)
    print(format_report(report))
    if not report.passed:
        raise SystemExit(1)


def cmd_list(_args: argparse.Namespace) -> None:
    session = _open_session()
    assessments = session.query(Assessment).order_by(Assessment.creado_en.desc()).all()
    if not assessments:
        print("Sin evaluaciones guardadas todavia. Usa 'run' primero.")
        return
    for a in assessments:
        print(
            f"{a.id}  {a.creado_en:%Y-%m-%d %H:%M}  "
            f"{a.organization.nombre:20s}  {a.estado:12s}  {a.methodology_version}"
        )


def cmd_reevaluate(args: argparse.Namespace) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")
    session = _open_session()

    tiene_documentos = (
        session.query(Source)
        .filter_by(assessment_id=args.assessment_id, tipo="documents")
        .first()
        is not None
    )
    ai_requested = tiene_documentos or args.ai_adjust
    guard_error = check_live_ai_guard(
        ai_requested, os.environ.get("DEEPSEEK_API_KEY"), args.confirm_live_ai
    )
    if guard_error:
        _abort(guard_error)

    client = _build_ai_client_if_needed(ai_requested)
    try:
        assessment = svc.reevaluate(
            session,
            methodology,
            args.assessment_id,
            ai_client=client,
            apply_ai_adjustment=args.ai_adjust,
            context=json.loads(args.context),
        )
    except svc.AssessmentNotFoundError:
        _abort(f"No existe un assessment con id {args.assessment_id!r}.")
        return

    results = svc.load_criterion_results(session, assessment.id)
    print(f"\nNuevo assessment: {assessment.id} (reevaluacion de {args.assessment_id})\n")
    _print_report(methodology, results)


def cmd_plans(args: argparse.Namespace) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")
    session = _open_session()

    ai_requested = args.ai
    guard_error = check_live_ai_guard(
        ai_requested, os.environ.get("DEEPSEEK_API_KEY"), args.confirm_live_ai
    )
    if guard_error:
        _abort(guard_error)

    client = _build_ai_client_if_needed(ai_requested)
    try:
        svc.generate_plans(session, methodology, args.assessment_id, ai_client=client)
    except svc.AssessmentNotFoundError:
        _abort(f"No existe un assessment con id {args.assessment_id!r}.")
        return

    plans = svc.load_plans(session, args.assessment_id)
    if not plans:
        print("Sin hallazgos por debajo del umbral de brecha: no se genero ningun plan.")
        return

    orden = {"alta": 0, "media": 1, "baja": 2}
    for plan in sorted(plans, key=lambda p: orden[p.prioridad]):
        print(f"[{plan.prioridad:5s}] {plan.criterion_id} — {plan.titulo} ({plan.generado_por})")
        print(f"  Objetivo: {plan.objetivo}")
        for i, paso in enumerate(plan.pasos, start=1):
            print(f"  {i}. {paso}")
        print(f"  Verificacion: {plan.verificacion}")
        if plan.dependencias:
            print(f"  Dependencias: {', '.join(plan.dependencias)}")
        print()


def cmd_events(args: argparse.Namespace) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")
    session = _open_session()

    guard_error = check_live_ai_guard(
        args.ai, os.environ.get("DEEPSEEK_API_KEY"), args.confirm_live_ai
    )
    if guard_error:
        _abort(guard_error)

    client = _build_ai_client_if_needed(args.ai)
    result = svc.ingest_events(session, methodology, args.org, args.jsonl, ai_client=client)

    print(
        f"Eventos leidos: {result.eventos_ingeridos} "
        f"({result.eventos_nuevos} nuevos, {result.eventos_existentes} ya existian)"
    )
    if not result.nuevos_incidentes and not result.incidentes_actualizados:
        print("Sin disparadores: ningun incidente nuevo ni actualizado.")
        return

    for incident in result.nuevos_incidentes:
        print(f"\nIncidente NUEVO [{incident.severidad}] {incident.id}: {incident.titulo}")
        _print_incident_plans(session, incident.id)
    for incident in result.incidentes_actualizados:
        print(f"\nIncidente ACTUALIZADO [{incident.severidad}] {incident.id}: {incident.titulo}")
        _print_incident_plans(session, incident.id)


def _print_incident_plans(session: Session, incident_id: str) -> None:
    for plan in svc.load_incident_plans(session, incident_id):
        print(f"  Plan: {plan.titulo} ({plan.generado_por})")
        print(f"    Diagnostico: {plan.diagnostico_observable}")
        print(f"    Hipotesis: {'; '.join(plan.hipotesis)}")
        print(f"    Comprobaciones seguras: {'; '.join(plan.comprobaciones_seguras)}")
        print(f"    Objetivo: {plan.objetivo}")
        for i, paso in enumerate(plan.pasos, start=1):
            print(f"    {i}. {paso}")
        print(f"    Verificacion: {plan.verificacion}")
        print(f"    {plan.advertencia}")


def cmd_incidents(args: argparse.Namespace) -> None:
    session = _open_session()
    incidents = svc.list_incidents(session, args.org)
    if not incidents:
        print(f"Sin incidentes para {args.org!r}. Usa 'events' primero.")
        return

    for incident in incidents:
        print(
            f"{incident.id}  [{incident.severidad:5s}] {incident.estado:10s}  "
            f"{incident.actualizado_en:%Y-%m-%d %H:%M}  {incident.titulo}"
        )
        if args.plans:
            _print_incident_plans(session, incident.id)


def cmd_compare(args: argparse.Namespace) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")
    session = _open_session()

    try:
        report = svc.compare(session, methodology, args.assessment_a, args.assessment_b)
    except svc.AssessmentNotFoundError as exc:
        _abort(f"No existe un assessment con id {exc!s}.")
        return

    print(f"Comparando {args.assessment_a} -> {args.assessment_b}\n")
    for diff in report.diffs:
        marca = "->" if diff.cambio else "  "
        antes = f"{diff.estado_antes} {diff.score_antes}"
        despues = f"{diff.estado_despues} {diff.score_despues}"
        print(f"  {marca} {diff.criterion_id} [{antes}] -> [{despues}]  {diff.titulo}")

    if report.cambios:
        print(f"\n{len(report.cambios)} criterio(s) cambiaron.")
    else:
        print("\nSin cambios en ningun criterio.")
    print(f"Global: {report.global_antes} -> {report.global_despues}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Ejecuta y persiste una evaluacion")
    run_parser.add_argument("--terraform", type=Path, default=None, help="Archivo o directorio .tf")
    run_parser.add_argument(
        "--ansible", type=Path, default=None, help="Archivo o directorio de playbooks"
    )
    run_parser.add_argument(
        "--documents", type=Path, default=None, help="Archivo o directorio de documentos"
    )
    run_parser.add_argument("--org", default="Organizacion Demo")
    run_parser.add_argument("--scope", default="entorno:produccion")
    run_parser.add_argument(
        "--ai-adjust", action="store_true", help="Aplica U2 (ajuste contextual) con IA"
    )
    run_parser.add_argument(
        "--context", default="{}", help='Contexto para U2 como JSON, ej. \'{"sector": "salud"}\''
    )
    run_parser.add_argument("--confirm-live-ai", action="store_true")
    run_parser.set_defaults(func=cmd_run)

    eval_parser = subparsers.add_parser(
        "eval-ai", help="Evalua la extraccion de IA contra el golden set (cuesta dinero)"
    )
    eval_parser.add_argument(
        "--golden-dir", type=Path, default=REPO_ROOT / "tests" / "golden_ai"
    )
    eval_parser.add_argument("--confirm-live-ai", action="store_true")
    eval_parser.set_defaults(func=cmd_eval_ai)

    list_parser = subparsers.add_parser("list", help="Lista evaluaciones guardadas")
    list_parser.set_defaults(func=cmd_list)

    reeval_parser = subparsers.add_parser(
        "reevaluate", help="Nueva evaluacion heredando las fuentes de una anterior"
    )
    reeval_parser.add_argument("assessment_id")
    reeval_parser.add_argument(
        "--ai-adjust", action="store_true", help="Aplica U2 (ajuste contextual) con IA"
    )
    reeval_parser.add_argument("--context", default="{}", help="Contexto para U2 como JSON")
    reeval_parser.add_argument("--confirm-live-ai", action="store_true")
    reeval_parser.set_defaults(func=cmd_reevaluate)

    plans_parser = subparsers.add_parser(
        "plans", help="Genera planes de mejora para los hallazgos de una evaluacion"
    )
    plans_parser.add_argument("assessment_id")
    plans_parser.add_argument(
        "--ai", action="store_true", help="Redacta el contenido con IA (si no, usa la plantilla)"
    )
    plans_parser.add_argument("--confirm-live-ai", action="store_true")
    plans_parser.set_defaults(func=cmd_plans)

    events_parser = subparsers.add_parser(
        "events", help="Ingiere eventos JSONL: patrones, disparadores, incidentes y planes"
    )
    events_parser.add_argument("org", help="Nombre de la organizacion")
    events_parser.add_argument("jsonl", type=Path, help="Archivo JSONL de eventos")
    events_parser.add_argument(
        "--ai", action="store_true", help="Redacta los planes con IA (si no, usa la plantilla)"
    )
    events_parser.add_argument("--confirm-live-ai", action="store_true")
    events_parser.set_defaults(func=cmd_events)

    incidents_parser = subparsers.add_parser(
        "incidents", help="Lista incidentes de una organizacion"
    )
    incidents_parser.add_argument("org", help="Nombre de la organizacion")
    incidents_parser.add_argument(
        "--plans", action="store_true", help="Mostrar tambien sus planes"
    )
    incidents_parser.set_defaults(func=cmd_incidents)

    compare_parser = subparsers.add_parser("compare", help="Diferencia entre dos evaluaciones")
    compare_parser.add_argument("assessment_a")
    compare_parser.add_argument("assessment_b")
    compare_parser.set_defaults(func=cmd_compare)

    args = parser.parse_args()

    if args.command == "run" and not (args.terraform or args.ansible or args.documents):
        parser.error("run requiere --terraform, --ansible y/o --documents")

    args.func(args)


if __name__ == "__main__":
    main()
