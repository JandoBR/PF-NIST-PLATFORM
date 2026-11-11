"""CRI-RS-03 — Notificacion a partes interesadas (docs/03 §5, privacidad secundaria).

Documental (`doc.claim(tipo=notification_list)`): lista de notificacion con criterios y plazos.
Alimenta la vista de privacidad (docs/03 §7).

Sin destinatarios no hay lista: una afirmacion que no dice a quien se notifica no puntua (docs/03:
100 / 75 / 0, igual que `DE-03`). Antes daba 50 por "mencion generica"; ver docs/09 §47.
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    doc_claims,
    found,
    merged_content,
    result,
    silencio_documental,
)
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

    encontradas = found(claims)
    contenido, aportantes = merged_content(encontradas)
    if not contenido.get("destinatarios"):
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran a quien se notifica un incidente.",
            [c.id for c in encontradas or claims],
        )

    ids = [c.id for c in aportantes]
    criterios = bool(contenido.get("criterios"))
    plazos = bool(contenido.get("plazos"))

    if criterios and plazos:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Lista de notificacion con destinatarios, criterios y plazos.",
            ids,
        )

    # 100 exige los tres datos: una lista sin criterios no dice cuando notificar, y una sin
    # plazos no dice en cuanto tiempo. Cualquier lista con destinatarios sigue siendo 75.
    faltan = "criterios" if not criterios else "plazos"
    detalle = (
        f"Lista de notificacion definida, sin {faltan}."
        if criterios or plazos
        else "Lista de notificacion definida, sin criterios ni plazos."
    )
    return result(CRITERION_ID, Estado.EVALUADO, 75, detalle, ids)
