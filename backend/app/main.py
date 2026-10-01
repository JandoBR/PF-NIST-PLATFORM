"""CLI de demo del nucleo determinista: Terraform -> evidencia -> criterios -> agregados -> Tier.

No es la API (doc 04 §6, deliberadamente pospuesta). Permite mostrar el motor de evaluacion
funcionando de punta a punta sin base de datos, Redis ni IA:

    uv run python -m app.main tests/fixtures/terraform/good --scope entorno:produccion
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation import aggregation, engine, tier
from app.methodology.loader import load_methodology

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(terraform_path: Path, scope: str) -> None:
    methodology = load_methodology(REPO_ROOT / "methodology")

    adapter = TerraformAdapter(source_id=f"cli:{terraform_path}", scope=scope)
    evidence = adapter.parse_path(terraform_path)
    print(
        f"Evidencia recolectada: {len(evidence)} instancias "
        f"({methodology.methodology_version})\n"
    )

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
    parser.add_argument("terraform_path", type=Path, help="Archivo o directorio .tf a analizar")
    parser.add_argument("--scope", default="entorno:produccion")
    args = parser.parse_args()
    run(args.terraform_path, args.scope)


if __name__ == "__main__":
    main()
