"""CRI-GV-02 — Roles y responsabilidades definidos (docs/03 §1).

Documental puro (`doc.claim(tipo=role_assigned)`): sin evidencia tecnica que lo contradiga, la
decision depende de lo que la extraccion pudo citar (mismo patron que CRI-GV-01).

Cubre las cuatro subcategorias de `GV.RR`: los roles con responsable y autoridad
(`GV.RR-01`/`GV.RR-02`) son la puerta, y para el 100 hacen falta las otras dos facetas de la
categoria -- recursos acordes a la estrategia (`GV.RR-03`) y la ciberseguridad en las practicas de
recursos humanos (`GV.RR-04`). Nombrar a un CISO no es dotar a la funcion.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-02"
CRITERION_VERSION = 2


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
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran roles ni responsabilidades.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido", {})
    roles = contenido.get("roles") or []
    roles_validos = [r for r in roles if isinstance(r, dict)]
    recursos = bool(contenido.get("recursos_asignados"))
    practicas_rh = bool(contenido.get("practicas_rh"))

    if any(r.get("autoridad") for r in roles_validos):
        if recursos and practicas_rh:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                100,
                "Roles con responsables y autoridad, recursos asignados acordes a la estrategia de"
                " riesgo y la ciberseguridad incorporada a las practicas de recursos humanos.",
                [mejor.id],
            )
        faltan = ", ".join(
            texto
            for texto, presente in (
                ("recursos asignados (GV.RR-03)", recursos),
                ("ciberseguridad en las practicas de RH (GV.RR-04)", practicas_rh),
            )
            if not presente
        )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            f"Roles con responsables y autoridad descritos. Falta declarar: {faltan}.",
            [mejor.id],
        )
    if roles_validos:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Responsables definidos sin autoridad explicita.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        25,
        "Roles genericos mencionados sin asignacion concreta de responsables.",
        [mejor.id],
    )
