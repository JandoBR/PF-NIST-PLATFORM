"""CRI-PR-07 — Concienciacion y formacion en seguridad (docs/03 §3).

Documental (`doc.claim(tipo=training_program)`). PR.AT distingue dos cosas: la formacion general
de todo el personal (`PR.AT-01`) y la de los roles especializados (`PR.AT-02`), asi que la regla
puntua por separado la frecuencia declarada y la existencia de formacion por rol.

El contenido declara solo los tres campos que esta regla lee (`programa`, `frecuencia`,
`roles_especializados`): un campo que ninguna regla consume es justo el problema que CR-06 y CR-07
tuvieron que limpiar (docs/09 §36, §57).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-07"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "training_program")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre formacion y"
            " concienciacion.",
        )

    mejor = best_found(claims)
    if mejor is None:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un programa de concienciacion ni de formacion.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido") or {}
    if not contenido.get("programa"):
        return silencio_documental(
            CRITERION_ID,
            "La afirmacion no declara un programa de formacion (solo lo menciona).",
            [mejor.id],
        )

    frecuencia = bool(contenido.get("frecuencia"))
    por_rol = bool(contenido.get("roles_especializados"))

    if frecuencia and por_rol:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Programa de concienciacion con periodicidad declarada y formacion especifica para"
            " roles especializados.",
            [mejor.id],
        )
    if frecuencia:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Programa de concienciacion con periodicidad declarada, sin formacion diferenciada"
            " para roles especializados (PR.AT-02).",
            [mejor.id],
        )
    if por_rol:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Formacion para roles especializados declarada, sin periodicidad del programa general.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Programa de formacion declarado sin periodicidad ni alcance por rol.",
        [mejor.id],
    )
