"""CRI-DE-03 — Informacion de eventos a personal y herramientas (docs/03 §4).

Mixto: destinatarios declarados (`doc.claim(tipo=notification_list)`) + evidencia operativa de
alerta (`log.pattern(alert_raised)`).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, by_type, doc_claims
from app.evaluation.rules._common import result as build
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-DE-03"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "notification_list")
    alerta = next(
        (e for e in by_type(evidence, "log.pattern") if e.value.get("patron") == "alert_raised"),
        None,
    )

    if not claims and alerta is None:
        return build(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin destinatarios declarados ni evidencia operativa de alerta.",
        )

    mejor = best_found(claims)
    destinatarios = (
        mejor.value.get("contenido", {}).get("destinatarios") if mejor is not None else None
    )

    if destinatarios and alerta is not None:
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Alertas llegan a destinatarios definidos y el escenario lo evidencia.",
            [mejor.id, alerta.id],
        )
    if destinatarios:
        return build(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Destinatarios de alertas definidos, sin evidencia operativa en la ventana.",
            [mejor.id],
        )
    return build(
        CRITERION_ID,
        Estado.NO_IMPLEMENTADO,
        0,
        "Hay eventos de alerta, pero no se declaran destinatarios definidos.",
        [e.id for e in (claims or ([alerta] if alerta else []))],
    )
