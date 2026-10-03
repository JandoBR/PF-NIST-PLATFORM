"""CRI-ID-04 — Inventario de datos y metadatos (docs/03 §2, privacidad secundaria).

Documental (`doc.claim(tipo=data_inventory)`): el 100 exige tipos de datos **y** clasificacion
(incluye datos personales). Alimenta la vista de privacidad (docs/03 §7).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-04"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "data_inventory")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre inventario de datos.",
        )

    mejor = best_found(claims)
    if mejor is None:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un inventario de datos.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido", {})
    tipos = contenido.get("tipos_datos")
    clasificacion = contenido.get("clasificacion")

    if tipos and clasificacion:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Inventario de datos con tipos y clasificacion (incluye datos personales).",
            [mejor.id],
        )
    if tipos or clasificacion:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Inventario de datos parcial, sin tipos o sin clasificacion.",
            [mejor.id],
        )
    return silencio_documental(
        CRITERION_ID,
        "El inventario documentado no describe tipos de datos ni su clasificacion.",
        [mejor.id],
    )
