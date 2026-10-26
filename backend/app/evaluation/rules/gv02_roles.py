"""CRI-GV-02 — Roles y responsabilidades definidos (docs/03 §1).

Documental puro (`doc.claim(tipo=role_assigned)`): sin evidencia tecnica que lo contradiga, la
decision depende de lo que la extraccion pudo citar (mismo patron que CRI-GV-01).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-02"
CRITERION_VERSION = 1


def _texto(valor: object) -> bool:
    """Campo textual con contenido real (no `None`, no cadena vacia)."""

    return isinstance(valor, str) and bool(valor.strip())


def _nivel_roles(roles: object) -> int:
    """100 = rol con responsable, responsabilidades y autoridad; 75 = responsable sin el resto;
    50 = roles genericos o sin responsable nombrado (docs/03 §1)."""

    if not isinstance(roles, list):
        return 50
    validos = [r for r in roles if isinstance(r, dict) and _texto(r.get("rol"))]
    if not validos:
        return 50
    if any(
        _texto(r.get("responsable"))
        and _texto(r.get("responsabilidades"))
        and _texto(r.get("autoridad"))
        for r in validos
    ):
        return 100
    if any(_texto(r.get("responsable")) for r in validos):
        return 75
    return 50


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

    encontradas = [c for c in claims if c.value.get("encontrado")]
    if not encontradas:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran roles ni responsabilidades.",
            [c.id for c in claims],
        )

    niveles = [(_nivel_roles(c.value.get("contenido", {}).get("roles")), c) for c in encontradas]
    nivel = max(n for n, _ in niveles)
    mejor = best_found([c for n, c in niveles if n == nivel])
    assert mejor is not None

    if nivel == 100:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Roles con responsable nombrado, responsabilidades y autoridad descritas.",
            [mejor.id],
        )
    if nivel == 75:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Responsable nombrado, pero sin responsabilidades o autoridad explicitas.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Roles genericos o sin un responsable nombrado.",
        [mejor.id],
    )
