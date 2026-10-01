"""Plan de incidente (docs/08 §7): mismo esquema base que U3 (docs/05 §4.1), extendido con
diagnostico/hipotesis/comprobaciones/advertencia. El diagnostico es deterministico (plantilla
por disparador), no generado por IA: solo objetivo/pasos/verificacion vienen de
`generate_plan_content` (mismo principio "determinismo primero" que el resto del sistema).
"""

from __future__ import annotations

from app.ai.client import AIClient, NullAIClient
from app.ai.plan_generation import generate_plan_content
from app.methodology.loader import Methodology
from app.ops.triggers import TriggerMatch
from app.recommendations.plans import Plan

ADVERTENCIA = "Asesoria. No se ejecuta ninguna accion automaticamente."

#: disparador -> (plantilla de diagnostico, hipotesis, comprobaciones seguras). Adaptado de la
#: tabla "disparador -> plan" de docs/06 §7 / docs/08 §7.
_PLANTILLAS: dict[str, tuple[str, list[str], list[str]]] = {
    "D1": (
        "auth_failures_burst en {recurso} sin alert_raised.",
        ["Regla de deteccion ausente o umbral mal configurado."],
        ["Revisar reglas y umbrales de deteccion sin modificar produccion."],
    ),
    "D3": (
        "incident_declared en {recurso} sin escalation_done dentro del plazo documentado.",
        ["Ruta de escalamiento no definida o no seguida."],
        ["Revisar la ruta de escalamiento y los plazos sin modificar produccion."],
    ),
    "D4": (
        "restore_exercise_run en {recurso} con resultado fail.",
        ["Backup corrupto o procedimiento de restauracion incompleto."],
        ["Verificar la integridad del backup mas reciente sin sobrescribirlo."],
    ),
    "D5": (
        "restore_verified en {recurso} sin recovery_communicated.",
        ["Paso de comunicacion no definido en el procedimiento de recuperacion."],
        ["Confirmar con el equipo si la comunicacion ya se envio por otro canal."],
    ),
}


def _plan_source_criterion(methodology: Methodology, trigger: TriggerMatch):
    for criterion_id in trigger.criterios:
        criterion = methodology.criterios.get(criterion_id)
        if criterion is not None:
            return criterion_id, criterion
    return trigger.criterios[0], None


def generate_incident_plan(
    methodology: Methodology, trigger: TriggerMatch, client: AIClient | None = None
) -> Plan:
    active_client = client or NullAIClient()
    criterion_id, criterion = _plan_source_criterion(methodology, trigger)

    if criterion is not None:
        content = generate_plan_content(
            active_client,
            criterion,
            severidad=trigger.severidad,
            score=0.0,
            evidence_ids=trigger.event_ids,
        )
        titulo, objetivo, pasos, verificacion, dependencias = (
            content.titulo,
            content.objetivo,
            content.pasos,
            content.verificacion,
            content.dependencias,
        )
    else:
        titulo = objetivo = trigger.titulo
        pasos, verificacion, dependencias = [], "", []

    diagnostico_tpl, hipotesis, comprobaciones = _PLANTILLAS[trigger.disparador]
    ia_activa = type(active_client).__name__ != "NullAIClient"

    return Plan(
        criterion_id=criterion_id,
        titulo=titulo,
        prioridad=trigger.severidad,
        objetivo=objetivo,
        pasos=pasos,
        verificacion=verificacion,
        dependencias=dependencias,
        generado_por="ai:plan_v1" if ia_activa else "plantilla",
        origen="evento",
        diagnostico_observable=diagnostico_tpl.format(recurso=trigger.recurso),
        hipotesis=hipotesis,
        comprobaciones_seguras=comprobaciones,
        advertencia=ADVERTENCIA,
    )
