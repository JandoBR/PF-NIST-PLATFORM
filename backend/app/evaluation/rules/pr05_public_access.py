"""CRI-PR-05 — Almacenamiento protegido contra acceso publico (docs/03 §3).

Distingue "no hay buckets" (no_aplicable) de "hay buckets sin `public_access_block` declarado"
(evidencia_insuficiente) cruzando contra `tf.resource.present`.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-05"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    presentes = by_type(evidence, "tf.resource.present")
    buckets = [e for e in presentes if e.subject_type == "aws_s3_bucket"]
    relevant = by_type(evidence, "tf.public_access.config")

    if not buckets:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.NO_APLICABLE,
            explanation="Sin buckets de almacenamiento en el alcance.",
        )

    if not relevant:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Existen buckets sin `aws_s3_bucket_public_access_block` declarado.",
        )

    resolved = [e for e in relevant if e.value["bloqueo_publico"] != "unknown"]
    unknown = [e for e in relevant if e.value["bloqueo_publico"] == "unknown"]

    if not resolved:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Bloqueo de acceso publico desconocido para todos los buckets.",
            evidence_ids=[e.id for e in unknown],
        )

    expuestos = [e for e in resolved if e.value["nivel"] == "ninguno"]
    parciales = [e for e in resolved if e.value["nivel"] == "parcial"]

    if expuestos:
        score, nivel_txt = 0, "sin bloqueo (block_public_acls = false explicito)"
        afectados = expuestos
    elif parciales:
        score, nivel_txt = 50, "bloqueo parcial (alguno de los 4 modos)"
        afectados = parciales
    else:
        score, nivel_txt = 100, "bloqueo completo en los 4 modos"
        afectados = resolved

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=score,
        final_score=score,
        explanation=f"{nivel_txt}: " + ", ".join(e.subject_ref for e in afectados) + ".",
        evidence_ids=[e.id for e in resolved],
    )
