"""Consumo explicito de eventos por evaluacion (docs/08 §3, docs/09 §98).

Una evaluacion consume los origenes de eventos que se le piden, no todo lo guardado del org+scope:
una ingesta de otro escenario no puede colarse en el calculo de madurez.
"""

from pathlib import Path

from app.core import assessment_service as svc
from app.core import operations
from app.models.tables import Event, Job
from tests.conftest import TEST_ORG_NAME, run_pending_jobs

SCOPE = "entorno:produccion"
SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"
TERRAFORM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"
LOG_A = SCENARIOS / "e1b_fallos_sin_alerta.jsonl"
LOG_B = SCENARIOS / "e2_flujo_correcto.jsonl"
SOURCE_A = f"events:{LOG_A.name}"
SOURCE_B = f"events:{LOG_B.name}"


def _ingest_both(db_session, methodology) -> None:
    operations.ingest_events(db_session, methodology, "Empresa Fuentes", LOG_A)
    operations.ingest_events(db_session, methodology, "Empresa Fuentes", LOG_B)


def _patterns(evidence):
    return [e for e in evidence if e.type_id == "log.pattern"]


def _upload_terraform(api_client, fixture: str, **form):
    path = TERRAFORM_FIXTURES / fixture / "main.tf"
    with path.open("rb") as fh:
        return api_client.post(
            "/assessments",
            data={"scope": SCOPE, **form},
            files={"terraform_files": ("main.tf", fh, "text/plain")},
        )


def test_a_subset_of_sources_only_sees_its_own_events_and_patterns(db_session, methodology):
    _ingest_both(db_session, methodology)

    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_source_ids=[SOURCE_B],
    )
    evidence = svc.load_evidence(db_session, assessment.id)
    patrones = {e.value["patron"] for e in _patterns(evidence)}

    assert "incident_declared" in patrones and "escalation_done" in patrones
    assert "auth_failures_burst" not in patrones  # ese patron es del log A, no seleccionado
    window = next(e for e in evidence if e.type_id == "log.window")
    assert window.source_id == SOURCE_B
    assert window.value["desde"].startswith("2026-09-20T03:14:00")


def test_omitting_the_selection_keeps_using_every_source(db_session, methodology):
    _ingest_both(db_session, methodology)

    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Fuentes", scope=SCOPE
    )
    evidence = svc.load_evidence(db_session, assessment.id)
    patrones = {e.value["patron"] for e in _patterns(evidence)}

    assert {"auth_failures_burst", "incident_declared", "escalation_done"} <= patrones
    eventos = assessment.reproducibility["eventos"]
    assert eventos["todas"] is True
    assert eventos["source_ids"] == sorted([SOURCE_A, SOURCE_B])
    assert eventos["conteo"] == 9


def test_empty_selection_consumes_no_events(db_session, methodology):
    _ingest_both(db_session, methodology)

    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_source_ids=[],
    )
    evidence = svc.load_evidence(db_session, assessment.id)

    assert not [e for e in evidence if e.type_id in {"log.window", "log.pattern"}]
    eventos = assessment.reproducibility["eventos"]
    assert eventos["todas"] is False
    assert eventos["source_ids"] == []
    assert eventos["conteo"] == 0
    assert eventos["desde"] is None and eventos["hasta"] is None
    assert len(eventos["sha256"]) == 64


def test_reproducibility_records_selection_range_and_a_stable_hash(db_session, methodology):
    _ingest_both(db_session, methodology)

    solo_a = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_source_ids=[SOURCE_A],
    )
    solo_b = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_source_ids=[SOURCE_B],
    )

    eventos_a = solo_a.reproducibility["eventos"]
    eventos_b = solo_b.reproducibility["eventos"]
    assert eventos_a["source_ids"] == [SOURCE_A]
    assert eventos_a["conteo"] == 6
    assert eventos_a["desde"] == "2026-09-20T03:10:00+00:00"
    assert eventos_a["hasta"] == "2026-09-20T03:10:50+00:00"
    assert len(eventos_a["sha256"]) == 64
    assert eventos_a["sha256"] != eventos_b["sha256"]


