"""CRI-PR-01 — Cifrado de datos en reposo (docs/03 §3, docs/01 §9).

La observacion tecnica prevalece (D7): cualquier recurso `disabled` hace caer el puntaje aunque
otros esten `enabled`. Los recursos `unknown` no bloquean el calculo de los resueltos, pero quedan
registrados como limitacion.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, by_type, doc_claims, noting_unresolved
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-01"
CRITERION_VERSION = 1


@noting_unresolved({"storage_encrypted", "sse_algorithm", "bucket"})
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    """Puntaje tecnico; la politica documental (`doc.claim(policy_exists)`) nunca lo eleva
    (docs/03 §3): solo se cita como contexto cuando hay cifrado deshabilitado."""

    resultado = _evaluate_technical(evidence)
    politica = best_found(doc_claims(evidence, "policy_exists"))
    if politica is None or resultado.final_score != 25:
        return resultado
    return resultado.model_copy(
        update={
            "explanation": (
                f"{resultado.explanation} Existe una politica documentada"
                " (doc.claim policy_exists) que no se refleja en la configuracion: es una brecha"
                " entre lo declarado y lo observado."
            ),
            "evidence_ids": [*resultado.evidence_ids, politica.id],
        }
    )


def _evaluate_technical(evidence: list[EvidenceInstance]) -> CriterionResult:
    relevant = by_type(evidence, "tf.encryption.config")
    if not relevant:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.NO_APLICABLE,
            explanation="Sin recursos de almacenamiento o base de datos en el alcance.",
        )

    disabled = [e for e in relevant if e.value["estado"] == "disabled"]
    enabled = [e for e in relevant if e.value["estado"] == "enabled"]
    unknown = [e for e in relevant if e.value["estado"] == "unknown"]

    if disabled:
        explanation = (
            "Cifrado deshabilitado en: " + ", ".join(e.subject_ref for e in disabled) + "."
            " La observacion tecnica prevalece sobre cualquier politica documental (D7)."
        )
        if unknown:
            explanation += f" {len(unknown)} recurso(s) con estado desconocido no se consideraron."
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=25,
            final_score=25,
            explanation=explanation,
            evidence_ids=[e.id for e in disabled + enabled],
        )

    if enabled:
        explanation = "Cifrado habilitado en todos los recursos resueltos: " + ", ".join(
            e.subject_ref for e in enabled
        )
        if unknown:
            explanation += (
                f". {len(unknown)} recurso(s) con estado desconocido quedan como limitacion"
                " y no se puntuan."
            )
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=100,
            final_score=100,
            explanation=explanation,
            evidence_ids=[e.id for e in enabled],
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVIDENCIA_INSUFICIENTE,
        explanation="Todos los recursos tienen estado de cifrado desconocido (unknown).",
        evidence_ids=[e.id for e in unknown],
    )
