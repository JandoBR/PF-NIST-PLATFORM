"""CRI-RC-02 — Verificacion de integridad de backups (docs/03 §6).

Mixto: politica que exige verificacion (`doc.claim(backup_policy).verificacion_integridad`) mas
evidencia operativa (`log.pattern`). `restore_exercise_run` con `resultado=fail` es la condicion del
disparador D4 (docs/08 §5). Sin ventana no se penaliza: se evalua solo lo documental como tope 75.
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    best_found_with,
    by_type,
    doc_claims,
    latest_pattern,
    pattern_moment,
    result,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RC-02"
CRITERION_VERSION = 1


def _verificacion_documentada(claim: EvidenceInstance) -> bool:
    return bool((claim.value.get("contenido") or {}).get("verificacion_integridad"))


def _superado_por_verificacion(
    ejercicio: EvidenceInstance | None, verificado: EvidenceInstance | None
) -> bool:
    """Un ejercicio fallido no condena el criterio si una verificacion posterior lo supera.

    La ventana puede traer un fallo y despues una restauracion verificada; RC-03 cuenta esa
    verificacion como 100, asi que RC-02 no puede quedarse en 0 por un estado que la ventana ya
    dejo atras. Sin marcas de tiempo no se asume la superacion: se mantiene el 0 conservador.
    """

    if ejercicio is None or ejercicio.value.get("resultado") != "fail" or verificado is None:
        return False
    fin_fallo = pattern_moment(ejercicio, "hasta")
    fin_verificado = pattern_moment(verificado, "hasta")
    return fin_fallo is not None and fin_verificado is not None and fin_verificado > fin_fallo


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

    ejercicio = latest_pattern(evidence, "restore_exercise_run")
    verificado = latest_pattern(evidence, "restore_verified")
    superado = _superado_por_verificacion(ejercicio, verificado)

    if ejercicio is not None and ejercicio.value["resultado"] == "fail" and not superado:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            "Ejercicio de restauracion fallido observado en la ventana.",
            [ventana[0].id, ejercicio.id],
        )

    if verificado is not None and doc_verifica:
        nota = (
            " El ejercicio fallido anterior queda superado por la verificacion posterior."
            if superado
            else ""
        )
        ids = [ventana[0].id, verificacion.id, verificado.id]
        if superado:
            ids.append(ejercicio.id)
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Politica exige verificacion de integridad y el escenario evidencia restauracion"
            f" verificada.{nota}",
            ids,
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
