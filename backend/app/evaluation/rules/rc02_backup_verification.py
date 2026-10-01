"""CRI-RC-02 — Verificacion de integridad de backups (docs/03 §6).

Simplificado a `log.pattern`/`log.window` (sin `doc.claim` todavia: tope 75). `restore_exercise_run`
con `resultado=fail` es exactamente la condicion del disparador D4 (docs/08 §5).
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RC-02"
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

    ejercicio = _patron(evidence, "restore_exercise_run")
    verificado = _patron(evidence, "restore_verified")

    if ejercicio and ejercicio.value["resultado"] == "fail":
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=0,
            final_score=0,
            explanation="Ejercicio de restauracion fallido observado en la ventana.",
            evidence_ids=[ventana[0].id, ejercicio.id],
        )

    if verificado:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=75,
            final_score=75,
            explanation="Restauracion verificada en la ventana (sin politica documentada aun):"
            " puntaje maximo 75.",
            evidence_ids=[ventana[0].id, verificado.id],
        )

    if ejercicio:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=50,
            final_score=50,
            explanation="Ejercicio de restauracion exitoso sin verificacion final.",
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
