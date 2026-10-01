"""CRI-PR-02 — Backups configurados y protegidos (docs/03 §3).

Sin `doc.claim(backup_policy)` el puntaje maximo alcanzable es 75 (retencion >= 7 dias): el 100
exige que la retencion cumpla una politica documentada, que este adaptador todavia no produce.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-02"
CRITERION_VERSION = 1
RETENCION_MINIMA_DIAS = 7


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    relevant = by_type(evidence, "tf.backup.config")
    if not relevant:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.NO_APLICABLE,
            explanation="Sin bases de datos administradas en el alcance.",
        )

    resolved = [e for e in relevant if e.value["retencion_dias"] is not None]
    unknown = [e for e in relevant if e.value["retencion_dias"] is None]

    if not resolved:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Retencion de backups desconocida para todos los recursos.",
            evidence_ids=[e.id for e in unknown],
        )

    disabled = [e for e in resolved if e.value["retencion_dias"] == 0]
    if disabled:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=25,
            final_score=25,
            explanation="Backups deshabilitados explicitamente en: "
            + ", ".join(e.subject_ref for e in disabled) + ".",
            evidence_ids=[e.id for e in resolved],
        )

    peor_retencion = min(e.value["retencion_dias"] for e in resolved)
    if peor_retencion >= RETENCION_MINIMA_DIAS:
        score = 75
        detalle = f"retencion minima observada {peor_retencion} dias (>= {RETENCION_MINIMA_DIAS})"
    else:
        score = 50
        detalle = f"retencion minima observada {peor_retencion} dias (< {RETENCION_MINIMA_DIAS})"

    explanation = f"Backups habilitados; {detalle}. Sin politica documentada: puntaje maximo 75."
    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=score,
        final_score=score,
        explanation=explanation,
        evidence_ids=[e.id for e in resolved],
    )
