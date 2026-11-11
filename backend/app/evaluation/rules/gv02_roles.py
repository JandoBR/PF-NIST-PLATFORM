"""CRI-GV-02 — Roles y responsabilidades definidos (docs/03 §1).

Documental puro (`doc.claim(tipo=role_assigned)`): sin evidencia tecnica que lo contradiga, la
decision depende de lo que la extraccion pudo citar (mismo patron que CRI-GV-01).

Cubre las cuatro subcategorias de `GV.RR`: el 100 exige un rol con **responsable nombrado,
responsabilidades y autoridad** (`GV.RR-01`/`GV.RR-02`) y, ademas, las otras dos facetas de la
categoria -- recursos acordes a la estrategia (`GV.RR-03`) y la ciberseguridad en las practicas de
recursos humanos (`GV.RR-04`). Nombrar a un CISO no es dotar a la funcion.

El rol se elige por completitud, no por confianza; las dos facetas booleanas, en cambio, se agregan
de cualquier fragmento del documento que las declare, salvo que el mismo documento las contradiga
(`_common.merged_bool`, docs/09 §101).
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    best_found,
    doc_claims,
    found,
    merged_bool,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-02"
CRITERION_VERSION = 2


def _texto(valor: object) -> bool:
    """Campo textual con contenido real (no `None`, no cadena vacia)."""

    return isinstance(valor, str) and bool(valor.strip())


def _roles_validos(contenido: dict) -> list[dict]:
    roles = contenido.get("roles") or []
    if not isinstance(roles, list):
        return []
    return [r for r in roles if isinstance(r, dict) and _texto(r.get("rol"))]


def _completitud(role: dict) -> int:
    """3 = responsable + responsabilidades + autoridad; 2 = autoridad y uno de los dos;
    1 = autoridad sola; 0 = sin autoridad."""

    responsable = _texto(role.get("responsable"))
    responsabilidades = _texto(role.get("responsabilidades"))
    autoridad = _texto(role.get("autoridad"))
    if responsable and responsabilidades and autoridad:
        return 3
    if autoridad and (responsable or responsabilidades):
        return 2
    return 1 if autoridad else 0


def _mejor_claim(encontradas: list[EvidenceInstance]) -> tuple[int, EvidenceInstance]:
    def nivel(claim: EvidenceInstance) -> int:
        contenido = claim.value.get("contenido", {})
        return max((_completitud(r) for r in _roles_validos(contenido)), default=0)

    maximo = max(nivel(c) for c in encontradas)
    mejor = best_found([c for c in encontradas if nivel(c) == maximo])
    assert mejor is not None
    return maximo, mejor


def _faltantes(contenido: dict, roles: list[dict], nivel: int) -> list[str]:
    faltan: list[str] = []
    if nivel < 3:
        if not any(_texto(r.get("responsable")) for r in roles):
            faltan.append("responsable nombrado (GV.RR-01/02)")
        if not any(_texto(r.get("responsabilidades")) for r in roles):
            faltan.append("responsabilidades (GV.RR-01/02)")
        if not any(_texto(r.get("autoridad")) for r in roles):
            faltan.append("autoridad (GV.RR-01/02)")
    if not contenido.get("recursos_asignados"):
        faltan.append("recursos asignados (GV.RR-03)")
    if not contenido.get("practicas_rh"):
        faltan.append("ciberseguridad en las practicas de RH (GV.RR-04)")
    return faltan


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

    encontradas = found(claims)
    if not encontradas:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran roles ni responsabilidades.",
            [c.id for c in claims],
        )

    nivel, mejor = _mejor_claim(encontradas)
    contenido = dict(mejor.value.get("contenido", {}))
    roles = _roles_validos(contenido)
    aportantes = {mejor.id: mejor}
    for campo in ("recursos_asignados", "practicas_rh"):
        contenido[campo], declarantes = merged_bool(encontradas, campo)
        for claim in declarantes:
            aportantes.setdefault(claim.id, claim)
    ids = [c.id for c in aportantes.values()]

    if nivel == 3 and contenido.get("recursos_asignados") and contenido.get("practicas_rh"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Rol con responsable nombrado, responsabilidades y autoridad, recursos acordes a la"
            " estrategia de riesgo y ciberseguridad en las practicas de recursos humanos.",
            ids,
        )

    if nivel > 0:
        faltan = _faltantes(contenido, roles, nivel)
        detalle = ", ".join(faltan) if faltan else "ninguna"
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            f"Hay autoridad declarada, pero falta: {detalle}.",
            ids,
        )

    if roles:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Roles definidos sin autoridad explicita.",
            ids,
        )

    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        25,
        "Roles genericos mencionados sin un responsable nombrado.",
        ids,
    )
