"""CRI-RS-03 — Notificacion a partes interesadas (docs/03 §5, privacidad secundaria).

Documental (`doc.claim(tipo=notification_list)`): lista de notificacion con criterios y plazos.
Alimenta la vista de privacidad (docs/03 §7).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RS-03"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "notification_list")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre notificacion a"
            " interesados.",
        )

    mejor = best_found(claims)
    if mejor is None:
        return result(
            CRITERION_ID,
            Estado.NO_IMPLEMENTADO,
            0,
            "Los documentos analizados no declaran a quien se notifica un incidente.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido", {})
    destinatarios = contenido.get("destinatarios")
    if destinatarios and contenido.get("plazos"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Lista de notificacion con destinatarios, criterios y plazos.",
            [mejor.id],
        )
    if destinatarios:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Lista de notificacion definida, sin plazos.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Notificacion a interesados mencionada de forma generica.",
        [mejor.id],
    )
