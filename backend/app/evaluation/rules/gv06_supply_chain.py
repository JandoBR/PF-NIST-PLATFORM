"""CRI-GV-06 — Programa de riesgo de la cadena de suministro (docs/03 §1).

Documental (`doc.claim(tipo=supplier_program)`). Cubre las diez subcategorias de `GV.SC`: el
programa y sus politicas (`GV.SC-01`) mas una faceta por subcategoria en `_CAMPOS`.

**Anclas de amplitud, no de presencia.** La categoria es una lista de practicas, asi que el puntaje
mide cuantas de las nueve facetas declara el documento. Si el 100 dependiera solo de que exista un
programa, las nueve subcategorias se sostendrian en una sola frase. El `programa` sigue siendo la
puerta: sin el, silencio documental.
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

CRITERION_ID = "CRI-GV-06"
CRITERION_VERSION = 2

#: Campo del contenido -> resultado del CSF que sostiene (ademas del programa, GV.SC-01).
_CAMPOS: dict[str, str] = {
    "roles": "roles con proveedores y terceros (GV.SC-02)",
    "integracion_riesgo": "riesgo de proveedores integrado al riesgo empresarial (GV.SC-03)",
    "proveedores_priorizados": "proveedores conocidos y priorizados (GV.SC-04)",
    "requisitos_contractuales": "requisitos en contratos (GV.SC-05)",
    "debida_diligencia": "debida diligencia antes de formalizar la relacion (GV.SC-06)",
    "riesgos_monitoreados": "riesgos del proveedor registrados y respondidos (GV.SC-07)",
    "en_respuesta_incidentes": "proveedores en la respuesta a incidentes (GV.SC-08)",
    "monitoreo_ciclo_vida": "practicas monitoreadas durante la relacion (GV.SC-09)",
    "terminacion": "disposiciones para el cierre de la relacion (GV.SC-10)",
}

#: Minimo de facetas declaradas por tramo. El programa solo (`0`) vale 25: existe la politica y
#: nada mas.
_TRAMOS: tuple[tuple[int, int], ...] = ((7, 100), (4, 75), (1, 50), (0, 25))


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "supplier_program")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre la gestion de"
            " proveedores y terceros.",
        )

    encontradas = found(claims)
    if not encontradas:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un programa de riesgo de la cadena de"
            " suministro.",
            [c.id for c in claims],
        )

    contenido, aportantes = merged_content(encontradas)
    if not contenido.get("programa"):
        return silencio_documental(
            CRITERION_ID,
            "La afirmacion menciona proveedores pero no declara un programa ni politicas de"
            " cadena de suministro.",
            [c.id for c in aportantes or encontradas],
        )

    declarados = [c for c in _CAMPOS if contenido.get(c)]
    faltantes = [_CAMPOS[c] for c in _CAMPOS if c not in declarados]
    detalle = f" Falta declarar: {', '.join(faltantes)}." if faltantes else ""
    score = next(puntaje for minimo, puntaje in _TRAMOS if len(declarados) >= minimo)

    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        score,
        f"Programa de cadena de suministro con {len(declarados)} de {len(_CAMPOS)} practicas"
        f" declaradas.{detalle}",
        [c.id for c in aportantes],
    )
