"""Helpers compartidos por las reglas de criterio."""

from __future__ import annotations

from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance


def by_type(evidence: list[EvidenceInstance], type_id: str) -> list[EvidenceInstance]:
    return [e for e in evidence if e.type_id == type_id]


def doc_claims(
    evidence: list[EvidenceInstance], tipo_afirmacion: str
) -> list[EvidenceInstance]:
    """`doc.claim` de un `tipo_afirmacion`, excluyendo los de confianza baja (E3, docs/05 §2.3):
    una confianza baja no cuenta como evidencia suficiente."""

    return [
        e
        for e in by_type(evidence, "doc.claim")
        if e.value.get("tipo_afirmacion") == tipo_afirmacion and e.limitations is None
    ]


def best_found(claims: list[EvidenceInstance]) -> EvidenceInstance | None:
    """La afirmacion `encontrado=true` con mayor confianza, o `None` si ninguna declara el hecho."""

    encontradas = [c for c in claims if c.value.get("encontrado")]
    if not encontradas:
        return None
    return max(encontradas, key=lambda c: c.value.get("confianza", 0))


def result(
    criterion_id: str,
    estado: Estado,
    score: int | None,
    explanation: str,
    evidence_ids: list[str] | None = None,
) -> CriterionResult:
    """Construye un `CriterionResult`. `criterion_version` lo sobreescribe el motor con la version
    del catalogo (engine._evaluate_one)."""

    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=estado,
        base_score=score,
        final_score=score,
        explanation=explanation,
        evidence_ids=evidence_ids or [],
    )
