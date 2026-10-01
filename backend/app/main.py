"""CLI de demo del nucleo determinista: Terraform/documentos -> evidencia -> criterios ->
agregados -> Tier -> persistencia -> reevaluacion -> comparacion.

No es la API (doc 04 §6, deliberadamente pospuesta). Cada evaluacion se guarda en SQLite por
defecto (ver app/core/db.py) para poder reevaluar y comparar sin levantar Postgres/Redis:

    uv run python -m app.main run --terraform tests/fixtures/terraform/good \
        --documents tests/fixtures/documents --org "Empresa Demo"
    uv run python -m app.main list
    uv run python -m app.main reevaluate <assessment_id>
    uv run python -m app.main compare <assessment_id_a> <assessment_id_b>

Sin `DEEPSEEK_API_KEY` configurada (shell o backend/.env), la extraccion documental se omite
y el sistema sigue funcionando con los criterios tecnicos (doc 05 §7, principio de degradacion).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.ai.client import build_default_client
from app.core import assessment_service as svc
from app.core.db import build_engine, build_session_factory, create_all
from app.evaluation import aggregation, tier
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology, load_methodology
from app.models.tables import Assessment, Source

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def check_live_ai_guard(
    documents_requested: bool, api_key: str | None, confirmed: bool
) -> str | None:
    """Bloqueo explicito antes de gastar dinero real.

    Pedido tras un incidente real: una corrida de prueba disparo 3 llamadas pagadas porque
    `backend/.env` ya tenia una API key real y nadie la noto hasta despues.
    Retorna un mensaje de error si hay que abortar, o None si se puede seguir.
    """

    if not documents_requested or not api_key or confirmed:
        return None
    return (
        "Hay una DEEPSEEK_API_KEY real configurada (shell o backend/.env).\n"
        "Esta operacion hara llamadas reales y pagadas a la API de DeepSeek\n"
        "(los chunks ya cacheados en backend/.cache/ no se repiten).\n"
        "Pasa --confirm-live-ai si de verdad quieres continuar, o quita la key"
        " para una corrida sin costo."
    )


def _abort(message: str) -> None:
    print(f"ATENCION: {message}", file=sys.stderr)
    raise SystemExit(1)


def _open_session() -> Session:
    engine = build_engine()
    create_all(engine)
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


def _build_ai_client_if_needed(documents_requested: bool):
    if not documents_requested:
        return None
    client = build_default_client()
    ia_activa = type(client).__name__ != "NullAIClient"
    print(f"IA: {'activa (DeepSeek)' if ia_activa else 'no configurada, extraccion omitida'}.")
    return client


def cmd_run(args: argparse.Namespace) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")

    guard_error = check_live_ai_guard(
        args.documents is not None, os.environ.get("DEEPSEEK_API_KEY"), args.confirm_live_ai
    )
    if guard_error:
        _abort(guard_error)

    client = _build_ai_client_if_needed(args.documents is not None)
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
    )
    results = svc.load_criterion_results(session, assessment.id)
    print(f"\nAssessment guardado: {assessment.id} (org={args.org})\n")
    _print_report(methodology, results)


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
    guard_error = check_live_ai_guard(
        tiene_documentos, os.environ.get("DEEPSEEK_API_KEY"), args.confirm_live_ai
    )
    if guard_error:
        _abort(guard_error)

    client = _build_ai_client_if_needed(tiene_documentos)
    try:
        assessment = svc.reevaluate(session, methodology, args.assessment_id, ai_client=client)
    except svc.AssessmentNotFoundError:
        _abort(f"No existe un assessment con id {args.assessment_id!r}.")
        return

    results = svc.load_criterion_results(session, assessment.id)
    print(f"\nNuevo assessment: {assessment.id} (reevaluacion de {args.assessment_id})\n")
    _print_report(methodology, results)


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
    run_parser.add_argument("--confirm-live-ai", action="store_true")
    run_parser.set_defaults(func=cmd_run)

    list_parser = subparsers.add_parser("list", help="Lista evaluaciones guardadas")
    list_parser.set_defaults(func=cmd_list)

    reeval_parser = subparsers.add_parser(
        "reevaluate", help="Nueva evaluacion heredando las fuentes de una anterior"
    )
    reeval_parser.add_argument("assessment_id")
    reeval_parser.add_argument("--confirm-live-ai", action="store_true")
    reeval_parser.set_defaults(func=cmd_reevaluate)

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
