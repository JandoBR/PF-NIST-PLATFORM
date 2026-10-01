"""CRI-GV-01 — Politica de ciberseguridad establecida y revisada (docs/03 §1).

Primer criterio puramente documental: solo usa `doc.claim`. Sin evidencia tecnica que pueda
contradecirlo (D7 no aplica aqui), la decision se basa enteramente en lo que la extraccion de
IA pudo citar.
"""

from __future__ import annotations

from datetime import date

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-01"
CRITERION_VERSION = 1

_FRECUENCIA_DIAS = {
    "mensual": 31,
    "trimestral": 92,
    "semestral": 183,
    "anual": 366,
}


def _usable(claims: list[EvidenceInstance]) -> list[EvidenceInstance]:
    """Confianza baja 'no cuenta como evidencia suficiente' (E3, docs/05 §2.3)."""

    return [c for c in claims if c.limitations is None]


def _revision_vigente(review_claim: EvidenceInstance) -> bool:
    frecuencia = str(review_claim.value["contenido"].get("frecuencia", "")).lower()
    ultima = review_claim.value["contenido"].get("ultima_revision")
    dias_frecuencia = _FRECUENCIA_DIAS.get(frecuencia)
    if dias_frecuencia is None or not ultima:
        return False
    try:
        ultima_fecha = date.fromisoformat(str(ultima))
    except ValueError:
        return False
    return (date.today() - ultima_fecha).days <= dias_frecuencia


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    all_claims = by_type(evidence, "doc.claim")
    exists_claims = _usable(
        [c for c in all_claims if c.value["tipo_afirmacion"] == "policy_exists"]
    )
    review_claims = _usable(
        [c for c in all_claims if c.value["tipo_afirmacion"] == "policy_review"]
    )

    if not exists_claims:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Sin documentos analizados (o sin afirmaciones utilizables) sobre"
            " la existencia de una politica de ciberseguridad.",
        )

    encontradas = [c for c in exists_claims if c.value["encontrado"]]
    if not encontradas:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.NO_IMPLEMENTADO,
            base_score=0,
            final_score=0,
            explanation="Los documentos analizados no declaran ninguna politica de ciberseguridad.",
            evidence_ids=[c.id for c in exists_claims],
        )

    mejor = max(encontradas, key=lambda c: c.value["confianza"])
    contenido = mejor.value["contenido"]
    nombre = contenido.get("nombre")
    aprobada_por = contenido.get("aprobada_por")

    if not nombre:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=25,
            final_score=25,
            explanation="Mencion informal de politicas sin un documento concreto identificado.",
            evidence_ids=[mejor.id],
        )

    if not aprobada_por:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=50,
            final_score=50,
            explanation=f"Politica '{nombre}' existe en borrador o sin aprobacion identificada.",
            evidence_ids=[mejor.id],
        )

    review_encontrada = [c for c in review_claims if c.value["encontrado"]]
    if not review_encontrada:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=75,
            final_score=75,
            explanation=f"Politica '{nombre}' aprobada por {aprobada_por}, sin evidencia de"
            " revision reciente.",
            evidence_ids=[mejor.id],
        )

    mejor_revision = max(review_encontrada, key=lambda c: c.value["confianza"])
    if _revision_vigente(mejor_revision):
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=100,
            final_score=100,
            explanation=f"Politica '{nombre}' aprobada por {aprobada_por}, con revision"
            " dentro de la frecuencia declarada.",
            evidence_ids=[mejor.id, mejor_revision.id],
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=75,
        final_score=75,
        explanation=f"Politica '{nombre}' aprobada por {aprobada_por}; la revision declarada"
        " no esta vigente dentro de su frecuencia.",
        evidence_ids=[mejor.id, mejor_revision.id],
    )
