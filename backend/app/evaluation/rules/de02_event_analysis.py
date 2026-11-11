"""CRI-DE-02 — Analisis de eventos y declaracion de incidentes (docs/03 §4).

Combina lo documental (`doc.claim(tipo=process_defined)`, con `contenido.criterios_declaracion`) con
lo operativo (`log.pattern`). Aplica la "regla de justicia" (docs/06 §5) literalmente: sin
`log.window` no se puede concluir nada; con ventana completa, solo se penaliza si hubo una
oportunidad real (`auth_failures_burst`) que no produjo alerta/declaracion.

`DE.AE-03` ("la informacion se correlaciona a partir de multiples fuentes") es la razon del
ancla del 100: no basta con que se haya alertado, el patron tiene que venir de **dos origenes
distintos** (`log.pattern@2.fuentes`). Un solo origen es deteccion, no correlacion.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, by_type, doc_claims, latest_pattern
from app.evaluation.rules._common import result as build
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-DE-02"
CRITERION_VERSION = 2


def _fuentes(patron: EvidenceInstance) -> list[str]:
    """Origenes del patron. `log.pattern@1` no los traia: ahi la lista es vacia y nunca se
    afirma correlacion (no se penaliza por ello, solo no se llega al 100)."""

    valor = patron.value.get("fuentes") or []
    return sorted({str(f) for f in valor if str(f).strip()})


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

    alerta = latest_pattern(evidence, "alert_raised")
    declarado = latest_pattern(evidence, "incident_declared")
    oportunidad = latest_pattern(evidence, "auth_failures_burst")
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
        fuentes = _fuentes(positivo)
        if len(fuentes) >= 2:
            return build(
                CRITERION_ID,
                Estado.EVALUADO,
                100,
                "Criterios de declaracion documentados y evidencia operativa correlacionada desde"
                f" {len(fuentes)} fuentes ({', '.join(fuentes)}).",
                [ventana[0].id, positivo.id, doc_criterios.id],
            )
        unica = f" (solo {fuentes[0]})" if fuentes else " (ningun evento declara origen)"
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Criterios de declaracion documentados y evidencia operativa de alerta/declaracion,"
            f" pero de un solo origen{unica}: no hay correlacion entre fuentes (DE.AE-03).",
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
