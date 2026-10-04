"""CRI-RC-03 — Restauracion verificada y comunicacion de recuperacion (docs/03 §6).

Mixto: el 100 exige `log.pattern(restore_verified)` mas la comunicacion **evidenciada**
(`recovery_communicated`). Una lista de notificacion documentada (`doc.claim(notification_list)` con
destinatarios) se cita, pero no sustituye a la comunicacion observada: antes daba 100 mientras el
disparador D5 (docs/08 §5) abria un incidente por esa misma comunicacion faltante.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found_with, by_type, doc_claims, result
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
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin ventana de observacion completa: no se puede concluir.",
        )

    verificado = _patron(evidence, "restore_verified")
    comunicado = _patron(evidence, "recovery_communicated")
    ejercicio = _patron(evidence, "restore_exercise_run")
    # Sin destinatarios no hay lista (docs/09 §47): igual que en DE-03 y RS-03.
    notificacion = best_found_with(doc_claims(evidence, "notification_list"), "destinatarios")

    if verificado is not None and comunicado is not None:
        ids = [ventana[0].id, verificado.id, comunicado.id]
        if notificacion is not None:
            ids.append(notificacion.id)
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Restauracion verificada y comunicacion de recuperacion evidenciada en la ventana.",
            ids,
        )

    if verificado is not None and notificacion is not None:
        # Saber a quien avisar no prueba que se aviso: sin `recovery_communicated` el tope es 75,
        # como en los demas criterios mixtos sin evidencia operativa.
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Restauracion verificada y lista de notificacion documentada, sin comunicacion de"
            " recuperacion observada.",
            [ventana[0].id, verificado.id, notificacion.id],
        )

    if verificado is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Restauracion verificada sin comunicacion de recuperacion observada.",
            [ventana[0].id, verificado.id],
        )

    if ejercicio is not None and ejercicio.value["resultado"] == "ok":
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Recuperacion ejecutada sin verificacion final.",
            [ventana[0].id, ejercicio.id],
        )

    return result(
        CRITERION_ID,
        Estado.EVIDENCIA_INSUFICIENTE,
        None,
        "Ventana completa sin ningun patron aplicable: sin oportunidad, no se penaliza"
        " (docs/06 §5).",
        [ventana[0].id],
    )
