"""CRI-GV-04 — Revision del desempeno y mejora de la estrategia (docs/03 §1).

Documental: un proceso de revision (`process_defined` con `proceso` de revision/mejora/desempeno)
da 100 con metricas o ajustes y 75 sin ellos. Solo la revision periodica de la politica
(`policy_review`) da 50: revisar un documento no es revisar la estrategia, y ese mismo claim ya
cuenta para GV-01 (docs/09 §60).
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    best_found,
    doc_claims,
    found,
    merged_content,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-04"
CRITERION_VERSION = 1


def _es_de_revision(claim: EvidenceInstance) -> bool:
    contenido = claim.value.get("contenido", {})
    proceso = str(contenido.get("proceso", "")).lower()
    return any(
        palabra in proceso
        for palabra in ("revision", "revisión", "mejora", "desempeno", "desempeño", "performance")
    )


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    review = doc_claims(evidence, "policy_review")
    process = doc_claims(evidence, "process_defined")
    if not review and not process:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre revision del"
            " desempeno.",
        )

    candidatos = [c for c in process if _es_de_revision(c)]
    encontradas = found(candidatos)
    contenido, aportantes = merged_content(encontradas)
    mejor_review = best_found(review)

    if not encontradas and mejor_review is None:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un proceso de revision con metricas o ajustes.",
            [c.id for c in (*review, *process)],
        )

    if encontradas and (contenido.get("metricas") or contenido.get("ajustes")):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Proceso de revision con metricas/resultados y evidencia de ajustes.",
            [c.id for c in aportantes],
        )
    if encontradas:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Proceso de revision periodica definido, sin metricas ni evidencia de ajustes.",
            [c.id for c in aportantes or encontradas],
        )
    # Solo la frecuencia de revision de la politica (`policy_review`): eso es revisar un documento,
    # no la estrategia ni el desempeno (GV.OV). Cuenta como revision mencionada, no definida, y el
    # mismo claim ya da a GV-01 su tramo de revision: no debe cubrir dos requisitos de Tier 3.
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Solo se declara la revision periodica de la politica, no un proceso de revision del"
        " desempeno o la estrategia.",
        [mejor_review.id],
    )
