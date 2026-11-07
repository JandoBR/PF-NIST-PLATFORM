"""CRI-RC-02 — Verificacion de integridad de backups (docs/03 §6).

Mixto: politica que exige verificacion (`doc.claim(backup_policy).verificacion_integridad`) mas
evidencia operativa (`log.pattern`). `restore_exercise_run` con `resultado=fail` es la condicion del
disparador D4 (docs/08 §5). Sin ventana no se penaliza: se evalua solo lo documental como tope 75.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found_with, by_type, doc_claims, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RC-02"
CRITERION_VERSION = 1


def _patron(evidence: list[EvidenceInstance], patron: str) -> EvidenceInstance | None:
    for item in by_type(evidence, "log.pattern"):
        if item.value["patron"] == patron:
            return item
    return None


def _verificacion_documentada(claim: EvidenceInstance) -> bool:
    return bool((claim.value.get("contenido") or {}).get("verificacion_integridad"))


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    verificacion = best_found_with(doc_claims(evidence, "backup_policy"), "verificacion_integridad")
    doc_verifica = verificacion is not None and _verificacion_documentada(verificacion)

    ventana = by_type(evidence, "log.window")
    if not ventana or not ventana[0].value["completo"]:
        if doc_verifica:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                75,
                "Politica de backups exige verificacion de integridad, sin evidencia operativa"
                " (sin ventana completa).",
                [verificacion.id],
            )
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin ventana de observacion completa ni politica que exija verificacion.",
        )

    ejercicio = _patron(evidence, "restore_exercise_run")
    verificado = _patron(evidence, "restore_verified")

    if ejercicio is not None and ejercicio.value["resultado"] == "fail":
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            "Ejercicio de restauracion fallido observado en la ventana.",
            [ventana[0].id, ejercicio.id],
        )

    if verificado is not None and doc_verifica:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Politica exige verificacion de integridad y el escenario evidencia restauracion"
            " verificada.",
            [ventana[0].id, verificacion.id, verificado.id],
        )

    if verificado is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Restauracion verificada en la ventana (sin politica documentada aun): puntaje maximo"
            " 75.",
            [ventana[0].id, verificado.id],
        )

    if ejercicio is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Ejercicio de restauracion exitoso sin verificacion final.",
            [ventana[0].id, ejercicio.id],
        )

    if doc_verifica:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Politica de backups exige verificacion de integridad, sin evidencia operativa en la"
            " ventana.",
            [ventana[0].id, verificacion.id],
        )

    return result(
        CRITERION_ID,
        Estado.EVIDENCIA_INSUFICIENTE,
        None,
        "Ventana completa sin ningun patron aplicable ni politica de verificacion: sin"
        " oportunidad, no se penaliza (docs/06 §5).",
        [ventana[0].id],
    )
