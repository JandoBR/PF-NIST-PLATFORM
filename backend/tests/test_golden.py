"""Golden files de Terraform/Ansible y del pipeline completo (docs/07 §3, docs/11 TS-01).

Cada caso corre el codigo real sobre un fixture fijo y compara contra `tests/golden/*.json`. Dos
niveles: la **evidencia** que emite cada adaptador (detecta cambios de parser) y el **resultado
del pipeline** -- criterios, agregados y Tier -- (detecta cambios de reglas, pesos o umbrales).
"""

from pathlib import Path

import pytest

from app.adapters.ansible.adapter import AnsibleAdapter
from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation import aggregation, engine, tier
from app.methodology.loader import load_methodology
from tests.golden_utils import (
    assert_matches_golden,
    normalize_aggregate,
    normalize_evidence,
    normalize_results,
)

BACKEND = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCOPE = "entorno:produccion"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(BACKEND / "methodology")


def _terraform(name: str):
    return TerraformAdapter(source_id="golden:terraform", scope=SCOPE).parse_path(
        FIXTURES / "terraform" / name
    )


def _ansible(name: str):
    return AnsibleAdapter(source_id="golden:ansible", scope=SCOPE).parse_path(
        FIXTURES / "ansible" / name
    )


@pytest.mark.parametrize("name", ["good", "gaps"])
def test_terraform_adapter_evidence_matches_golden(name):
    assert_matches_golden(f"terraform_{name}_evidence", normalize_evidence(_terraform(name)))


@pytest.mark.parametrize("name", ["good", "gaps"])
def test_ansible_adapter_evidence_matches_golden(name):
    assert_matches_golden(f"ansible_{name}_evidence", normalize_evidence(_ansible(name)))


@pytest.mark.parametrize("name", ["good", "gaps"])
def test_pipeline_result_matches_golden(methodology, name):
    """Terraform + Ansible del mismo caso -> criterios, agregados por funcion/global y Tier."""

    evidence = [*_terraform(name), *_ansible(name)]
    results = engine.evaluate_all(methodology, evidence)
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    estimate = tier.estimate_tier(methodology.settings.tier, results)

    assert_matches_golden(
        f"pipeline_{name}",
        {
            "criteria": normalize_results(results, evidence),
            "funciones": [normalize_aggregate(a) for a in funciones],
            "global": normalize_aggregate(aggregation.aggregate_global(methodology, funciones)),
            "tier": estimate.model_dump(mode="json"),
        },
    )


def test_golden_output_is_independent_of_the_run():
    """Dos corridas seguidas normalizan igual: lo que varia (uuid, fechas) no llega al golden."""

    assert normalize_evidence(_terraform("gaps")) == normalize_evidence(_terraform("gaps"))
