"""FN-09: los jobs guardan sus entradas y un job fallido se puede reintentar."""

from pathlib import Path

import pytest

from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core import operations, refresh
from app.models.tables import CriterionResultRow, EvidenceRow, Job, Organization, PlanRow
from tests.conftest import run_pending_jobs
from tests.test_api_assessments import _upload_terraform

SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


def _upload_events(api_client, auth_user):
    with (SCENARIOS / "e1b_fallos_sin_alerta.jsonl").open("rb") as fh:
        return api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": ("e1b.jsonl", fh, "application/jsonl")},
        ).json()


def _fail_next_collection(monkeypatch):
    """Hace fallar la recoleccion de evidencia; devuelve la funcion que deshace el fallo."""

    original = svc._collect_evidence_and_sources

    def boom(*args, **kwargs):
        raise RuntimeError("fallo transitorio")

    monkeypatch.setattr(svc, "_collect_evidence_and_sources", boom)
    return lambda: monkeypatch.setattr(svc, "_collect_evidence_and_sources", original)


def _failed_assessment_job(api_client, db_session, methodology, fake_redis, monkeypatch):
    heal = _fail_next_collection(monkeypatch)
    accepted = _upload_terraform(api_client, "good").json()
    run_pending_jobs(db_session, methodology, fake_redis)
    heal()
    job = db_session.get(Job, accepted["job_id"])
    assert job.estado == "fallido" and "fallo transitorio" in job.error
    return accepted, job


# -- las entradas se guardan -----------------------------------------------------------------


def test_jobs_store_their_inputs_without_the_job_id(api_client, db_session, auth_user):
    accepted = _upload_terraform(api_client, "good", ai_adjust="false").json()
    run_job = db_session.get(Job, accepted["job_id"])
    assert run_job.payload["assessment_id"] == accepted["assessment_id"]
    assert Path(run_job.payload["terraform_path"]).exists()
    assert "job_id" not in run_job.payload

    ingest = db_session.get(Job, _upload_events(api_client, auth_user)["job_id"])
    assert Path(ingest.payload["jsonl_path"]).exists()
    assert ingest.payload["org_nombre"] == auth_user.organization.nombre


def test_reevaluation_and_refresh_jobs_store_their_inputs(
    api_client, db_session, methodology, fake_redis
):
    accepted = _upload_terraform(api_client, "good").json()
    run_pending_jobs(db_session, methodology, fake_redis)

    reeval = api_client.post(f"/assessments/{accepted['assessment_id']}/reevaluate").json()
    assert db_session.get(Job, reeval["job_id"]).payload["terraform_path"]

    _, refresh_job = refresh.enqueue_surveillance_refresh(
        db_session, methodology, fake_redis, accepted["assessment_id"]
    )
    assert refresh_job.payload["selective_refresh"] is True


# -- reintento de una evaluacion --------------------------------------------------------------


def test_retrying_a_failed_assessment_job_completes_it(
    api_client, db_session, methodology, fake_redis, monkeypatch
):
    accepted, failed = _failed_assessment_job(
        api_client, db_session, methodology, fake_redis, monkeypatch
    )
    listed = next(j for j in api_client.get("/jobs").json() if j["id"] == failed.id)
    assert listed["reintentable"] is True and listed["usa_ia"] is False

    response = api_client.post(f"/jobs/{failed.id}/retry")

    assert response.status_code == 202
    new = response.json()
    assert new["id"] != failed.id and new["estado"] == "pendiente"
    assert new["assessment_id"] == accepted["assessment_id"]  # misma evaluacion, no una nueva
    run_pending_jobs(db_session, methodology, fake_redis)
    detail = api_client.get(f"/assessments/{accepted['assessment_id']}").json()
    assert detail["estado"] == "completada" and detail["error"] is None
    assert db_session.get(Job, new["id"]).estado == "completado"
    assert db_session.get(Job, failed.id).estado == "fallido"  # el intento original queda


def test_a_failed_job_can_only_be_retried_once(
    api_client, db_session, methodology, fake_redis, monkeypatch
):
    _, failed = _failed_assessment_job(api_client, db_session, methodology, fake_redis, monkeypatch)

    assert api_client.post(f"/jobs/{failed.id}/retry").status_code == 202
    again = api_client.post(f"/jobs/{failed.id}/retry")

    assert again.status_code == 409 and "ya se reintento" in again.json()["detail"]


