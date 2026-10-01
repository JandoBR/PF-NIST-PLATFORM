"""CRI-RS-01 — Plan de respuesta con clasificacion y escalamiento (docs/03 §5).

Simplificado a `log.pattern`/`log.window` (sin `doc.claim` todavia: tope 75 sin plan
documentado). `incident_declared` sin `escalation_done` en una ventana completa es exactamente
la condicion del disparador D3 (docs/08 §5) — aqui alimenta madurez, no abre un incidente.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RS-01"
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

    escalado = _patron(evidence, "escalation_done")
    declarado = _patron(evidence, "incident_declared")

    if escalado:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=75,
            final_score=75,
            explanation="Evidencia operativa de escalamiento en la ventana (sin plan"
            " documentado aun): puntaje maximo 75.",
            evidence_ids=[ventana[0].id, escalado.id],
        )

    if declarado:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=0,
            final_score=0,
            explanation="Incidente declarado sin escalamiento dentro de la ventana observada:"
            " falla de respuesta con ventana completa (docs/06 §5).",
            evidence_ids=[ventana[0].id, declarado.id],
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVIDENCIA_INSUFICIENTE,
        explanation="Ventana completa sin ningun patron aplicable: sin oportunidad, no se"
        " penaliza (docs/06 §5).",
        evidence_ids=[ventana[0].id],
    )
