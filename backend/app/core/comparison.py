"""Comparacion entre dos evaluaciones (docs/04 §6, UI-07): que criterios cambiaron y como se
movio el puntaje global."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.assessment_service import AssessmentNotFoundError, load_criterion_results
from app.evaluation import aggregation
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import (
    Assessment,
)


@dataclass
class CriterionDiff:
    criterion_id: str
    titulo: str
    estado_antes: str | None
    estado_despues: str | None
    score_antes: float | None
    score_despues: float | None

    @property
    def cambio(self) -> bool:
        return (self.estado_antes, self.score_antes) != (self.estado_despues, self.score_despues)


@dataclass
class ComparisonReport:
    assessment_id_a: str
    assessment_id_b: str
    diffs: list[CriterionDiff]
    global_antes: float | None
    global_despues: float | None

    @property
    def cambios(self) -> list[CriterionDiff]:
        return [d for d in self.diffs if d.cambio]


def compare(
    session: Session, methodology: Methodology, assessment_id_a: str, assessment_id_b: str
) -> ComparisonReport:
    for assessment_id in (assessment_id_a, assessment_id_b):
        if session.get(Assessment, assessment_id) is None:
            raise AssessmentNotFoundError(assessment_id)

    results_a = {r.criterion_id: r for r in load_criterion_results(session, assessment_id_a)}
    results_b = {r.criterion_id: r for r in load_criterion_results(session, assessment_id_b)}

    diffs = []
    for criterion_id in sorted(set(results_a) | set(results_b)):
        ra, rb = results_a.get(criterion_id), results_b.get(criterion_id)
        criterio = methodology.criterios.get(criterion_id)
        diffs.append(
            CriterionDiff(
                criterion_id=criterion_id,
                titulo=criterio.titulo if criterio else criterion_id,
                estado_antes=ra.estado.value if ra else None,
                estado_despues=rb.estado.value if rb else None,
                score_antes=ra.final_score if ra else None,
                score_despues=rb.final_score if rb else None,
            )
        )

    global_antes = _global_score(methodology, list(results_a.values()))
    global_despues = _global_score(methodology, list(results_b.values()))

    return ComparisonReport(
        assessment_id_a=assessment_id_a,
        assessment_id_b=assessment_id_b,
        diffs=diffs,
        global_antes=global_antes,
        global_despues=global_despues,
    )


def _global_score(methodology: Methodology, results: list[CriterionResult]) -> float | None:
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    return aggregation.aggregate_global(methodology, funciones).score
