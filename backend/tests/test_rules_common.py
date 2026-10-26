"""Helpers de reglas: seleccion determinista de la mejor afirmacion (docs/00 §7)."""

from datetime import UTC, datetime

from app.evaluation.rules._common import best_found
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(ref: str, contenido: dict) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=2,
        subject_type="document",
        subject_ref=ref,
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": "policy_exists",
            "encontrado": True,
            "contenido": contenido,
            "confianza": 0.9,
        },
        source_id="test:common",
        locator=Locator(file=ref),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="ai:extraction",
    )


def test_best_found_breaks_ties_deterministically_not_by_list_order():
    a = _claim("doc-b", {"nombre": "Politica B"})
    b = _claim("doc-a", {"nombre": "Politica A"})

    assert best_found([a, b]).subject_ref == "doc-a"
    assert best_found([b, a]).subject_ref == "doc-a"


def test_best_found_still_prefers_higher_confidence():
    a = _claim("doc-a", {"nombre": "Politica A"})
    b = _claim("doc-b", {"nombre": "Politica B"})
    b.value["confianza"] = 0.95

    assert best_found([a, b]).subject_ref == "doc-b"