def test_retry_clears_partial_results_instead_of_duplicating_them(
    api_client, db_session, methodology, fake_redis
):
    """Una corrida que fallo despues de guardar (p. ej. al generar planes) deja filas a medias."""

    accepted = _upload_terraform(api_client, "good").json()
    run_pending_jobs(db_session, methodology, fake_redis)
    assessment_id = accepted["assessment_id"]
    resultados = db_session.query(CriterionResultRow).filter_by(assessment_id=assessment_id).count()
    assert resultados > 0
    job = db_session.get(Job, accepted["job_id"])
    assessment = svc.get_assessment(db_session, assessment_id)
    job_service.mark_failed(db_session, job, "fallo al generar planes")
    assessment.estado, assessment.error = "fallida", "fallo al generar planes"
    db_session.commit()

    assert api_client.post(f"/jobs/{job.id}/retry").status_code == 202
    run_pending_jobs(db_session, methodology, fake_redis)

    assert (
        db_session.query(CriterionResultRow).filter_by(assessment_id=assessment_id).count()
        == resultados
    )
    assert db_session.query(EvidenceRow).filter_by(assessment_id=assessment_id).count() > 0
    assert db_session.query(PlanRow).filter_by(assessment_id=assessment_id).count() == len(
        svc.load_plans(db_session, assessment_id)
    )


# -- reintento de una ingesta ----------------------------------------------------------------


def test_retrying_a_failed_event_ingest_does_not_duplicate_events(
    api_client, db_session, methodology, fake_redis, auth_user, monkeypatch
):
    original = operations.ingest_events

    def caido(*_args, **_kwargs):
        raise RuntimeError("redis caido")

    monkeypatch.setattr(operations, "ingest_events", caido)
    accepted = _upload_events(api_client, auth_user)
    run_pending_jobs(db_session, methodology, fake_redis)
    failed = db_session.get(Job, accepted["job_id"])
    assert failed.estado == "fallido"
    monkeypatch.setattr(operations, "ingest_events", original)

    new = api_client.post(f"/jobs/{failed.id}/retry")
    assert new.status_code == 202 and new.json()["tipo"] == "event_ingest"
    run_pending_jobs(db_session, methodology, fake_redis)
    assert db_session.get(Job, new.json()["id"]).estado == "completado"

    from app.models.tables import Event

    eventos = db_session.query(Event).count()
    assert eventos > 0
    # Reintentar de nuevo ingiere lo mismo: el dedup por event_id evita duplicados.
    failed.estado = "fallido"
    db_session.commit()
    assert api_client.post(f"/jobs/{failed.id}/retry").status_code == 202
    run_pending_jobs(db_session, methodology, fake_redis)
    assert db_session.query(Event).count() == eventos


# -- lo que no se puede reintentar -------------------------------------------------------------


def test_only_failed_jobs_can_be_retried(api_client, db_session, auth_user):
    job = job_service.create_job(
        db_session, "event_ingest", org_id=auth_user.org_id, payload={"jsonl_path": None}
    )

    response = api_client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409 and "fallido" in response.json()["detail"]
    listed = next(j for j in api_client.get("/jobs").json() if j["id"] == job.id)
    assert listed["reintentable"] is False


def test_a_job_without_stored_inputs_cannot_be_retried(api_client, db_session, auth_user):
    job = job_service.create_job(db_session, "event_ingest", org_id=auth_user.org_id)
    job_service.mark_failed(db_session, job, "x")

    response = api_client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409 and "anterior al guardado" in response.json()["detail"]
    listed = next(j for j in api_client.get("/jobs").json() if j["id"] == job.id)
    assert listed["reintentable"] is False


def test_retry_explains_when_the_uploaded_files_are_gone(
    api_client, db_session, auth_user, tmp_path
):
    job = job_service.create_job(
        db_session,
        "event_ingest",
        org_id=auth_user.org_id,
        payload={"jsonl_path": str(tmp_path / "borrado.jsonl"), "org_nombre": "x"},
    )
    job_service.mark_failed(db_session, job, "x")

    response = api_client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409
    assert "borrado.jsonl" in response.json()["detail"]


def test_retry_of_another_organizations_job_is_404(api_client, db_session):
    other = Organization(nombre="Otra Org")
    db_session.add(other)
    db_session.commit()
    job = job_service.create_job(db_session, "event_ingest", org_id=other.id, payload={})
    job_service.mark_failed(db_session, job, "x")

    assert api_client.post(f"/jobs/{job.id}/retry").status_code == 404
    assert api_client.post("/jobs/no-existe/retry").status_code == 404


def test_retry_requires_a_session(anon_client):
    assert anon_client.post("/jobs/x/retry").status_code == 401


# -- el permiso de gasto no se hereda ---------------------------------------------------------


@pytest.mark.parametrize("confirmed, expected", [(False, 409), (True, 202)])
def test_retrying_a_job_that_used_real_ai_needs_confirmation_again(
    api_client, db_session, auth_user, tmp_path, monkeypatch, confirmed, expected
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real")
    archivo = tmp_path / "e.jsonl"
    archivo.write_text("")
    job = job_service.create_job(
        db_session,
        "event_ingest",
        org_id=auth_user.org_id,
        payload={"jsonl_path": str(archivo), "org_nombre": "x", "ai_requested": True},
    )
    job_service.mark_failed(db_session, job, "x")
    listed = next(j for j in api_client.get("/jobs").json() if j["id"] == job.id)
    assert listed["usa_ia"] is True

    response = api_client.post(f"/jobs/{job.id}/retry", params={"confirm_live_ai": confirmed})

    assert response.status_code == expected
