"""CRI-DE-02 — Analisis de eventos y declaracion de incidentes (docs/03 §4).

Simplificado a `log.pattern`/`log.window` solamente (sin `doc.claim` todavia): el tope sin
criterios de declaracion documentados es 75, igual patron que CRI-PR-02 sin politica.

Aplica la "regla de justicia" (docs/06 §5) literalmente: sin `log.window` no se puede concluir
nada; con ventana completa, solo se penaliza si hubo una oportunidad real (`auth_failures_burst`)
que no produjo alerta/declaracion.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-DE-02"
CRITERION_VERSION = 1


def _patron(evidence: list[EvidenceInstance], patron: str) -> EvidenceInstance | None:
    for item in by_type(evidence, "log.pattern"):
        if item.value["patron"] == patron:
            return item
    return None


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    ventana = by_type(evidence, "log.window")
    if not ventana or not ventana[0].value["completo"]:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Sin ventana de observacion completa: no se puede concluir.",
        )

    alerta = _patron(evidence, "alert_raised")
    declarado = _patron(evidence, "incident_declared")
    oportunidad = _patron(evidence, "auth_failures_burst")

    if alerta or declarado:
        presente = alerta or declarado
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=75,
            final_score=75,
            explanation="Evidencia operativa de alerta/declaracion en la ventana "
            "(sin criterios de declaracion documentados aun): puntaje maximo 75.",
            evidence_ids=[ventana[0].id, presente.id],
        )

    if oportunidad:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=0,
            final_score=0,
            explanation="Hubo actividad que debia generar alerta (auth_failures_burst) y no la"
            " hubo: falla de deteccion con ventana completa (docs/06 §5).",
            evidence_ids=[ventana[0].id, oportunidad.id],
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVIDENCIA_INSUFICIENTE,
        explanation="Ventana completa sin ningun patron aplicable: sin oportunidad, no se"
        " penaliza (docs/06 §5).",
        evidence_ids=[ventana[0].id],
    )
