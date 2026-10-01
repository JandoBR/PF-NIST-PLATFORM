"""CRI-RC-03 — Restauracion verificada y comunicacion de recuperacion (docs/03 §6).

A diferencia de CRI-DE-02/RS-01/RC-02, aqui el 100 SI es alcanzable solo con `log.pattern`: la
regla documentada pide comunicacion "definida/evidenciada" (un "o", no un "y" con lo documental
como en los otros tres criterios simplificados), y `recovery_communicated` es exactamente esa
evidencia operativa. `restore_verified` sin `recovery_communicated` es la condicion del
disparador D5 (docs/08 §5).
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RC-03"
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

    verificado = _patron(evidence, "restore_verified")
    comunicado = _patron(evidence, "recovery_communicated")
    ejercicio = _patron(evidence, "restore_exercise_run")

    if verificado and comunicado:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=100,
            final_score=100,
            explanation="Restauracion verificada y comunicacion de recuperacion evidenciadas"
            " en la ventana.",
            evidence_ids=[ventana[0].id, verificado.id, comunicado.id],
        )

    if verificado:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=75,
            final_score=75,
            explanation="Restauracion verificada sin comunicacion de recuperacion observada.",
            evidence_ids=[ventana[0].id, verificado.id],
        )

    if ejercicio and ejercicio.value["resultado"] == "ok":
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=50,
            final_score=50,
            explanation="Recuperacion ejecutada sin verificacion final.",
            evidence_ids=[ventana[0].id, ejercicio.id],
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVIDENCIA_INSUFICIENTE,
        explanation="Ventana completa sin ningun patron aplicable: sin oportunidad, no se"
        " penaliza (docs/06 §5).",
        evidence_ids=[ventana[0].id],
    )
