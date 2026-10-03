"""API-04: todos los errores son `application/problem+json`, y toda respuesta trae la version de
metodologia (docs/04 §6)."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers

PROBLEM = "application/problem+json"


def _assert_problem(response, status, title):
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM)
    body = response.json()
    assert body["status"] == status and body["title"] == title
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["instance"].endswith(response.request.url.path) or "://" in body["instance"]
    assert body["type"].startswith("https://pf.local/problems/")
    return body


def test_http_exceptions_outside_assessments_are_problem_json(api_client):
    # `jobs` nunca tuvo handler propio: antes devolvia el {"detail": ...} de FastAPI.
    body = _assert_problem(api_client.get("/jobs/no-existe"), 404, "Not Found")
    assert "no-existe" in body["detail"]


def test_a_conflict_is_problem_json(api_client, db_session, auth_user):
    from app.core import jobs as job_service

    job = job_service.create_job(db_session, "event_ingest", org_id=auth_user.org_id)

    body = _assert_problem(api_client.post(f"/jobs/{job.id}/retry"), 409, "Conflict")
    assert "fallido" in body["detail"]


def test_auth_errors_are_problem_json(anon_client):
    _assert_problem(anon_client.get("/jobs"), 401, "Unauthorized")


def test_validation_errors_have_a_text_detail_and_the_fields(api_client):
    response = api_client.get("/jobs", params={"limit": 0})

    body = _assert_problem(response, 422, "Unprocessable Entity")
    assert "limit" in body["detail"]
    assert body["errors"][0]["loc"][-1] == "limit" and body["errors"][0]["msg"]


def test_every_response_carries_the_methodology_version(api_client, methodology):
    for ruta in ("/health", "/jobs", "/jobs/no-existe", "/no-existe"):
        response = api_client.get(ruta)
        assert response.headers["X-Methodology-Version"] == methodology.methodology_version, ruta


def test_unexpected_errors_do_not_leak_internals():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secreto interno: password=hunter2")

    @app.get("/forbidden")
    def forbidden():
        raise HTTPException(status_code=403, detail="No permitido.", headers={"X-Motivo": "rol"})

    cliente = TestClient(app, raise_server_exceptions=False)

    body = _assert_problem(cliente.get("/boom"), 500, "Internal Server Error")
    assert "hunter2" not in str(body)
    prohibido = cliente.get("/forbidden")
    _assert_problem(prohibido, 403, "Forbidden")
    assert prohibido.headers["X-Motivo"] == "rol"  # las cabeceras de la excepcion se conservan
