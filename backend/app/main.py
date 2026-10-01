"""CLI de demo del nucleo determinista: Terraform/documentos -> evidencia -> criterios ->
agregados -> Tier.

No es la API (doc 04 §6, deliberadamente pospuesta). Permite mostrar el motor de evaluacion
funcionando de punta a punta sin base de datos ni Redis:

    uv run python -m app.main --terraform tests/fixtures/terraform/good \
        --documents tests/fixtures/documents

Sin `DEEPSEEK_API_KEY` configurada (shell o backend/.env), la extraccion documental se omite
y el sistema sigue funcionando con los criterios tecnicos (doc 05 §7, principio de degradacion).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.adapters.documents.adapter import DocumentAdapter
from app.adapters.terraform.adapter import TerraformAdapter
from app.ai.client import build_default_client
from app.evaluation import aggregation, engine, tier
from app.methodology.loader import Methodology, load_methodology
from app.schemas.evidence import EvidenceInstance

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def check_live_ai_guard(
    documents_path: Path | None, api_key: str | None, confirmed: bool
) -> str | None:
    """Bloqueo explicito antes de gastar dinero real.

    Pedido tras un incidente real: una corrida de prueba disparo 3 llamadas pagadas porque
    `backend/.env` ya tenia una API key real y nadie la noto hasta despues.
    Retorna un mensaje de error si hay que abortar, o None si se puede seguir.
    """

    if documents_path is None or not api_key or confirmed:
        return None
    return (
        "Hay una DEEPSEEK_API_KEY real configurada (shell o backend/.env).\n"
        "Analizar --documents hara llamadas reales y pagadas a la API de DeepSeek\n"
        "(los chunks ya cacheados en backend/.cache/ no se repiten).\n"
        "Pasa --confirm-live-ai si de verdad quieres continuar, o quita la key"
        " para una corrida sin costo."
    )


def _tipos_afirmacion_solicitados(methodology: Methodology) -> list[str]:
    tipos: set[str] = set()
    for criterio in methodology.criterios.values():
        tipos.update(criterio.regla.get("tipos_afirmacion", []))
    return sorted(tipos)


def _collect_evidence(
    methodology: Methodology, terraform_path: Path | None, documents_path: Path | None, scope: str
) -> list[EvidenceInstance]:
    evidence: list[EvidenceInstance] = []

    if terraform_path is not None:
        adapter = TerraformAdapter(source_id=f"cli:{terraform_path}", scope=scope)
        tf_evidence = adapter.parse_path(terraform_path)
        evidence.extend(tf_evidence)
        print(f"Terraform: {len(tf_evidence)} instancias de evidencia.")

    if documents_path is not None:
        client = build_default_client()
        ia_activa = type(client).__name__ != "NullAIClient"
        print(f"IA: {'activa (DeepSeek)' if ia_activa else 'no configurada, extraccion omitida'}.")

        adapter = DocumentAdapter(
            client, methodology, source_id=f"cli:{documents_path}", scope=scope
        )
        doc_evidence = adapter.parse_path(
            documents_path, tipos_solicitados=_tipos_afirmacion_solicitados(methodology)
        )
        evidence.extend(doc_evidence)
        print(f"Documentos: {len(doc_evidence)} instancias de evidencia.")
        if adapter.chunks_omitidos:
            print(f"  ({adapter.chunks_omitidos} chunk(s) omitidos por limite de costo)")

    return evidence


def run(terraform_path: Path | None, documents_path: Path | None, scope: str) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")
    evidence = _collect_evidence(methodology, terraform_path, documents_path, scope)
    print(f"\nTotal evidencia: {len(evidence)} instancias ({methodology.methodology_version})\n")

    results = engine.evaluate_all(methodology, evidence)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terraform", type=Path, default=None, help="Archivo o directorio .tf")
    parser.add_argument(
        "--documents", type=Path, default=None, help="Archivo o directorio de documentos"
    )
    parser.add_argument("--scope", default="entorno:produccion")
    parser.add_argument(
        "--confirm-live-ai",
        action="store_true",
        help="Confirma llamadas reales y pagadas a DeepSeek cuando hay una API key configurada",
    )
    args = parser.parse_args()

    if args.terraform is None and args.documents is None:
        parser.error("se requiere --terraform y/o --documents")

    guard_error = check_live_ai_guard(
        args.documents, os.environ.get("DEEPSEEK_API_KEY"), args.confirm_live_ai
    )
    if guard_error:
        print(f"ATENCION: {guard_error}", file=sys.stderr)
        raise SystemExit(1)

    run(args.terraform, args.documents, args.scope)


if __name__ == "__main__":
    main()
