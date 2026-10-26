"""CRI-PR-05 — Almacenamiento protegido contra acceso publico (docs/03 §3).

Distingue "no hay buckets" (no_aplicable) de "hay buckets sin `public_access_block` declarado"
(evidencia_insuficiente) cruzando contra `tf.resource.present`.

Tambien mira `tf.db_exposure.config` (`publicly_accessible` de RDS): una base de datos declarada
publica es una exposicion explicita de datos almacenados y puntua 0, igual que un bucket sin
bloqueo; si todas las bases son privadas no resta ni suma. Una politica documental que diga lo
contrario no cambia el puntaje (D7): se reporta como contradiccion (`recommendations`).
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type, noting_unresolved, result
from app.evaluation.schemas import SCORING_STATES, CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-05"
CRITERION_VERSION = 1


def _versioning_note(evidence: list[EvidenceInstance]) -> str:
    """`tf.versioning.config` no cambia el puntaje (docs/03 §3): solo se informa."""

    versionings = by_type(evidence, "tf.versioning.config")
    sin_versionado = [e.subject_ref for e in versionings if e.value["habilitado"] is not True]
    if not sin_versionado:
        return ""
    return (
        " Sin versionado habilitado o desconocido (informativo): " + ", ".join(sin_versionado) + "."
    )


def _with_database_exposure(
    evidence: list[EvidenceInstance], resultado: CriterionResult
) -> CriterionResult:
    dbs = by_type(evidence, "tf.db_exposure.config")
    publicas = [e for e in dbs if e.value["publico"] is True]
    privadas = [e for e in dbs if e.value["publico"] is False]

    if publicas:
        texto = (
            "Base(s) de datos publicamente accesible(s) (publicly_accessible = true): "
            + ", ".join(e.subject_ref for e in publicas)
            + "."
        )
        if resultado.estado in SCORING_STATES:
            texto += f" {resultado.explanation}"
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            texto,
            [*(e.id for e in publicas), *resultado.evidence_ids],
        )
    if not privadas:
        return resultado
    nombres = ", ".join(e.subject_ref for e in privadas)
    if resultado.estado == Estado.NO_APLICABLE:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            f"Ninguna base de datos es publicamente accesible: {nombres}.",
            [e.id for e in privadas],
        )
    if resultado.estado == Estado.EVALUADO:
        return resultado.model_copy(
            update={
                "explanation": f"{resultado.explanation} Bases de datos no publicas: {nombres}.",
                "evidence_ids": [*resultado.evidence_ids, *(e.id for e in privadas)],
            }
        )
    return resultado


@noting_unresolved(
    {
        "publicly_accessible",
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
        "bucket",
    }
)
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    resultado = _with_database_exposure(evidence, _evaluate_public_access(evidence))
    nota = _versioning_note(evidence)
    if not nota or resultado.estado == Estado.NO_APLICABLE:
        return resultado
    return resultado.model_copy(update={"explanation": resultado.explanation + nota})


def _evaluate_public_access(evidence: list[EvidenceInstance]) -> CriterionResult:
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
        # Solo un bloqueo resuelto permite afirmar el 100. Un bucket sin bloque declarado o con
        # flags sin resolver (`unknown`) no cuenta como bloqueado (docs/03 §3).
        con_bloque = {e.subject_ref for e in resolved}
        sin_bloque = sorted(b.subject_ref for b in buckets if b.subject_ref not in con_bloque)
        if sin_bloque:
            return CriterionResult(
                criterion_id=CRITERION_ID,
                criterion_version=CRITERION_VERSION,
                estado=Estado.EVIDENCIA_INSUFICIENTE,
                explanation="Buckets sin bloqueo resuelto (`public_access_block` ausente o con"
                " flags sin resolver): " + ", ".join(sin_bloque) + ".",
                evidence_ids=[e.id for e in resolved],
            )
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
