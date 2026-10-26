from datetime import UTC, datetime, timedelta

from app.models.tables import Incident, Organization
from app.ops.incidents import upsert_incident
from app.ops.triggers import TriggerMatch


def _org(db_session, nombre="Empresa Ops") -> Organization:
    org = Organization(nombre=nombre)
    db_session.add(org)
    db_session.flush()
    return org


def _trigger(correlation_key="ck-1", last_event_time=None) -> TriggerMatch:
    now = datetime.now(UTC)
    return TriggerMatch(
        disparador="D1",
        correlation_key=correlation_key,
        severidad="media",
        criterios=["CRI-DE-02"],
        titulo="Titulo",
        recurso="srv-01",
        first_event_time=now,
        last_event_time=last_event_time or now,
        event_ids=["e1", "e2"],
    )


def test_first_trigger_creates_a_new_open_incident(db_session):
    org = _org(db_session)
    incident, es_nuevo = upsert_incident(db_session, org.id, "entorno:produccion", _trigger())

    assert es_nuevo is True
    assert incident.estado == "open"
    assert incident.event_ids == ["e1", "e2"]
    assert len(incident.timeline) == 1


def test_repeated_trigger_with_same_correlation_key_updates_not_duplicates(db_session):
    org = _org(db_session)
    first, _ = upsert_incident(db_session, org.id, "s", _trigger(correlation_key="ck-same"))

    mas_tarde = datetime.now(UTC) + timedelta(minutes=5)
    later = _trigger(correlation_key="ck-same", last_event_time=mas_tarde)
    second, es_nuevo = upsert_incident(db_session, org.id, "s", later)

    assert es_nuevo is False
    assert first.id == second.id
    assert db_session.query(Incident).filter_by(org_id=org.id).count() == 1
    assert len(second.timeline) == 2


def test_same_correlation_key_in_another_scope_is_a_separate_incident(db_session):
    """El entorno forma parte de la identidad: produccion y staging no se contaminan."""

    org = _org(db_session)
    produccion, _ = upsert_incident(
        db_session, org.id, "entorno:produccion", _trigger(correlation_key="ck-shared")
    )
    staging, es_nuevo = upsert_incident(
        db_session, org.id, "entorno:staging", _trigger(correlation_key="ck-shared")
    )

    assert es_nuevo is True
    assert produccion.id != staging.id
    assert db_session.query(Incident).filter_by(org_id=org.id).count() == 2


def test_different_correlation_keys_create_separate_incidents(db_session):
    org = _org(db_session)
    upsert_incident(db_session, org.id, "s", _trigger(correlation_key="ck-a"))
    upsert_incident(db_session, org.id, "s", _trigger(correlation_key="ck-b"))

    assert db_session.query(Incident).filter_by(org_id=org.id).count() == 2


def test_new_event_ids_are_merged_not_replaced(db_session):
    org = _org(db_session)
    upsert_incident(db_session, org.id, "s", _trigger(correlation_key="ck-merge"))

    segundo = _trigger(correlation_key="ck-merge")
    segundo = TriggerMatch(**{**segundo.__dict__, "event_ids": ["e2", "e3"]})
    incident, _ = upsert_incident(db_session, org.id, "s", segundo)

    assert incident.event_ids == ["e1", "e2", "e3"]


def test_ingesting_e1c_opens_a_d2_incident_with_a_triage_plan(db_session, methodology):
    from pathlib import Path

    from app.core import operations

    escenarios = Path(__file__).resolve().parent / "fixtures" / "scenarios"
    ruta = escenarios / "e1c_alerta_sin_triaje.jsonl"
    result = operations.ingest_events(db_session, methodology, "Empresa D2", ruta)

    (incident,) = result.nuevos_incidentes
    assert incident.titulo == "Alerta sin triaje a tiempo" and incident.criterios == ["CRI-RS-01"]
    (plan,) = operations.load_incident_plans(db_session, incident.id)
    assert plan.criterion_id == "CRI-RS-01" and plan.prioridad == "media"
    assert "alert_raised" in plan.diagnostico_observable


def test_two_organizations_can_share_a_correlation_key(db_session):
    """La clave sale de los eventos (recurso + hora): dos organizaciones que ingieren el mismo log
    la comparten. Antes era unica global y la segunda ingesta fallaba con IntegrityError."""

    a, b = _org(db_session, "Org A"), _org(db_session, "Org B")
    primero, nuevo_a = upsert_incident(db_session, a.id, "s", _trigger(correlation_key="ck-shared"))
    segundo, nuevo_b = upsert_incident(db_session, b.id, "s", _trigger(correlation_key="ck-shared"))
    db_session.commit()

    assert nuevo_a and nuevo_b and primero.id != segundo.id
    assert db_session.query(Incident).filter_by(correlation_key="ck-shared").count() == 2
