"""CRI-RS-02 — Analisis de incidentes y preservacion de evidencia (docs/03 §5).

Mixto: proceso documentado (`process_defined` con `contenido.proceso` de analisis/incidente) mas,
si la hay, evidencia operativa de declaracion (`log.pattern(incident_declared)`).
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    best_found,
    by_type,
    doc_claims,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RS-02"
CRITERION_VERSION = 1


def _es_de_analisis(claim: EvidenceInstance) -> bool:
    contenido = claim.value.get("contenido", {})
    proceso = str(contenido.get("proceso", "")).lower()
    return any(
        palabra in proceso
        for palabra in ("analisis", "análisis", "causa", "incidente", "evidencia", "forense")
    )


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    process = doc_claims(evidence, "process_defined")
    if not process:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre analisis de"
            " incidentes.",
        )

    candidatos = [c for c in process if _es_de_analisis(c)]
    mejor = best_found(candidatos)
    if mejor is None:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un proceso de analisis de incidentes.",
            [c.id for c in process],
        )

    declarado = any(
        e.value.get("patron") == "incident_declared" for e in by_type(evidence, "log.pattern")
    )
    if declarado:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Proceso de analisis de causa raiz y conservacion de evidencia, evidenciado en el"
            " escenario.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        75,
        "Proceso de analisis de incidentes documentado, sin evidencia operativa.",
        [mejor.id],
    )
