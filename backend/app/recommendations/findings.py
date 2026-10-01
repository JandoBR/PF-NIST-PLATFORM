"""Hallazgos derivados de resultados (docs/01 glosario: "brecha... vinculada a criterios y
evidencia"). No se persisten: son tan baratos de recalcular desde `criterion_results` como los
agregados y el Tier (misma decision que ahi).

Alcance de este corte (simplificado a proposito): solo el tipo `brecha` (score bajo). Las
`contradiccion` (tecnico vs documental, docs/02 §5) y `limitacion` quedan para una ampliacion
posterior; no se calcula criticidad de activo todavia, asi que la severidad viene solo del score.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.evaluation.schemas import SCORING_STATES, CriterionResult
from app.methodology.loader import Methodology

#: Bandas de severidad por score (simplificado: sin ponderar criticidad de activo todavia).
_SEVERIDAD_ALTA_MAX = 25
_SEVERIDAD_MEDIA_MAX = 50


class Finding(BaseModel):
    criterion_id: str
    titulo: str
    tipo: str = "brecha"
    severidad: str
    score: float
    evidence_ids: list[str]


def _severidad(score: float) -> str:
    if score < _SEVERIDAD_ALTA_MAX:
        return "alta"
    if score < _SEVERIDAD_MEDIA_MAX:
        return "media"
    return "baja"


def derive_findings(methodology: Methodology, results: list[CriterionResult]) -> list[Finding]:
    """Un hallazgo por cada criterio puntuado por debajo de `planes.umbral_brecha`."""

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
    return findings
