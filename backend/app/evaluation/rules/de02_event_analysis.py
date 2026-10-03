"""CRI-DE-02 — Analisis de eventos y declaracion de incidentes (docs/03 §4).

Combina lo documental (`doc.claim(tipo=process_defined)`, con `contenido.criterios_declaracion`) con
lo operativo (`log.pattern`). Aplica la "regla de justicia" (docs/06 §5) literalmente: sin
`log.window` no se puede concluir nada; con ventana completa, solo se penaliza si hubo una
oportunidad real (`auth_failures_burst`) que no produjo alerta/declaracion.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, by_type, doc_claims
from app.evaluation.rules._common import result as build
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-DE-02"
CRITERION_VERSION = 1


def _patron(evidence: list[EvidenceInstance], patron: str) -> EvidenceInstance | None:
    for item in by_type(evidence, "log.pattern"):
        if item.value["patron"] == patron:
            return item
    return None


def _es_de_declaracion(claim: EvidenceInstance) -> bool:
    proceso = str(claim.value.get("contenido", {}).get("proceso", "")).lower()
    return any(
        palabra in proceso
        for palabra in ("incidente", "declaracion", "declaración", "evento", "analisis", "análisis")
    )


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    doc = [c for c in doc_claims(evidence, "process_defined") if _es_de_declaracion(c)]
    doc_mejor = best_found(doc)
    tiene_criterios = doc_mejor is not None and doc_mejor.value.get("contenido", {}).get(
        "criterios_declaracion"
    )
    doc_criterios = doc_mejor if tiene_criterios else None

    ventana = by_type(evidence, "log.window")
    if not ventana or not ventana[0].value["completo"]:
        # Igual que RC-02: sin eventos se evalua lo documental (docs/09 §60). Antes daba
        # evidencia_insuficiente aunque los documentos definieran criterios de declaracion.
        if doc_criterios:
            return build(
                CRITERION_ID,
                Estado.EVALUADO,
                75,
                "Criterios de declaracion documentados, sin evidencia operativa (sin ventana"
                " completa).",
                [doc_criterios.id],
            )
        if doc_mejor is not None:
            return build(
                CRITERION_ID,
                Estado.EVALUADO,
                50,
                "Analisis de eventos descrito sin criterios de declaracion concretos (sin ventana"
                " completa).",
                [doc_mejor.id],
            )
        return build(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin ventana de observacion completa ni criterios de declaracion documentados.",
        )

    alerta = _patron(evidence, "alert_raised")
    declarado = _patron(evidence, "incident_declared")
    oportunidad = _patron(evidence, "auth_failures_burst")
    positivo = alerta or declarado

    if oportunidad and not positivo:
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            "Hubo actividad que debia generar alerta (auth_failures_burst) y no la hubo: falla de"
            " deteccion con ventana completa (docs/06 §5).",
            [ventana[0].id, oportunidad.id],
        )
    if doc_criterios and positivo:
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Criterios de declaracion documentados y evidencia operativa de alerta/declaracion.",
            [ventana[0].id, positivo.id, doc_criterios.id],
        )
    if doc_criterios:
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Criterios de declaracion documentados, sin evidencia operativa en la ventana.",
            [ventana[0].id, doc_criterios.id],
        )
    if positivo:
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Evidencia operativa de alerta/declaracion, sin criterios de declaracion documentados.",
            [ventana[0].id, positivo.id],
        )
    if doc_mejor is not None:
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Analisis de eventos descrito sin criterios de declaracion concretos.",
            [ventana[0].id, doc_mejor.id],
        )
    return build(
        CRITERION_ID,
        Estado.EVIDENCIA_INSUFICIENTE,
        None,
        "Ventana completa sin ningun patron aplicable ni criterios documentados: sin"
        " oportunidad, no se penaliza (docs/06 §5).",
        [ventana[0].id],
    )
