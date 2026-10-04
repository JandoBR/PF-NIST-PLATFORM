from datetime import UTC
from pathlib import Path

import pytest

from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation import engine
from app.evaluation.schemas import Estado
from app.methodology.loader import load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def _results_by_id(methodology, fixture_name):
    adapter = TerraformAdapter(source_id=f"test:{fixture_name}", scope="entorno:produccion")
    evidence = adapter.parse_path(FIXTURES / fixture_name)
    results = engine.evaluate_all(methodology, evidence)
    return {r.criterion_id: r for r in results}


def test_good_fixture_scores(methodology):
    results = _results_by_id(methodology, "good")

    assert results["CRI-PR-01"].estado == Estado.EVALUADO
    assert results["CRI-PR-01"].final_score == 100

    assert results["CRI-PR-02"].estado == Estado.EVALUADO
    assert results["CRI-PR-02"].final_score == 75  # tope sin doc.claim de politica

    assert results["CRI-PR-03"].final_score == 100
    assert results["CRI-PR-05"].final_score == 100
    assert results["CRI-PR-06"].final_score == 75  # multirregion, sin logs de sistema (Ansible)


def test_gaps_fixture_scores(methodology):
    results = _results_by_id(methodology, "gaps")

    # Ausencias explicitas, no implementaciones parciales: 0 (docs/09 §65).
    assert results["CRI-PR-01"].final_score == 0  # ningun recurso cifrado
    assert results["CRI-PR-02"].final_score == 0  # retencion 0 en la unica base
    assert results["CRI-PR-03"].final_score == 0  # SSH y RDP abiertos a 0.0.0.0/0
    assert results["CRI-PR-05"].final_score == 0  # block_public_acls = false explicito
    # Un 0 es evidencia explicita de ausencia: sale como no_implementado, no como evaluado.
    assert results["CRI-PR-05"].estado == Estado.NO_IMPLEMENTADO

    assert results["CRI-PR-06"].estado == Estado.EVIDENCIA_INSUFICIENTE
    assert results["CRI-PR-06"].final_score is None


def test_no_evidence_is_no_aplicable_not_zero(methodology):
    results = engine.evaluate_all(methodology, evidence=[])

    assert results[0].estado in (Estado.NO_APLICABLE, Estado.EVIDENCIA_INSUFICIENTE)
    assert all(r.final_score is None for r in results)


def test_unknown_encryption_state_is_insufficient_not_assumed(methodology):
    from datetime import datetime

    from app.schemas.evidence import EvidenceInstance, Locator, Modality

    evidence = [
        EvidenceInstance(
            type_id="tf.encryption.config",
            type_version=1,
            subject_type="aws_db_instance",
            subject_ref="aws_db_instance.misterioso",
            scope="entorno:produccion",
            value={"estado": "unknown", "mecanismo": None, "llave": None},
            source_id="test:unknown",
            locator=Locator(file="main.tf"),
            observed_at=datetime.now(UTC),
            modality=Modality.DECLARADA,
            created_by="adapter:terraform",
        )
    ]
    results = {r.criterion_id: r for r in engine.evaluate_all(methodology, evidence)}

    assert results["CRI-PR-01"].estado == Estado.EVIDENCIA_INSUFICIENTE
    assert results["CRI-PR-01"].final_score is None
