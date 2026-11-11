"""Hallazgos derivados de resultados (docs/01 glosario: "brecha... vinculada a criterios y
evidencia"). No se persisten: son tan baratos de recalcular desde `criterion_results` como los
agregados y el Tier (misma decision que ahi).

Tipos: `brecha` (score bajo; unica que genera plan), `contradiccion` (tecnico vs documental o
documento vs documento, docs/02 §5; ver `contradictions.py`) y `limitacion` (expresion sin resolver
o recurso desconocido que condiciona un criterio; ver `limitations.py`). Las dos ultimas solo se
derivan si se pasa la evidencia, no puntuan y no generan plan. No se calcula criticidad de activo
todavia, asi que la severidad de una brecha viene solo del score.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.evaluation.schemas import SCORING_STATES, CriterionResult
from app.methodology.loader import Methodology
from app.schemas.evidence import EvidenceInstance

#: Bandas de severidad por score (simplificado: sin ponderar criticidad de activo todavia).
_SEVERIDAD_ALTA_MAX = 25
_SEVERIDAD_MEDIA_MAX = 50


class Finding(BaseModel):
    criterion_id: str
    titulo: str
    tipo: str = "brecha"
    severidad: str
    #: Puntaje del criterio en una `brecha`; `None` en una `contradiccion` (no puntua).
    score: float | None
    evidence_ids: list[str]
    #: Texto con ambos lados de una `contradiccion`; `None` en una `brecha`.
    detalle: str | None = None


def _severidad(score: float) -> str:
    if score < _SEVERIDAD_ALTA_MAX:
        return "alta"
    if score < _SEVERIDAD_MEDIA_MAX:
        return "media"
    return "baja"


def derive_findings(
    methodology: Methodology,
    results: list[CriterionResult],
    evidence: list[EvidenceInstance] | None = None,
) -> list[Finding]:
    """Un hallazgo `brecha` por cada criterio puntuado por debajo de `planes.umbral_brecha`; con
    `evidence`, ademas las `contradiccion` (que nunca generan plan ni alteran el puntaje)."""

    umbral = methodology.settings.planes.umbral_brecha
    findings = []
    for result in results:
        if result.estado not in SCORING_STATES or result.final_score is None:
            continue  # evidencia_insuficiente/no_aplicable/error: sin base para un hallazgo
        if result.final_score >= umbral:
            continue

        criterio = methodology.criterios.get(result.criterion_id)
        findings.append(
            Finding(
                criterion_id=result.criterion_id,
                titulo=criterio.titulo if criterio else result.criterion_id,
                severidad=_severidad(result.final_score),
                score=result.final_score,
                evidence_ids=result.evidence_ids,
            )
        )
    if evidence is not None:
        from app.recommendations.contradictions import detect_contradictions  # evita ciclo
        from app.recommendations.limitations import (
            detect_document_conflicts,
            detect_document_silence,
            detect_limitations,
            detect_unverified_quotes,
        )

        findings.extend(detect_contradictions(evidence))
        findings.extend(detect_limitations(methodology, results, evidence))
        findings.extend(detect_document_conflicts(results, evidence))
        findings.extend(detect_document_silence(methodology, results, evidence))
        findings.extend(detect_unverified_quotes(methodology, evidence))
    return findings
