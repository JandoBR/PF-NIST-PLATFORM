from pathlib import Path

import pytest

from app.core import assessment_service as svc
from app.evaluation.schemas import Estado
from app.methodology.loader import load_methodology
from app.models.tables import Event, Incident, LogPatternRow

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def test_ingesting_e1b_opens_one_incident_with_a_plan(db_session, methodology):
    result = svc.ingest_events(
        db_session, methodology, "Empresa Ops", SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    )

    assert result.eventos_ingeridos == 6
    assert len(result.nuevos_incidentes) == 1
    incident = result.nuevos_incidentes[0]
    assert incident.severidad == "media"

    plans = svc.load_incident_plans(db_session, incident.id)
    assert len(plans) == 1
    assert plans[0].origen == "evento"
    assert plans[0].generado_por == "plantilla"
    assert plans[0].advertencia is not None


def test_ingesting_e1_flujo_correcto_opens_no_incident(db_session, methodology):
    result = svc.ingest_events(
        db_session, methodology, "Empresa Ops Correcta", SCENARIOS / "e1_flujo_correcto.jsonl"
    )
    assert result.nuevos_incidentes == []
    assert result.incidentes_actualizados == []


def test_reingesting_the_same_file_does_not_duplicate_events_or_incidents(db_session, methodology):
    path = SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    first = svc.ingest_events(db_session, methodology, "Empresa Repetida", path)
    second = svc.ingest_events(db_session, methodology, "Empresa Repetida", path)

    assert second.eventos_ingeridos == 6  # el parser siempre reporta lo leido del archivo
    assert db_session.query(Event).filter_by(org_id=first.org_id).count() == 6  # pero no se duplica
    assert db_session.query(Incident).filter_by(org_id=first.org_id).count() == 1
    assert db_session.query(LogPatternRow).filter_by(org_id=first.org_id).count() == 1


def test_list_incidents_orders_by_most_recently_updated(db_session, methodology):
    svc.ingest_events(
        db_session, methodology, "Empresa Lista", SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    )
    svc.ingest_events(
        db_session, methodology, "Empresa Lista", SCENARIOS / "e2b_declarado_sin_escalar.jsonl"
    )

    incidents = svc.list_incidents(db_session, "Empresa Lista")
    assert len(incidents) == 2
    assert incidents[0].actualizado_en >= incidents[1].actualizado_en


def test_running_an_assessment_after_ingest_picks_up_surveillance_evidence(db_session, methodology):
    svc.ingest_events(
        db_session, methodology, "Empresa Vigilancia", SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
    )

    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Vigilancia", scope="entorno:produccion"
    )
    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}

    assert results["CRI-DE-02"].estado == Estado.EVALUADO
    assert results["CRI-DE-02"].final_score == 0  # burst sin alerta: falla de deteccion
    assert "evidencia_insuficiente" != results["CRI-DE-02"].estado


def test_assessment_for_org_without_any_events_is_insufficient_not_zero(db_session, methodology):
    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Sin Eventos", scope="entorno:produccion"
    )
    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    assert results["CRI-DE-02"].estado == Estado.EVIDENCIA_INSUFICIENTE
