"""Entidad `incident` (docs/08 §4): se crea por un disparador, se actualiza por hechos
posteriores. El motor observa hechos; nunca los fabrica (no inventa un escalamiento porque
exista un plan). Idempotente por `correlation_key` (O4: la misma ingesta repetida no duplica
incidentes, solo extiende su timeline) — un cooldown por tiempo o un rate-limit por
organizacion/criterio quedan fuera de este corte.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.tables import Incident
from app.ops.triggers import TriggerMatch

#: Ciclo de vida de un incidente (docs/08 §4). `closed` es el unico estado terminal: la UI lo usa
#: para separar "activos" de "historial".
INCIDENT_ESTADOS = ("open", "triaged", "contained", "recovering", "closed")


def _timeline_entry(trigger: TriggerMatch) -> dict:
    return {
        "disparador": trigger.disparador,
        "momento": trigger.last_event_time.isoformat(),
        "titulo": trigger.titulo,
    }


def upsert_incident(
    session: Session, org_id: str, scope: str, trigger: TriggerMatch
) -> tuple[Incident, bool]:
    """Retorna `(incidente, es_nuevo)`."""

    incident = (
        session.query(Incident)
        .filter_by(org_id=org_id, correlation_key=trigger.correlation_key)
        .one_or_none()
    )

    if incident is None:
        incident = Incident(
            org_id=org_id,
            scope=scope,
            correlation_key=trigger.correlation_key,
            titulo=trigger.titulo,
            estado="open",
            severidad=trigger.severidad,
            first_event_time=trigger.first_event_time,
            last_event_time=trigger.last_event_time,
            event_ids=trigger.event_ids,
            criterios=trigger.criterios,
            timeline=[_timeline_entry(trigger)],
        )
        session.add(incident)
        session.flush()
        return incident, True

    incident.last_event_time = trigger.last_event_time
    incident.event_ids = sorted(set(incident.event_ids) | set(trigger.event_ids))
    incident.timeline = [*incident.timeline, _timeline_entry(trigger)]
    incident.actualizado_en = datetime.now(UTC)
    return incident, False


def set_incident_estado(incident: Incident, estado: str) -> Incident:
    """Cambia el estado de un incidente (docs/11 UI-06/OP-04). No valida contra `INCIDENT_ESTADOS`
    aqui: la ruta es la que rechaza un estado desconocido con un 422 antes de llamar."""

    incident.estado = estado
    incident.actualizado_en = datetime.now(UTC)
    return incident
