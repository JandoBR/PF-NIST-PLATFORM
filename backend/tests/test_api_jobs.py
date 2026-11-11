"""`GET /jobs/{id}` reaprea perezosamente: si el job se quedo colgado (p. ej. no hay `worker-core`),
al sondearlo se marca `fallido` y se falla la `Assessment` ligada, para que el cliente nunca quede
esperando para siempre (docs/09 §20). Los jobs son de la organizacion del usuario (doc 10)."""

from datetime import UTC, datetime, timedelta

from app.api import routes_jobs
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core.queue import QUEUE_CORE, heartbeat_key
from tests.conftest import TEST_ORG_NAME


def test_get_job_reaps_stale_pending_and_fails_linked_assessment(
    db_session, methodology, api_client, monkeypatch
):
    monkeypatch.setattr(routes_jobs, "_PENDING_TIMEOUT", 0)

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name=TEST_ORG_NAME, scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job.creado_en = datetime.now(UTC) - timedelta(seconds=10)
    db_session.commit()

    response = api_client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "fallido"
    assert body["error"]

    db_session.refresh(assessment)
    assert assessment.estado == "fallida"
    assert assessment.error == body["error"]


def test_get_job_leaves_recent_pending_alone(db_session, methodology, api_client, monkeypatch):
    monkeypatch.setattr(routes_jobs, "_PENDING_TIMEOUT", 120)

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name=TEST_ORG_NAME, scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)

    response = api_client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["estado"] == "pendiente"
    db_session.refresh(assessment)
    assert assessment.estado == "pendiente"


def test_get_job_leaves_a_pending_job_queued_behind_a_long_job_alone(
    db_session, methodology, api_client, fake_redis, monkeypatch
):
    """El job viejo solo espera: su cola tiene un worker latiendo (docs/04 §5)."""

    monkeypatch.setattr(routes_jobs, "_PENDING_TIMEOUT", 0)

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name=TEST_ORG_NAME, scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job.creado_en = datetime.now(UTC) - timedelta(seconds=300)
    db_session.commit()
    fake_redis.set(heartbeat_key(QUEUE_CORE, "worker-test"), "ahora")

    response = api_client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["estado"] == "pendiente"
    db_session.refresh(assessment)
    assert assessment.estado == "pendiente"


def test_get_job_of_another_org_is_404(db_session, api_client):
    from app.models.tables import Organization

    other = Organization(nombre="Otra Org")
    db_session.add(other)
    db_session.commit()
    job = job_service.create_job(db_session, "event_ingest", org_id=other.id)

    assert api_client.get(f"/jobs/{job.id}").status_code == 404


def test_get_unknown_job_is_404(api_client):
    assert api_client.get("/jobs/no-existe").status_code == 404


# -- GET /jobs: historial de la organizacion (FN-01/API-03) -----------------------------------


def _pending_assessment(db_session, methodology, org_name=TEST_ORG_NAME):
    return svc.create_pending_assessment(
        db_session, methodology, org_name=org_name, scope="entorno:produccion"
    )


def test_list_jobs_returns_both_kinds_newest_first(db_session, methodology, api_client, auth_user):
    assessment = _pending_assessment(db_session, methodology)
    run = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    ingest = job_service.create_job(db_session, "event_ingest", org_id=auth_user.org_id)
    run.creado_en = datetime.now(UTC) - timedelta(seconds=30)
    db_session.commit()

    response = api_client.get("/jobs")

    assert response.status_code == 200
    # `assessment_run` solo lleva assessment_id: la organizacion sale de la evaluacion.
    assert [j["id"] for j in response.json()] == [ingest.id, run.id]
    assert response.json()[1]["assessment_id"] == assessment.id


def test_list_jobs_only_shows_the_users_organization(db_session, methodology, api_client):
    from app.models.tables import Organization

    mine = job_service.create_job(
        db_session,
        "assessment_run",
        assessment_id=_pending_assessment(db_session, methodology).id,
    )
    other = Organization(nombre="Otra Org")
    db_session.add(other)
    db_session.commit()
    job_service.create_job(db_session, "event_ingest", org_id=other.id)
    job_service.create_job(
        db_session,
        "assessment_run",
        assessment_id=_pending_assessment(db_session, methodology, "Otra Org").id,
    )

    assert [j["id"] for j in api_client.get("/jobs").json()] == [mine.id]


def test_list_jobs_filters_by_state_and_type(db_session, methodology, api_client, auth_user):
    assessment = _pending_assessment(db_session, methodology)
    run = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    ingest = job_service.create_job(db_session, "event_ingest", org_id=auth_user.org_id)
    job_service.mark_failed(db_session, ingest, "boom")

    fallidos = api_client.get("/jobs", params={"estado": "fallido"}).json()
    assert [j["id"] for j in fallidos] == [ingest.id] and fallidos[0]["error"] == "boom"
    runs = api_client.get("/jobs", params={"tipo": "assessment_run"}).json()
    assert [j["id"] for j in runs] == [run.id]
    assert api_client.get("/jobs", params={"estado": "otro"}).status_code == 422
    assert api_client.get("/jobs", params={"tipo": "otro"}).status_code == 422


def test_list_jobs_respects_the_limit(db_session, api_client, auth_user):
    for _ in range(3):
        job_service.create_job(db_session, "event_ingest", org_id=auth_user.org_id)

    assert len(api_client.get("/jobs", params={"limit": 2}).json()) == 2
    assert api_client.get("/jobs", params={"limit": 0}).status_code == 422


def test_list_jobs_reaps_stale_jobs_and_fails_the_linked_assessment(
    db_session, methodology, api_client, monkeypatch
):
    """Sin esto el historial mostraria "pendiente" un job que nadie va a tomar nunca."""

    monkeypatch.setattr(routes_jobs, "_PENDING_TIMEOUT", 0)
    assessment = _pending_assessment(db_session, methodology)
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job.creado_en = datetime.now(UTC) - timedelta(seconds=10)
    db_session.commit()

    (listed,) = api_client.get("/jobs").json()

    assert listed["id"] == job.id and listed["estado"] == "fallido" and listed["error"]
    db_session.refresh(assessment)
    assert assessment.estado == "fallida"


def test_list_jobs_requires_a_session(anon_client):
    assert anon_client.get("/jobs").status_code == 401


def test_job_result_is_exposed_by_the_api(db_session, api_client, auth_user):
    job = job_service.create_job(db_session, "event_ingest", org_id=auth_user.org_id)
    job_service.mark_done(db_session, job, {"eventos_nuevos": 4, "eventos_existentes": 2})

    resultado = api_client.get(f"/jobs/{job.id}").json()["resultado"]
    assert resultado["eventos_nuevos"] == 4
    assert resultado["eventos_existentes"] == 2
    # Los campos que el job no reporto se normalizan a 0, no quedan ausentes.
    assert resultado["eventos_leidos"] == 0 and resultado["patrones_nuevos"] == 0
    assert api_client.get("/jobs").json()[0]["resultado"]["eventos_nuevos"] == 4
