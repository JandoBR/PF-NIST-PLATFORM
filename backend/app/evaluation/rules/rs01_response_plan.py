"""CRI-RS-01 — Plan de respuesta con clasificacion y escalamiento (docs/03 §5).

Mixto: plan documentado (`process_defined` de respuesta y/o `escalation_path`) mas evidencia
operativa (`log.pattern(escalation_done)`). La regla de justicia (docs/06 §5) se mantiene:
`incident_declared` sin `escalation_done` en una ventana completa es falla de respuesta.
"""

from __future__ import annotations

from datetime import datetime

from app.evaluation.rules._common import best_found, by_type, doc_claims, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RS-01"
CRITERION_VERSION = 1


def _patron(evidence: list[EvidenceInstance], patron: str) -> EvidenceInstance | None:
    for item in by_type(evidence, "log.pattern"):
        if item.value["patron"] == patron:
            return item
    return None


def _es_de_respuesta(claim: EvidenceInstance) -> bool:
    proceso = str((claim.value.get("contenido") or {}).get("proceso", "")).lower()
    return any(p in proceso for p in ("respuesta", "response", "escalamiento", "escalation"))


def _ventana_completa(evidence: list[EvidenceInstance]) -> bool:
    ventana = by_type(evidence, "log.window")
    return bool(ventana and ventana[0].value["completo"])


def _momento(pattern: EvidenceInstance | None, clave: str) -> datetime | None:
    if pattern is None:
        return None
    try:
        return datetime.fromisoformat(str(pattern.value[clave]))
    except (KeyError, TypeError, ValueError):
        return None


def _escalamiento_posterior(
    escalado: EvidenceInstance | None, declarado: EvidenceInstance | None
) -> bool:
    """Solo cuenta un escalamiento cuyo ultimo evento es posterior a la declaracion.

    Un `escalation_done` anterior al `incident_declared` no es respuesta a ese incidente
    (docs/08 §5, D3). Se usa `hasta` para admitir varias escalaciones en el patron: si la
    ultima es posterior, hay al menos una que lo es.
    """

    inicio = _momento(declarado, "hasta")
    fin = _momento(escalado, "hasta")
    return inicio is not None and fin is not None and fin > inicio


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    plan = best_found([c for c in doc_claims(evidence, "process_defined") if _es_de_respuesta(c)])
    escalation = best_found(doc_claims(evidence, "escalation_path"))
    escalado = _patron(evidence, "escalation_done")
    declarado = _patron(evidence, "incident_declared")
    completa = _ventana_completa(evidence)
    posterior = _escalamiento_posterior(escalado, declarado)

    if plan is None and escalation is None:
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

    contenido = plan.value.get("contenido", {}) if plan is not None else {}
    completo = bool(plan is not None and contenido.get("pasos") and contenido.get("responsables"))
    ids = [e.id for e in (plan, escalation, escalado, declarado) if e is not None]

    if posterior:
        score = 100 if completo else 75
        detalle = "plan documentado completo" if completo else "plan documentado parcial"
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

    score = 75 if completo else 50
    nota = "" if completa else " (sin ventana completa: evaluacion documental)"
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        score,
        f"Plan de respuesta documentado sin evidencia operativa reciente{nota}.",
        ids,
    )
