"""CRI-DE-01 — Monitoreo de red y computo (docs/03 §4).

Mixto y determinista: combina CloudTrail (`tf.logging.config`) con logs de sistema via Ansible
(`an.service.state` sobre rsyslog/journald/syslog-ng), reutilizando la deteccion de CRI-PR-06.
Sin ninguna configuracion de monitoreo es `evidencia_insuficiente`, nunca 0 (no se penaliza lo que
no se puede observar).
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-DE-01"
CRITERION_VERSION = 1
SYSLOG_SERVICES = {"rsyslog", "syslog-ng", "systemd-journald", "journald"}


def _system_logs(evidence: list[EvidenceInstance]) -> bool:
    return any(
        e.value["servicio"] in SYSLOG_SERVICES and e.value["estado"] == "habilitado"
        for e in by_type(evidence, "an.service.state")
    )


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    logging_cfg = by_type(evidence, "tf.logging.config")
    syslog = _system_logs(evidence)

    if not logging_cfg and not syslog:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin configuracion de monitoreo (CloudTrail ni logs de sistema) evaluable.",
        )

    habilitados = [e for e in logging_cfg if e.value.get("habilitado") is True]
    centralizado = any(
        e.value.get("multi_region") is True or e.value.get("destino") for e in habilitados
    )

    if habilitados and centralizado and syslog:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Fuentes de log habilitadas y centralizadas (CloudTrail + logs de sistema).",
            [e.id for e in habilitados],
        )
    if habilitados or syslog:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Fuentes de monitoreo habilitadas, sin centralizacion completa declarada.",
            [e.id for e in habilitados] or [e.id for e in by_type(evidence, "an.service.state")],
        )
    return result(
        CRITERION_ID,
        Estado.NO_IMPLEMENTADO,
        0,
        "CloudTrail/logs declarados pero sin ninguna fuente de monitoreo habilitada.",
        [e.id for e in logging_cfg],
    )
