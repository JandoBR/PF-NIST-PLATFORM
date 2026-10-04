"""Comparacion entre dos evaluaciones (docs/04 §6, UI-07): que criterios cambiaron y como se
movio el puntaje global."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.assessment_service import AssessmentNotFoundError, load_criterion_results
from app.evaluation import aggregation
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import (
    Assessment,
)
from app.recommendations.findings import derive_findings

#: Que le paso a un criterio entre las dos evaluaciones. "Sin puntaje" es `evidencia_insuficiente`,
#: `no_aplicable` o `error`: pasar de ahi a un puntaje no es mejorar ni empeorar, es que ahora hay
#: con que evaluarlo (y al reves).
MEJORA = "mejora"
RETROCESO = "retroceso"
AHORA_EVALUADO = "ahora_evaluado"
DEJO_DE_EVALUARSE = "dejo_de_evaluarse"
CAMBIO_DE_ESTADO = "cambio_de_estado"
IGUAL = "igual"


@dataclass
class CriterionDiff:
    criterion_id: str
    titulo: str
    estado_antes: str | None
    estado_despues: str | None
    score_antes: float | None
    score_despues: float | None
    #: La explicacion del criterio en cada evaluacion: el "por que" del cambio.
    explicacion_antes: str | None = None
    explicacion_despues: str | None = None

    @property
    def cambio(self) -> bool:
        return (self.estado_antes, self.score_antes) != (self.estado_despues, self.score_despues)

    @property
    def direccion(self) -> str:
        if not self.cambio:
            return IGUAL
        antes, despues = self.score_antes, self.score_despues
        if antes is None and despues is not None:
            return AHORA_EVALUADO
        if antes is not None and despues is None:
            return DEJO_DE_EVALUARSE
        if antes is None or despues is None or antes == despues:
            return CAMBIO_DE_ESTADO
        return MEJORA if despues > antes else RETROCESO


@dataclass
class ComparisonReport:
    assessment_id_a: str
    assessment_id_b: str
    diffs: list[CriterionDiff]
    global_antes: float | None
    global_despues: float | None
    #: Si difieren, parte de los cambios puede venir de las reglas o del alcance y no del entorno.
    misma_metodologia: bool = True
    mismo_scope: bool = True
    #: Criterios con hallazgo `brecha` en una evaluacion y no en la otra.
    hallazgos_resueltos: list[str] = field(default_factory=list)
    hallazgos_nuevos: list[str] = field(default_factory=list)

    @property
    def cambios(self) -> list[CriterionDiff]:
        return [d for d in self.diffs if d.cambio]


def compare(
    session: Session, methodology: Methodology, assessment_id_a: str, assessment_id_b: str
) -> ComparisonReport:
    antes = session.get(Assessment, assessment_id_a)
    despues = session.get(Assessment, assessment_id_b)
    for assessment_id, assessment in ((assessment_id_a, antes), (assessment_id_b, despues)):
        if assessment is None:
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
                explicacion_antes=ra.explanation if ra else None,
                explicacion_despues=rb.explanation if rb else None,
            )
        )

    brechas_a = _brechas(methodology, list(results_a.values()))
    brechas_b = _brechas(methodology, list(results_b.values()))
    global_antes = _global_score(methodology, list(results_a.values()))
    global_despues = _global_score(methodology, list(results_b.values()))

    return ComparisonReport(
        assessment_id_a=assessment_id_a,
        assessment_id_b=assessment_id_b,
        diffs=diffs,
        global_antes=global_antes,
        global_despues=global_despues,
        misma_metodologia=antes.methodology_version == despues.methodology_version,
        mismo_scope=antes.scope == despues.scope,
        hallazgos_resueltos=sorted(brechas_a - brechas_b),
        hallazgos_nuevos=sorted(brechas_b - brechas_a),
    )


def _brechas(methodology: Methodology, results: list[CriterionResult]) -> set[str]:
    return {f.criterion_id for f in derive_findings(methodology, results)}


def _global_score(methodology: Methodology, results: list[CriterionResult]) -> float | None:
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    return aggregation.aggregate_global(methodology, funciones).score