def test_patterns_are_detected_once_per_type_across_sources(db_session, methodology):
    _ingest_both(db_session, methodology)

    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Fuentes", scope=SCOPE
    )
    patrones = [e.value["patron"] for e in _patterns(svc.load_evidence(db_session, assessment.id))]

    assert len(patrones) == len(set(patrones))
    assert patrones.count("auth_failures_burst") == 1


def test_event_sources_endpoint_lists_origins_with_their_range(
    api_client, db_session, methodology, auth_user
):
    operations.ingest_events(db_session, methodology, TEST_ORG_NAME, LOG_A)
    operations.ingest_events(db_session, methodology, TEST_ORG_NAME, LOG_B)

    response = api_client.get(f"/orgs/{auth_user.org_id}/event-sources", params={"scope": SCOPE})

    assert response.status_code == 200
    by_id = {s["source_id"]: s for s in response.json()}
    assert set(by_id) == {SOURCE_A, SOURCE_B}
    assert by_id[SOURCE_A]["eventos"] == 6
    assert by_id[SOURCE_A]["desde"].startswith("2026-09-20T03:10:00")
    assert by_id[SOURCE_A]["ultima_ingesta"] is not None


def test_api_rejects_event_sources_from_another_org(api_client):
    response = _upload_terraform(
        api_client, "good", event_source_ids='["events:de-otra-org.jsonl"]'
    )

    assert response.status_code == 400


def test_api_selection_reaches_the_worker_and_the_evidence(
    api_client, db_session, methodology, fake_redis, auth_user
):
    operations.ingest_events(db_session, methodology, TEST_ORG_NAME, LOG_A)
    operations.ingest_events(db_session, methodology, TEST_ORG_NAME, LOG_B)

    accepted = _upload_terraform(api_client, "good", event_source_ids=f'["{SOURCE_B}"]').json()
    run_pending_jobs(db_session, methodology, fake_redis)

    evidence = api_client.get(f"/assessments/{accepted['assessment_id']}/evidence").json()
    patrones = [e["value"]["patron"] for e in evidence if e["type_id"] == "log.pattern"]
    assert "auth_failures_burst" not in patrones

    detail = api_client.get(f"/assessments/{accepted['assessment_id']}").json()
    assert detail["reproducibility"]["eventos"]["source_ids"] == [SOURCE_B]


def test_reevaluation_inherits_an_explicit_selection(
    api_client, db_session, methodology, fake_redis, auth_user
):
    operations.ingest_events(db_session, methodology, TEST_ORG_NAME, LOG_A)
    operations.ingest_events(db_session, methodology, TEST_ORG_NAME, LOG_B)
    accepted = _upload_terraform(api_client, "good", event_source_ids=f'["{SOURCE_B}"]').json()
    run_pending_jobs(db_session, methodology, fake_redis)

    reeval = api_client.post(f"/assessments/{accepted['assessment_id']}/reevaluate")

    assert reeval.status_code == 202
    job = db_session.get(Job, reeval.json()["job_id"])
    assert job.payload["event_source_ids"] == [SOURCE_B]


def test_auto_refresh_inherits_the_explicit_selection(db_session, methodology, fake_redis):
    from app.core import refresh

    _ingest_both(db_session, methodology)
    previous = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_source_ids=[SOURCE_B],
    )

    _, job = refresh.enqueue_surveillance_refresh(db_session, methodology, fake_redis, previous.id)

    assert job.payload["event_source_ids"] == [SOURCE_B]


def test_event_sources_are_scoped_to_the_org(db_session, methodology):
    _ingest_both(db_session, methodology)
    org_id = db_session.query(Event).first().org_id

    sources = svc.list_event_sources(db_session, org_id, SCOPE)

    assert {s.source_id for s in sources} == {SOURCE_A, SOURCE_B}
    assert svc.list_event_sources(db_session, "otra-org", SCOPE) == []
