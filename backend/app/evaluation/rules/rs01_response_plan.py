"""CRI-RS-01 — Plan de respuesta con clasificacion y escalamiento (docs/03 §5).

Mixto: plan documentado (`process_defined` de respuesta y/o `escalation_path`) mas evidencia
operativa (`log.pattern(escalation_done)`). La regla de justicia (docs/06 §5) se mantiene:
`incident_declared` sin `escalation_done` en una ventana completa es falla de respuesta.

`RS.MA-05` ("se aplican los criterios para iniciar la recuperacion del incidente") entra por
`contenido.criterios_recuperacion`, un campo propio y **no** `criterios_activacion`: en un
proceso de respuesta ese campo son los criterios para activar la respuesta, no para pasar a la
recuperacion, y ademas es el que `CRI-RC-01` ya lee del proceso de recuperacion en su ancla del
100. Un plan sin el traspaso documentado no llega al 100.
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    best_found,
    by_type,
    doc_claims,
    found,
    latest_pattern,
    merged_content,
    pattern_moment,
    result,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RS-01"
CRITERION_VERSION = 2


def _es_de_respuesta(claim: EvidenceInstance) -> bool:
    proceso = str((claim.value.get("contenido") or {}).get("proceso", "")).lower()
    return any(p in proceso for p in ("respuesta", "response", "escalamiento", "escalation"))


def _ventana_completa(evidence: list[EvidenceInstance]) -> bool:
    ventana = by_type(evidence, "log.window")
    return bool(ventana and ventana[0].value["completo"])


def _escalamiento_posterior(
    escalado: EvidenceInstance | None, declarado: EvidenceInstance | None
) -> bool:
    """Solo cuenta un escalamiento cuyo ultimo evento es posterior a la declaracion.

    Un `escalation_done` anterior al `incident_declared` no es respuesta a ese incidente
    (docs/08 §5, D3). Se usa el patron mas reciente (`_common.latest_pattern`) y su `hasta`:
    con varias escalaciones vale la ultima, y si es posterior, hay al menos una que lo es.
    """

    inicio = pattern_moment(declarado, "hasta")
    fin = pattern_moment(escalado, "hasta")
    return inicio is not None and fin is not None and fin > inicio


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    planes = found([c for c in doc_claims(evidence, "process_defined") if _es_de_respuesta(c)])
    contenido, aportantes = merged_content(planes)
    escalation = best_found(doc_claims(evidence, "escalation_path"))
    escalado = latest_pattern(evidence, "escalation_done")
    declarado = latest_pattern(evidence, "incident_declared")
    completa = _ventana_completa(evidence)
    posterior = _escalamiento_posterior(escalado, declarado)

    if not planes and escalation is None:
        if completa and declarado is not None and not posterior:
            ventana = by_type(evidence, "log.window")
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                0,
                "Incidente declarado sin escalamiento posterior dentro de la ventana observada:"
                " falla de respuesta (docs/06 §5, docs/08 §5).",
                [ventana[0].id, declarado.id],
            )
        if escalado is not None:
            ventana = by_type(evidence, "log.window")
            ids = [e.id for e in (ventana[0], escalado) if e is not None]
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                75,
                "Evidencia operativa de escalamiento sin plan de respuesta documentado: puntaje"
                " maximo 75.",
                ids,
            )
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin plan de respuesta documentado ni evidencia operativa suficiente.",
        )

    completo = bool(
        contenido.get("pasos")
        and contenido.get("responsables")
        and contenido.get("criterios_recuperacion")
    )
    ids = [c.id for c in aportantes]
    ids += [e.id for e in (escalation, escalado, declarado) if e is not None]

    if posterior:
        score = 100 if completo else 75
        detalle = (
            "plan documentado completo"
            if completo
            else "plan documentado parcial (faltan pasos, responsables o los criterios para"
            " iniciar la recuperacion)"
        )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            score,
            f"Evidencia operativa de escalamiento posterior al incidente declarado; {detalle}.",
            ids + [escalado.id],
        )

    if completa and declarado is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            "Incidente declarado sin escalamiento posterior dentro de la ventana observada: falla"
            " de respuesta (docs/06 §5, docs/08 §5).",
            ids + [declarado.id],
        )

    if escalado is not None:
        # Escalamiento observado, pero no asociado a un incidente declarado (o con ventana
        # incompleta): es evidencia operativa parcial, tope 75 (docs/03 §5).
        detalle = (
            "plan documentado completo"
            if completo
            else "plan documentado parcial (faltan pasos, responsables o los criterios para"
            " iniciar la recuperacion)"
        )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Evidencia operativa de escalamiento sin un incidente declarado asociado;"
            f" {detalle}; el plan no llega al 100.",
            ids + [escalado.id],
        )

    score = 75 if completo else 50
    nota = "" if completa else " (sin ventana completa: evaluacion documental)"
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        score,
        f"Plan de respuesta documentado sin evidencia operativa reciente{nota}.",
        ids,
    )
