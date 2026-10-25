"""CRI-GV-03 — Estrategia de gestion del riesgo (docs/03 §1).

Documental (`doc.claim(tipo=risk_tolerance)`). Cubre las siete subcategorias de `GV.RM`: los
objetivos y la tolerancia (`GV.RM-01`/`GV.RM-02`) son la puerta, y `_CAMPOS` lleva una faceta por
cada una de las otras cinco.

Mismo criterio de amplitud que `CRI-GV-06`: una estrategia que fija objetivos y tolerancia pero no
dice como se calculan los riesgos, por donde se comunican ni que opciones de respuesta hay, no
evidencia una categoria de siete resultados. Tres de las cinco facetas para el 100.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-03"
CRITERION_VERSION = 2

#: Campo del contenido -> resultado del CSF que sostiene (ademas de objetivos y tolerancia).
_CAMPOS: dict[str, str] = {
    "integracion_empresarial": "riesgo de ciberseguridad dentro del riesgo empresarial (GV.RM-03)",
    "opciones_respuesta": "opciones de respuesta al riesgo (GV.RM-04)",
    "lineas_comunicacion": "lineas de comunicacion del riesgo (GV.RM-05)",
    "metodo_estandarizado": "metodo estandarizado para calcular y priorizar riesgos (GV.RM-06)",
    "oportunidades_estrategicas": (
        "oportunidades estrategicas en la discusion del riesgo (GV.RM-07)"
    ),
}

#: Facetas minimas para el 100, una vez declarados objetivos y tolerancia.
_FACETAS_PARA_100 = 3


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "risk_tolerance")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre objetivos de riesgo"
            " y tolerancia.",
        )

    mejor = best_found(claims)
    if mejor is None:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran objetivos de riesgo ni tolerancia.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido", {})
    declaradas = [c for c in _CAMPOS if contenido.get(c)]
    faltantes = [_CAMPOS[c] for c in _CAMPOS if c not in declaradas]

    if contenido.get("objetivos_riesgo") and contenido.get("tolerancia"):
        if len(declaradas) >= _FACETAS_PARA_100:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                100,
                "Estrategia de riesgo con objetivos, tolerancia y"
                f" {len(declaradas)} de {len(_CAMPOS)} elementos de gestion declarados.",
                [mejor.id],
            )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Objetivos de riesgo y tolerancia documentados, pero la estrategia no se desarrolla."
            f" Falta declarar: {', '.join(faltantes)}.",
            [mejor.id],
        )
    if contenido.get("objetivos_riesgo"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Objetivos de riesgo definidos sin tolerancia explicita.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        25,
        "Declaracion generica de gestionar riesgos, sin objetivos ni tolerancia concretos.",
        [mejor.id],
    )
