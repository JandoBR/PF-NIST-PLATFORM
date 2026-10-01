from pathlib import Path

import pytest

from app.ai.client import FakeAIClient, NullAIClient
from app.ai.plan_generation import generate_plan_content
from app.methodology.loader import load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture(scope="module")
def criterion():
    methodology = load_methodology(METHODOLOGY_DIR)
    return methodology.criterios["CRI-PR-01"]


def test_falls_back_to_template_when_ai_unavailable(criterion):
    content = generate_plan_content(
        NullAIClient(), criterion, severidad="alta", score=25.0, evidence_ids=["ev1"]
    )

    assert content.objetivo == criterion.recomendacion
    assert content.pasos == [criterion.recomendacion]
    assert criterion.id in content.verificacion


def test_falls_back_to_template_on_invalid_ai_response(criterion):
    client = FakeAIClient({"CRI-PR-01": {"not": "the expected schema"}})
    content = generate_plan_content(
        client, criterion, severidad="alta", score=25.0, evidence_ids=["ev1"]
    )

    assert content.objetivo == criterion.recomendacion


def test_uses_ai_content_when_available_and_valid(criterion):
    client = FakeAIClient(
        {
            "CRI-PR-01": {
                "titulo": "Cifrar RDS y S3 ya",
                "objetivo": "Eliminar datos sin cifrar en reposo",
                "pasos": ["Habilitar KMS en RDS", "Habilitar KMS en S3"],
                "verificacion": "Reevaluar CRI-PR-01 y confirmar estado enabled",
                "dependencias": ["Acceso a KMS"],
            }
        }
    )
    content = generate_plan_content(
        client, criterion, severidad="alta", score=25.0, evidence_ids=["ev1"]
    )

    assert content.titulo == "Cifrar RDS y S3 ya"
    assert content.pasos == ["Habilitar KMS en RDS", "Habilitar KMS en S3"]
    assert content.dependencias == ["Acceso a KMS"]
