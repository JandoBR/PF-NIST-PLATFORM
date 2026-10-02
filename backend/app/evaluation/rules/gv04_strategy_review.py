"""CRI-GV-04 — Revision del desempeno y mejora de la estrategia (docs/03 §1).

Documental: revision periodica (`doc.claim(tipo=policy_review)`) y/o un proceso definido de
revision/mejora (`process_defined` con `contenido.proceso` de revision). El 100 exige evidencia de
metricas/ajustes.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result
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
    mejor_proc = best_found(candidatos)
    mejor_review = best_found(review)

    if mejor_proc is None and mejor_review is None:
        return result(
            CRITERION_ID,
            Estado.NO_IMPLEMENTADO,
            0,
            "Los documentos analizados no declaran un proceso de revision con metricas o ajustes.",
            [c.id for c in (*review, *process)],
        )

    contenido = mejor_proc.value.get("contenido", {}) if mejor_proc else {}
    if mejor_proc and (contenido.get("metricas") or contenido.get("ajustes")):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Proceso de revision con metricas/resultados y evidencia de ajustes.",
            [mejor_proc.id],
        )
    mejor = mejor_proc or mejor_review
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        75,
        "Revision periodica definida sin evidencia de ajustes realizados.",
        [mejor.id] if mejor else [],
    )
