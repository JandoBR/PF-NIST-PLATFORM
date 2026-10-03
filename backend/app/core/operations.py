"""Flujo B: eventos operativos e incidentes (docs/06, docs/08).

Ingerir un archivo de eventos (patrones, disparadores, incidentes y sus planes) y consultar o
cambiar el estado de los incidentes. No toca evaluaciones: la madurez solo ve los eventos cuando una
evaluacion los lee como `log.window`/`log.pattern` (`assessment_service`), y la reevaluacion
automatica tras una ingesta vive en `refresh`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.client import AIClient
from app.core.assessment_service import get_or_create_organization
from app.core.repository import (
    plan_to_row,
    row_to_plan,
)
from app.methodology.loader import Methodology
from app.models.tables import (
    Event,
    Incident,
    LogPatternRow,
    Organization,
    PlanRow,
)
from app.ops.incidents import set_incident_estado, upsert_incident
from app.ops.plans import generate_incident_plan
from app.ops.triggers import evaluate_triggers
from app.recommendations.plans import Plan
from app.surveillance.events import load_events_jsonl
from app.surveillance.patterns import detect_patterns


def _naive(moment: datetime) -> datetime:
    """SQLite descarta tzinfo al guardar `DateTime(timezone=True)`; normalizar antes de comparar."""

    return moment.replace(tzinfo=None)


def _event_source_id(fuente: str | None, jsonl_path: Path) -> str:
    """Origen del evento (docs/06 §2): su `fuente` si la declara; si no, el archivo del que vino
    (solo el nombre, no la ruta del servidor)."""

    return fuente or f"events:{Path(jsonl_path).name}"


@dataclass
class IngestResult:
    org_id: str
    #: Eventos leidos del archivo (nuevos + los que ya estaban).
    eventos_ingeridos: int
    nuevos_incidentes: list[Incident]
    incidentes_actualizados: list[Incident]
    #: Eventos que no estaban ya guardados (mismo `event_id` en el mismo scope = ya existia).
    eventos_nuevos: int = 0
    #: Patrones (`log.pattern`) realmente nuevos por scope, es decir la evidencia que consume la
    #: madurez. Reingerir el mismo archivo da 0. Alimenta el refresco automatico (docs/08 §8).
    patrones_nuevos_por_scope: dict[str, int] = field(default_factory=dict)

    @property
    def eventos_existentes(self) -> int:
        return self.eventos_ingeridos - self.eventos_nuevos

    def summary(self) -> dict[str, int]:
        """Resumen para `Job.resultado` (docs/11 FN-03): nuevos vs ya existentes."""

        return {
            "eventos_leidos": self.eventos_ingeridos,
            "eventos_nuevos": self.eventos_nuevos,
            "eventos_existentes": self.eventos_existentes,
            "patrones_nuevos": sum(self.patrones_nuevos_por_scope.values()),
            "incidentes_nuevos": len(self.nuevos_incidentes),
            "incidentes_actualizados": len(self.incidentes_actualizados),
        }


def ingest_events(
    session: Session,
    methodology: Methodology,
    org_name: str,
    jsonl_path: Path,
    ai_client: AIClient | None = None,
) -> IngestResult:
    """Flujo B completo (docs/08 §1): eventos -> patrones -> disparadores -> incidentes -> planes.

    El flujo A (evidencia de madurez) no se recalcula aqui: la proxima vez que se corra
    `run_assessment` para este org/scope, `collect_surveillance_evidence` ya vera los
    `log_patterns` persistidos ahora (docs/06 §6: "recalcular SOLO los criterios afectados" se
    logra simplemente evaluando una nueva assessment, nunca mutando una anterior).
    """

    org = get_or_create_organization(session, org_name)
    raw_events = load_events_jsonl(jsonl_path)

    por_scope: dict[str, list] = {}
    for evento in raw_events:
        por_scope.setdefault(evento.scope, []).append(evento)

    nuevos: list[Incident] = []
    actualizados: list[Incident] = []
    patrones_nuevos_por_scope: dict[str, int] = {}
    eventos_nuevos = 0

    for scope, eventos in por_scope.items():
        ya_ingeridos = {
            row.event_id
            for row in session.query(Event.event_id).filter_by(org_id=org.id, scope=scope).all()
        }
        for evento in eventos:
            if evento.event_id in ya_ingeridos:
                continue  # mismo archivo reingerido: no duplicar filas append-only
            eventos_nuevos += 1
            session.add(
                Event(
                    org_id=org.id,
                    scope=scope,
                    event_id=evento.event_id,
                    event_time=evento.event_time,
                    tipo=evento.tipo,
                    recurso=evento.recurso,
                    actor=evento.actor,
                    detalle=evento.detalle,
                    source_id=_event_source_id(evento.fuente, jsonl_path),
                )
            )
        session.flush()

        matches = detect_patterns(eventos, methodology.settings.vigilancia)
        # SQLite no conserva tzinfo en DateTime(timezone=True): se compara en naive UTC para
        # que el dedup no falle silenciosamente por un desajuste de tipo, no de valor.
        patrones_existentes = {
            (row.patron, _naive(row.desde), _naive(row.hasta), row.conteo)
            for row in session.query(LogPatternRow).filter_by(org_id=org.id, scope=scope).all()
        }
        agregados = 0
        for match in matches:
            clave = (match.patron, _naive(match.desde), _naive(match.hasta), match.conteo)
            if clave in patrones_existentes:
                continue  # mismo archivo reingerido: no duplicar el patron ya detectado
            session.add(
                LogPatternRow(
                    org_id=org.id,
                    scope=scope,
                    patron=match.patron,
                    resultado=match.resultado,
                    desde=match.desde,
                    hasta=match.hasta,
                    conteo=match.conteo,
                    fuentes=sorted(
                        {
                            _event_source_id(e.fuente, jsonl_path)
                            for e in eventos
                            if e.event_id in set(match.event_ids)
                        }
                    )
                    or None,
                )
            )
            agregados += 1
        patrones_nuevos_por_scope[scope] = agregados
        session.flush()

        triggers = evaluate_triggers(matches, methodology.settings.vigilancia, scope)
        for trigger in triggers:
            incident, es_nuevo = upsert_incident(session, org.id, scope, trigger)
            (nuevos if es_nuevo else actualizados).append(incident)

            plan = generate_incident_plan(methodology, trigger, client=ai_client)
            session.query(PlanRow).filter_by(incident_id=incident.id).delete()
            session.add(plan_to_row(plan, incident_id=incident.id))

    session.commit()
    return IngestResult(
        org_id=org.id,
        eventos_ingeridos=len(raw_events),
        eventos_nuevos=eventos_nuevos,
        nuevos_incidentes=nuevos,
        incidentes_actualizados=actualizados,
        patrones_nuevos_por_scope=patrones_nuevos_por_scope,
    )


def list_incidents(session: Session, org_name: str) -> list[Incident]:
    org = session.query(Organization).filter_by(nombre=org_name).one_or_none()
    if org is None:
        return []
    return (
        session.query(Incident)
        .filter_by(org_id=org.id)
        .order_by(Incident.actualizado_en.desc())
        .all()
    )


def load_incident_plans(session: Session, incident_id: str) -> list[Plan]:
    rows = session.query(PlanRow).filter_by(incident_id=incident_id).all()
    return [row_to_plan(row) for row in rows]


def get_incident(session: Session, incident_id: str) -> Incident | None:
    return session.get(Incident, incident_id)


def update_incident_estado(
    session: Session, incident_id: str, estado: str, motivo: str | None = None
) -> Incident | None:
    """Cambia el estado y persiste (docs/11 UI-06/OP-04/OP-11). `None` si el incidente no existe;
    lanza `InvalidTransition` si el cambio no esta permitido o falta el motivo al cerrar."""

    incident = session.get(Incident, incident_id)
    if incident is None:
        return None
    set_incident_estado(incident, estado, motivo)
    session.commit()
    return incident


def clear_operational_data(session: Session, org_id: str) -> dict[str, int]:
    """Borra los eventos, patrones e incidentes (con sus planes) de una organizacion.

    Pensado para los logs de ejemplo de la UI: cada boton muestra un escenario desde cero, sin
    arrastrar incidentes del anterior. Las evaluaciones ya hechas no cambian: guardan su propia
    copia de la evidencia operativa (son instantaneas, docs/00 §7)."""

    incidentes = [i.id for i in session.query(Incident.id).filter_by(org_id=org_id).all()]
    planes = (
        session.query(PlanRow).filter(PlanRow.incident_id.in_(incidentes)).delete()
        if incidentes
        else 0
    )
    borrado = {
        "planes": planes,
        "incidentes": session.query(Incident).filter_by(org_id=org_id).delete(),
        "patrones": session.query(LogPatternRow).filter_by(org_id=org_id).delete(),
        "eventos": session.query(Event).filter_by(org_id=org_id).delete(),
    }
    session.commit()
    return borrado
