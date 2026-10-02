"""CRI-GV-02 — Roles y responsabilidades definidos (docs/03 §1).

Documental puro (`doc.claim(tipo=role_assigned)`): sin evidencia tecnica que lo contradiga, la
decision depende de lo que la extraccion pudo citar (mismo patron que CRI-GV-01).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-02"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "role_assigned")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre roles y"
            " responsabilidades.",
        )

    mejor = best_found(claims)
    if mejor is None:
        return result(
            CRITERION_ID,
            Estado.NO_IMPLEMENTADO,
            0,
            "Los documentos analizados no declaran roles ni responsabilidades.",
            [c.id for c in claims],
        )

    roles = mejor.value.get("contenido", {}).get("roles") or []
    roles_validos = [r for r in roles if isinstance(r, dict)]

    if any(r.get("autoridad") for r in roles_validos):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Roles con responsables y autoridad descritos.",
            [mejor.id],
        )
    if roles_validos:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Responsables definidos sin autoridad explicita.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Roles genericos mencionados sin asignacion concreta de responsables.",
        [mejor.id],
    )
