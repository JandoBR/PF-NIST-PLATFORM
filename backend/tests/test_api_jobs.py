"""`GET /jobs/{id}` reaprea perezosamente: si el job se quedo colgado (p. ej. no hay `worker-core`),
al sondearlo se marca `fallido` y se falla la `Assessment` ligada, para que el cliente nunca quede
esperando para siempre (docs/09 §20). Los jobs son de la organizacion del usuario (doc 10)."""

from datetime import UTC, datetime, timedelta

from app.api import routes_jobs
from app.core import assessment_service as svc
from app.core import jobs as job_service
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


def test_get_job_of_another_org_is_404(db_session, api_client):
    from app.models.tables import Organization

    other = Organization(nombre="Otra Org")
    db_session.add(other)
    db_session.commit()
    job = job_service.create_job(db_session, "event_ingest", org_id=other.id)

    assert api_client.get(f"/jobs/{job.id}").status_code == 404


def test_get_unknown_job_is_404(api_client):
    assert api_client.get("/jobs/no-existe").status_code == 404
