"""CRI-GV-06 — Programa de riesgo de la cadena de suministro (docs/03 §1).

Documental (`doc.claim(tipo=supplier_program)`). Cubre la via documental de GV.SC: el programa y sus
politicas (`GV.SC-01`), los roles acordados con terceros (`GV.SC-02`), el conocimiento y la
priorizacion de proveedores (`GV.SC-04`) y los requisitos en contratos (`GV.SC-05`).

Las otras seis subcategorias de GV.SC (debida diligencia previa, monitoreo durante el ciclo de vida,
cierre de la relacion...) **no** se declaran: nada en el prototipo las evidencia. La senal tecnica
de procedencia de modulos de Terraform sigue siendo AMP-07 en docs/12 §5.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-06"
CRITERION_VERSION = 1

#: Campo del contenido -> resultado del CSF que sostiene (ademas del programa, GV.SC-01).
_CAMPOS: dict[str, str] = {
    "roles": "roles con proveedores y terceros (GV.SC-02)",
    "proveedores_priorizados": "proveedores conocidos y priorizados (GV.SC-04)",
    "requisitos_contractuales": "requisitos en contratos (GV.SC-05)",
}


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

    mejor = best_found(claims)
    if mejor is None:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un programa de riesgo de la cadena de"
            " suministro.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido") or {}
    if not contenido.get("programa"):
        return silencio_documental(
            CRITERION_ID,
            "La afirmacion menciona proveedores pero no declara un programa ni politicas de"
            " cadena de suministro.",
            [mejor.id],
        )

    declarados = [c for c in _CAMPOS if contenido.get(c)]
    faltantes = [_CAMPOS[c] for c in _CAMPOS if c not in declarados]
    detalle = f" Falta declarar: {', '.join(faltantes)}." if faltantes else ""

    if len(declarados) == 3:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Programa de cadena de suministro con roles, priorizacion de proveedores y requisitos"
            " contractuales.",
            [mejor.id],
        )
    if len(declarados) == 2:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Programa de cadena de suministro con dos de los tres elementos acordados." + detalle,
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Programa de cadena de suministro declarado sin roles, priorizacion ni requisitos"
        " contractuales acordados." + detalle,
        [mejor.id],
    )
