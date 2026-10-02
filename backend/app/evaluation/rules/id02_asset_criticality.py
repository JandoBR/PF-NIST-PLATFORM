"""CRI-ID-02 — Priorizacion de activos por criticidad (docs/03 §2).

Documental (`doc.claim(tipo=data_inventory)`), usando el campo `criticidad`/`clasificacion` del
inventario. `ctx.profile` (activos criticos declarados en contexto) aun no existe como pipeline
(docs/11 OP-01/OP-09), asi que la consistencia con el contexto no se contrasta todavia.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-02"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "data_inventory")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre clasificacion de"
            " activos.",
        )

    mejor = best_found(claims)
    if mejor is None:
        return result(
            CRITERION_ID,
            Estado.NO_IMPLEMENTADO,
            0,
            "Los documentos analizados no declaran clasificacion de activos por criticidad.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido", {})
    criticidad = contenido.get("criticidad") or contenido.get("clasificacion")
    if isinstance(criticidad, (list, dict)) and criticidad:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Clasificacion de criticidad documentada por activo.",
            [mejor.id],
        )
    if criticidad:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Criticidad mencionada de forma generica, sin criterios por activo.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.NO_IMPLEMENTADO,
        0,
        "El inventario documentado no clasifica los activos por criticidad.",
        [mejor.id],
    )
