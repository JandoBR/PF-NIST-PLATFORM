"""CRI-PR-06 — Generacion de logs para monitoreo (docs/03 §3).

MVP: solo evalua CloudTrail (`tf.logging.config`). Los logs de sistema via Ansible
(`an.task.config`) se incorporaran cuando exista ese adaptador; hasta entonces el tope sin ellos
sigue siendo 100 porque CloudTrail multirregion ya satisface la rama mas alta de la regla.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-06"
CRITERION_VERSION = 1


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    relevant = by_type(evidence, "tf.logging.config")
    if not relevant:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Sin recursos de logging (CloudTrail) evaluables en el alcance.",
        )

    habilitados = [e for e in relevant if e.value["habilitado"] is True]
    if not habilitados:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=0,
            final_score=0,
            explanation="CloudTrail declarado pero sin logging habilitado.",
            evidence_ids=[e.id for e in relevant],
        )

    multiregion = [e for e in habilitados if e.value["multi_region"] is True]
    if multiregion:
        score = 100
        detalle = "CloudTrail habilitado multirregion"
    else:
        score = 75
        detalle = "CloudTrail habilitado sin confirmacion de multirregion"

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=score,
        final_score=score,
        explanation=f"{detalle}: " + ", ".join(e.subject_ref for e in habilitados) + ".",
        evidence_ids=[e.id for e in habilitados],
    )
