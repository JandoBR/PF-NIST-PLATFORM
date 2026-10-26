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


#: Siguiente paso del ciclo de vida: se avanza de uno en uno (docs/08 §4).
_SIGUIENTE = {
    "open": "triaged",
    "triaged": "contained",
    "contained": "recovering",
    "recovering": "closed",
}


class InvalidTransition(ValueError):
    """El cambio de estado no esta permitido; el mensaje dice desde donde y a donde se puede ir."""


def allowed_transitions(estado: str) -> list[str]:
    """Estados a los que se puede pasar desde `estado` (docs/11 OP-11).

    Se avanza un paso por vez y no se retrocede. `closed` es terminal, y es el unico estado al que
    se puede saltar desde cualquier estado abierto: cerrar un falso positivo (el diagrama de
    docs/08 §4 lo muestra desde `open`) o un incidente resuelto sin pasar por todo el ciclo, siempre
    con el motivo registrado."""

    siguiente = _SIGUIENTE.get(estado)
    if siguiente is None:
        return []
    return [siguiente] if siguiente == "closed" else [siguiente, "closed"]


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
        .filter_by(org_id=org_id, scope=scope, correlation_key=trigger.correlation_key)
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


def set_incident_estado(incident: Incident, estado: str, motivo: str | None = None) -> Incident:
    """Cambia el estado de un incidente validando la transicion (docs/11 UI-06/OP-04/OP-11).

    Cerrar exige `motivo` (como se verifico o por que se descarta) y lo guarda en
    `motivo_cierre`; toda transicion queda en la linea de tiempo. No valida que `estado` exista en
    `INCIDENT_ESTADOS`: la ruta rechaza un estado desconocido con un 422 antes de llamar."""

    permitidas = allowed_transitions(incident.estado)
    if estado not in permitidas:
        desde = (
            "esta cerrado (estado terminal)"
            if not permitidas
            else f"esta {incident.estado!r}; puede pasar a: {', '.join(permitidas)}"
        )
        raise InvalidTransition(f"El incidente {desde}, no a {estado!r}.")
    motivo = (motivo or "").strip() or None
    if estado == "closed":
        if motivo is None:
            raise InvalidTransition(
                "Cerrar un incidente exige registrar el motivo o como se verifico."
            )
        incident.motivo_cierre = motivo

    ahora = datetime.now(UTC)
    entrada = {"transicion": f"{incident.estado}->{estado}", "momento": ahora.isoformat()}
    if motivo is not None:
        entrada["motivo"] = motivo
    incident.timeline = [*incident.timeline, entrada]
    incident.estado = estado
    incident.actualizado_en = ahora
    return incident
