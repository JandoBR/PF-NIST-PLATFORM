"""CRI-PR-06 — Generacion de logs para monitoreo (docs/03 §3).

Combina CloudTrail (`tf.logging.config`) con logs de sistema via Ansible (`an.service.state`
sobre rsyslog/journald/syslog-ng): el 100 de la regla documentada exige ambas senales, no solo
CloudTrail multirregion. Deteccion via el modulo `service` (en lugar de inspeccionar una tarea
`an.task.config` que edite `rsyslog.conf`): un servicio corriendo es una senal mas directa que
una tarea de configuracion, y es lo que el adaptador de Ansible puede afirmar con confianza.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type, noting_unresolved
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-06"
CRITERION_VERSION = 1
SYSLOG_SERVICES = {"rsyslog", "syslog-ng", "systemd-journald", "journald"}


def _system_logs_declared(evidence: list[EvidenceInstance]) -> bool:
    services = by_type(evidence, "an.service.state")
    return any(
        e.value["servicio"] in SYSLOG_SERVICES and e.value["estado"] == "habilitado"
        for e in services
    )


@noting_unresolved({"enable_logging"})
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    declarados = by_type(evidence, "tf.logging.config")
    # `habilitado == "unknown"` (expresion sin resolver) no se puntua: ni suma ni penaliza.
    relevant = [e for e in declarados if e.value["habilitado"] != "unknown"]
    system_logs = _system_logs_declared(evidence)

    if not relevant:
        if system_logs:
            return CriterionResult(
                criterion_id=CRITERION_ID,
                criterion_version=CRITERION_VERSION,
                estado=Estado.EVALUADO,
                base_score=75,
                final_score=75,
                explanation="Sin CloudTrail, pero logs de sistema declarados via Ansible.",
            )
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation=(
                "Sin recursos de logging (CloudTrail ni logs de sistema) evaluables."
                if not declarados
                else "El estado de logging de CloudTrail es desconocido (expresion sin resolver)."
            ),
            evidence_ids=[e.id for e in declarados],
        )

    habilitados = [e for e in relevant if e.value["habilitado"] is True]
    if not habilitados:
        if system_logs:
            return CriterionResult(
                criterion_id=CRITERION_ID,
                criterion_version=CRITERION_VERSION,
                estado=Estado.EVALUADO,
                base_score=50,
                final_score=50,
                explanation=(
                    "CloudTrail sin logging habilitado; alguna fuente de log (sistema) declarada."
                ),
                evidence_ids=[e.id for e in relevant],
            )
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
    if multiregion and system_logs:
        score, detalle = 100, "CloudTrail multirregion + logs de sistema declarados"
    elif multiregion:
        score, detalle = 75, "CloudTrail habilitado multirregion"
    elif system_logs:
        score = 75
        detalle = "CloudTrail habilitado (sin multirregion) con logs de sistema declarados"
    else:
        score, detalle = 75, "CloudTrail habilitado sin confirmacion de multirregion"

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=score,
        final_score=score,
        explanation=f"{detalle}: " + ", ".join(e.subject_ref for e in habilitados) + ".",
        evidence_ids=[e.id for e in habilitados],
    )
