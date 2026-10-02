"""CRI-GV-03 — Objetivos de riesgo y tolerancia establecidos (docs/03 §1).

Documental (`doc.claim(tipo=risk_tolerance)`).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-03"
CRITERION_VERSION = 1


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
        return result(
            CRITERION_ID,
            Estado.NO_IMPLEMENTADO,
            0,
            "Los documentos analizados no declaran objetivos de riesgo ni tolerancia.",
            [c.id for c in claims],
        )

    contenido = mejor.value.get("contenido", {})
    if contenido.get("objetivos_riesgo") and contenido.get("tolerancia"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Objetivos de riesgos y tolerancia/apetito documentados, con responsable.",
            [mejor.id],
        )
    if contenido.get("objetivos_riesgo"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Objetivos de riesgo definidos sin tolerancia explicita.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Declaracion generica de 'gestionar riesgos' sin objetivos ni tolerancia concretos.",
        [mejor.id],
    )
