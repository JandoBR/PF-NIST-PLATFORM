from pathlib import Path

import pytest

from app.ai.client import FakeAIClient
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import load_methodology
from app.recommendations.plans import generate_plans

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def _result(criterion_id, score):
    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=Estado.EVALUADO,
        base_score=score,
        final_score=score,
        explanation="x",
        evidence_ids=["ev1"],
    )


def test_one_plan_per_finding_with_priority_from_severity(methodology):
    results = [_result("CRI-PR-01", 10.0), _result("CRI-PR-02", 60.0), _result("CRI-PR-03", 100.0)]

    plans = generate_plans(methodology, results)

    by_criterion = {p.criterion_id: p for p in plans}
    assert set(by_criterion) == {"CRI-PR-01", "CRI-PR-02"}  # CRI-PR-03 >= umbral: sin plan
    assert by_criterion["CRI-PR-01"].prioridad == "alta"
    assert by_criterion["CRI-PR-02"].prioridad == "baja"


def test_without_ai_client_falls_back_to_template(methodology):
    plans = generate_plans(methodology, [_result("CRI-PR-01", 10.0)])

    assert plans[0].generado_por == "plantilla"
    assert plans[0].objetivo == methodology.criterios["CRI-PR-01"].recomendacion


def test_ai_client_without_content_is_labelled_template(methodology):
    """Tener un cliente de IA no basta: si no devolvio contenido, el plan es plantilla."""

    plans = generate_plans(methodology, [_result("CRI-PR-01", 10.0)], client=FakeAIClient({}))

    assert plans[0].generado_por == "plantilla"
    assert plans[0].objetivo == methodology.criterios["CRI-PR-01"].recomendacion


def test_with_ai_client_uses_generated_content(methodology):
    client = FakeAIClient(
        {
            "CRI-PR-01": {
                "titulo": "Plan con IA",
                "objetivo": "objetivo generado",
                "pasos": ["paso 1"],
                "verificacion": "verificar",
                "dependencias": [],
            }
        }
    )
    plans = generate_plans(methodology, [_result("CRI-PR-01", 10.0)], client=client)

    assert plans[0].generado_por == "ai:plan_v1"
    assert plans[0].titulo == "Plan con IA"
