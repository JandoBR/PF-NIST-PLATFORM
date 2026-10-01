"""E2E de documentos (cierra el gap del registro §4/§11): `run_assessment` con `documents_path`
y un cliente de IA falso recorre extraccion U1 -> evidencia `doc.claim` persistida -> regla
`CRI-GV-01`, sin tocar la API real. Los tests de `extract_claims` y de la regla por separado ya
existian; aqui se prueba el cableado completo."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.ai.client import FakeAIClient, NullAIClient
from app.core import assessment_service as svc
from app.evaluation.schemas import Estado
from app.methodology.loader import load_methodology
from app.models.tables import EvidenceRow

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
DOCS_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "documents"
POLICY_DOC = DOCS_FIXTURES / "politica-seguridad.md"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def _fake_extraction_client() -> FakeAIClient:
    """Respuestas indexadas por palabras que solo aparecen en el chunk correcto del fixture:
    la seccion principal cita 'Direccion General'; la seccion Revision cita 'frecuencia anual'."""

    ultima_revision = (date.today() - timedelta(days=30)).isoformat()
    return FakeAIClient(
        {
            "Direccion General": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {
                            "nombre": "Politica de Seguridad de la Informacion",
                            "aprobada_por": "Direccion General",
                            "fecha": "2025-03-01",
                        },
                        "cita": {
                            "fragmento": "aprobada por la Direccion General el 1 de marzo de 2025"
                        },
                        "confianza": 0.9,
                    }
                ]
            },
            "frecuencia anual": {
                "afirmaciones": [
                    {
                        "tipo": "policy_review",
                        "encontrado": True,
                        "contenido": {"frecuencia": "anual", "ultima_revision": ultima_revision},
                        "cita": {"fragmento": "se revisa con una frecuencia anual"},
                        "confianza": 0.9,
                    }
                ]
            },
        }
    )


def test_run_assessment_with_documents_persists_claims_and_scores_gv01(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Documentos",
        scope="entorno:produccion",
        documents_path=POLICY_DOC,
        ai_client=_fake_extraction_client(),
    )

    assert assessment.estado == "completada"
    assert {s.tipo for s in assessment.sources} == {"documents"}

    claims = (
        db_session.query(EvidenceRow)
        .filter_by(assessment_id=assessment.id, type_id="doc.claim")
        .all()
    )
    assert {c.value["tipo_afirmacion"] for c in claims} >= {"policy_exists", "policy_review"}
    assert all(c.locator.get("file") for c in claims)  # toda afirmacion conserva procedencia

    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    gv01 = results["CRI-GV-01"]
    assert gv01.estado == Estado.EVALUADO
    assert gv01.final_score == 100
    assert len(gv01.evidence_ids) == 2  # policy_exists + policy_review vigente


def test_run_assessment_without_ai_degrades_documents_without_failing(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Sin IA",
        scope="entorno:produccion",
        documents_path=POLICY_DOC,
        ai_client=NullAIClient(),
    )

    assert assessment.estado == "completada"
    assert db_session.query(EvidenceRow).filter_by(assessment_id=assessment.id).count() == 0

    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    assert results["CRI-GV-01"].estado == Estado.EVIDENCIA_INSUFICIENTE
