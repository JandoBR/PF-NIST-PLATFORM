from pathlib import Path

import pytest

from app.core import assessment_service as svc
from app.core import operations
from app.evaluation.schemas import Estado
from app.methodology.loader import load_methodology
from app.models.tables import Event, Incident, LogPatternRow, PlanRow

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def test_ingesting_e1b_opens_one_incident_with_a_plan(db_session, methodology):
    result = operations.ingest_events(
        db_session, methodology, "Empresa Ops", SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    )

    assert result.eventos_ingeridos == 6
    assert (result.eventos_nuevos, result.eventos_existentes) == (6, 0)
    assert len(result.nuevos_incidentes) == 1
    incident = result.nuevos_incidentes[0]
    assert incident.severidad == "media"

    plans = operations.load_incident_plans(db_session, incident.id)
    assert len(plans) == 1
    assert plans[0].origen == "evento"
    assert plans[0].generado_por == "plantilla"
    assert plans[0].advertencia is not None


def test_ingesting_e1_flujo_correcto_opens_no_incident(db_session, methodology):
    result = operations.ingest_events(
        db_session, methodology, "Empresa Ops Correcta", SCENARIOS / "e1_flujo_correcto.jsonl"
    )
    assert result.nuevos_incidentes == []
    assert result.incidentes_actualizados == []


def test_reingesting_the_same_file_does_not_duplicate_events_or_incidents(db_session, methodology):
    path = SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    first = operations.ingest_events(db_session, methodology, "Empresa Repetida", path)
    incident = first.nuevos_incidentes[0]
    entradas_timeline = len(incident.timeline)
    plan_id = db_session.query(PlanRow).filter_by(incident_id=incident.id).one().id

    second = operations.ingest_events(db_session, methodology, "Empresa Repetida", path)

    assert second.eventos_ingeridos == 6  # el parser siempre reporta lo leido del archivo
    assert (second.eventos_nuevos, second.eventos_existentes) == (0, 6)
    assert second.summary() == {
        "eventos_leidos": 6,
        "eventos_nuevos": 0,
        "eventos_existentes": 6,
        "patrones_nuevos": 0,
        "incidentes_nuevos": 0,
        "incidentes_actualizados": 0,
    }
    assert db_session.query(Event).filter_by(org_id=first.org_id).count() == 6  # pero no se duplica
    assert db_session.query(Incident).filter_by(org_id=first.org_id).count() == 1
    assert db_session.query(LogPatternRow).filter_by(org_id=first.org_id).count() == 1
    # Reingerir no reabre el incidente ni regenera su plan: ningun evento se inserto de verdad.
    db_session.refresh(incident)
    assert len(incident.timeline) == entradas_timeline
    assert db_session.query(PlanRow).filter_by(incident_id=incident.id).one().id == plan_id


def test_a_new_event_overlapping_an_existing_burst_still_updates_the_incident(
    db_session, methodology, tmp_path
):
    """La ingesta parcial suma un evento nuevo a una rafaga ya conocida: aunque otros ids
    del archivo ya estaban, el disparador si tiene un evento insertado y debe actualizar el
    incidente."""

    first = operations.ingest_events(
        db_session, methodology, "Empresa Parcial", SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    )
    incident = first.nuevos_incidentes[0]
    entradas_timeline = len(incident.timeline)
    plan_id = db_session.query(PlanRow).filter_by(incident_id=incident.id).one().id

    nuevo = tmp_path / "parcial.jsonl"
    nuevo.write_text(
        "\n".join(
            [
                # ya estaba: evento existente que se reenvia en el mismo archivo
                '{"event_id": "e1b-006", "event_time": "2026-09-20T03:10:50Z",'
                ' "tipo": "auth_failure", "recurso": "srv-app-01",'
                ' "scope": "entorno:produccion", "actor": "admin"}',
                # nuevo, dentro de la ventana de la misma rafaga
                '{"event_id": "e1b-007", "event_time": "2026-09-20T03:10:55Z",'
                ' "tipo": "auth_failure", "recurso": "srv-app-01",'
                ' "scope": "entorno:produccion", "actor": "admin"}',
            ]
        )
    )
    second = operations.ingest_events(db_session, methodology, "Empresa Parcial", nuevo)

    assert (second.eventos_nuevos, second.eventos_existentes) == (1, 1)
    assert [i.id for i in second.incidentes_actualizados] == [incident.id]
    db_session.refresh(incident)
    assert "e1b-007" in incident.event_ids
    assert len(incident.timeline) == entradas_timeline + 1
    assert db_session.query(PlanRow).filter_by(incident_id=incident.id).one().id != plan_id


def test_list_incidents_orders_by_most_recently_updated(db_session, methodology):
    operations.ingest_events(
        db_session, methodology, "Empresa Lista", SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    )
    operations.ingest_events(
        db_session, methodology, "Empresa Lista", SCENARIOS / "e2b_declarado_sin_escalar.jsonl"
    )

    incidents = operations.list_incidents(db_session, "Empresa Lista")
    assert len(incidents) == 2
    assert incidents[0].actualizado_en >= incidents[1].actualizado_en


def test_running_an_assessment_after_ingest_picks_up_surveillance_evidence(db_session, methodology):
    operations.ingest_events(
        db_session, methodology, "Empresa Vigilancia", SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    )

    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Vigilancia", scope="entorno:produccion"
    )
    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}

    # burst sin alerta: falla de deteccion observada, un 0 con estado no_implementado
    assert results["CRI-DE-02"].estado == Estado.NO_IMPLEMENTADO
    assert results["CRI-DE-02"].final_score == 0
    assert "evidencia_insuficiente" != results["CRI-DE-02"].estado


def test_assessment_for_org_without_any_events_is_insufficient_not_zero(db_session, methodology):
    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Sin Eventos", scope="entorno:produccion"
    )
    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    assert results["CRI-DE-02"].estado == Estado.EVIDENCIA_INSUFICIENTE
