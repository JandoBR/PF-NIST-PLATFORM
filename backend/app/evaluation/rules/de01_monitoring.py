"""CRI-DE-01 — Monitoreo de red y computo (docs/03 §4).

Mixto y determinista: combina CloudTrail (`tf.logging.config`) con logs de sistema via Ansible
(`an.service.state` sobre rsyslog/journald/syslog-ng), reutilizando la deteccion de CRI-PR-06.
Sin ninguna configuracion de monitoreo es `evidencia_insuficiente`, nunca 0 (no se penaliza lo que
no se puede observar).
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type, noting_unresolved, result
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


@noting_unresolved({"enable_logging"})
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    """Evalua la configuracion y, si hay una ventana de observacion (`log.window`), la cita como
    corroboracion de actividad observable (docs/03): no cambia el puntaje de la configuracion."""

    resultado = _evaluate_config(evidence)
    ventanas = by_type(evidence, "log.window")
    if not ventanas or resultado.estado not in (Estado.EVALUADO, Estado.NO_IMPLEMENTADO):
        return resultado
    ventana = max(ventanas, key=lambda e: e.value["hasta"])
    return resultado.model_copy(
        update={
            "explanation": (
                f"{resultado.explanation} Actividad observable en la ventana"
                f" {ventana.value['desde']} .. {ventana.value['hasta']}."
            ),
            "evidence_ids": [*resultado.evidence_ids, ventana.id],
        }
    )


def _evaluate_config(evidence: list[EvidenceInstance]) -> CriterionResult:
    declarados = by_type(evidence, "tf.logging.config")
    # `habilitado == "unknown"` (expresion sin resolver) no se puntua: ni suma ni penaliza.
    logging_cfg = [e for e in declarados if e.value.get("habilitado") != "unknown"]
    syslog = _system_logs(evidence)

    if not logging_cfg and not syslog:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin configuracion de monitoreo (CloudTrail ni logs de sistema) evaluable."
            if not declarados
            else "El estado de CloudTrail es desconocido (expresion sin resolver) y no hay logs"
            " de sistema declarados.",
            [e.id for e in declarados],
        )

    habilitados = [e for e in logging_cfg if e.value.get("habilitado") is True]
    # `destino` (el bucket del trail) es obligatorio en `aws_cloudtrail`: siempre viene, asi que
    # no distingue nada. La centralizacion que si se puede leer es el trail multirregion.
    centralizado = any(e.value.get("multi_region") is True for e in habilitados)

    if habilitados and centralizado and syslog:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Fuentes de log habilitadas y centralizadas (CloudTrail multirregion + logs de"
            " sistema).",
            [e.id for e in habilitados],
        )
    if habilitados or syslog:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Fuentes de monitoreo habilitadas, sin CloudTrail multirregion junto a logs de"
            " sistema.",
            [e.id for e in habilitados] or [e.id for e in by_type(evidence, "an.service.state")],
        )
    return result(
        CRITERION_ID,
        Estado.NO_IMPLEMENTADO,
        0,
        "CloudTrail/logs declarados pero sin ninguna fuente de monitoreo habilitada.",
        [e.id for e in logging_cfg],
    )
