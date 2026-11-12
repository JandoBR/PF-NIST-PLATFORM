"""CRI-RS-04 — Contencion y erradicacion del incidente (docs/03 §5).

Mixto: el patron `containment_done` (que hasta ahora se agregaba sin que ningun criterio lo
consumiera, docs/09 §53) mas el proceso documentado de contencion/erradicacion
(`doc.claim(process_defined)`). La regla de justicia (docs/06 §5) se aplica igual que en CRI-RS-01:
un `incident_declared` sin contencion dentro de una ventana completa es una falla de mitigacion,
y sin ventana completa no se concluye nada de lo operativo.

`RS.MI-01` (contener) la evidencia el patron; `RS.MI-02` (erradicar) descansa en la parte
documental, porque ningun evento del contrato declara la erradicacion por si solo.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, by_type, doc_claims, latest_pattern, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RS-04"
CRITERION_VERSION = 1


def _es_de_contencion(claim: EvidenceInstance) -> bool:
    proceso = str((claim.value.get("contenido") or {}).get("proceso", "")).lower()
    return any(
        palabra in proceso
        for palabra in (
            "contencion",
            "contención",
            "erradicacion",
            "erradicación",
            "mitigacion",
            "mitigación",
        )
    )


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    candidatos = [c for c in doc_claims(evidence, "process_defined") if _es_de_contencion(c)]
    plan = best_found(candidatos)
    con_pasos = plan is not None and bool((plan.value.get("contenido") or {}).get("pasos"))

    contenido = latest_pattern(evidence, "containment_done")
    declarado = latest_pattern(evidence, "incident_declared")
    ventana = by_type(evidence, "log.window")
    completa = bool(ventana and ventana[0].value["completo"])

    if not completa:
        if con_pasos:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                75,
                "Procedimiento de contencion y erradicacion documentado, sin evidencia operativa"
                " (sin ventana completa).",
                [plan.id],
            )
        if plan is not None:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                50,
                "Contencion descrita de forma generica, sin pasos ni evidencia operativa.",
                [plan.id],
            )
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin ventana de observacion completa ni procedimiento de contencion documentado.",
            [c.id for c in candidatos],
        )

    ids = [e.id for e in (ventana[0], plan, contenido) if e is not None]

    if contenido is not None:
        if con_pasos:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                100,
                "Contencion observada en la ventana y procedimiento de contencion/erradicacion"
                " documentado.",
                ids,
            )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Contencion observada en la ventana, sin procedimiento documentado: puntaje maximo 75.",
            ids,
        )

    if declarado is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            "Incidente declarado sin contencion dentro de la ventana observada: falla de"
            " mitigacion (docs/06 §5).",
            [ventana[0].id, declarado.id],
        )

    if con_pasos:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Procedimiento de contencion y erradicacion documentado, sin incidentes que contener"
            " en la ventana.",
            [ventana[0].id, plan.id],
        )
    if plan is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Contencion descrita de forma generica, sin evidencia operativa en la ventana.",
            [ventana[0].id, plan.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVIDENCIA_INSUFICIENTE,
        None,
        "Ventana completa sin incidentes ni procedimiento documentado: sin oportunidad, no se"
        " penaliza (docs/06 §5).",
        [ventana[0].id],
    )
