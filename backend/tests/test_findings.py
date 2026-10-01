from pathlib import Path

import pytest

from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import load_methodology
from app.recommendations.findings import derive_findings

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def _result(criterion_id="CRI-PR-01", estado=Estado.EVALUADO, score=None, evidence_ids=None):
    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=estado,
        base_score=score,
        final_score=score,
        explanation="x",
        evidence_ids=evidence_ids or [],
    )


def test_score_below_threshold_produces_a_finding(methodology):
    results = [_result(score=25.0, evidence_ids=["ev1"])]
    findings = derive_findings(methodology, results)

    assert len(findings) == 1
    assert findings[0].criterion_id == "CRI-PR-01"
    assert findings[0].score == 25.0
    assert findings[0].evidence_ids == ["ev1"]


def test_score_at_or_above_threshold_produces_no_finding(methodology):
    results = [_result(score=75.0), _result(score=100.0)]
    assert derive_findings(methodology, results) == []


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, "alta"),
        (24.9, "alta"),
        (25.0, "media"),
        (49.9, "media"),
        (50.0, "baja"),
        (74.9, "baja"),
    ],
)
def test_severity_bands(methodology, score, expected):
    findings = derive_findings(methodology, [_result(score=score)])
    assert findings[0].severidad == expected


_NON_SCORING_STATES = [Estado.EVIDENCIA_INSUFICIENTE, Estado.NO_APLICABLE, Estado.ERROR]


@pytest.mark.parametrize("estado", _NON_SCORING_STATES)
def test_non_scoring_states_never_produce_findings(methodology, estado):
    results = [_result(estado=estado, score=None)]
    assert derive_findings(methodology, results) == []


def test_no_implementado_below_threshold_produces_a_finding(methodology):
    results = [_result(criterion_id="CRI-GV-01", estado=Estado.NO_IMPLEMENTADO, score=0.0)]
    findings = derive_findings(methodology, results)
    assert len(findings) == 1
    assert findings[0].severidad == "alta"
