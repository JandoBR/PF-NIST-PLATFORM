"""CRI-RC-01 — Procedimiento de recuperacion definido y ejecutable (docs/03 §6).

Documental (`doc.claim`): el procedimiento usa `process_defined` con `contenido.proceso` de
recuperacion; `backup_policy` se usa como senal minima si no hay procedimiento completo.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-RC-01"
CRITERION_VERSION = 1


def _es_de_recuperacion(claim: EvidenceInstance) -> bool:
    contenido = claim.value.get("contenido", {})
    proceso = str(contenido.get("proceso", "")).lower()
    return any(
        palabra in proceso
        for palabra in ("recuperacion", "recuperación", "recovery", "restauracion", "restauración")
    )


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    process = doc_claims(evidence, "process_defined")
    backups = doc_claims(evidence, "backup_policy")

    if not process and not backups:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre recuperacion.",
        )

    candidatos = [c for c in process if _es_de_recuperacion(c)]
    mejor = best_found(candidatos)

    if mejor is None:
        backup_ok = best_found(backups)
        if backup_ok is not None:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                50,
                "Se declara una politica de backups, pero no un procedimiento de recuperacion.",
                [backup_ok.id],
            )
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un procedimiento de recuperacion.",
            [c.id for c in process or backups],
        )

    contenido = mejor.value.get("contenido", {})
    if (
        contenido.get("pasos")
        and contenido.get("criterios_activacion")
        and contenido.get("responsables")
    ):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Procedimiento de recuperacion con pasos, responsables y criterios de activacion.",
            [mejor.id],
        )
    if contenido.get("pasos"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Procedimiento de recuperacion definido, sin criterios de activacion.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Recuperacion mencionada de forma generica.",
        [mejor.id],
    )
