from pathlib import Path

from tests.conftest import TEST_ORG_NAME, run_pending_jobs

SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


def test_health(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_methodology_lists_catalog(api_client):
    response = api_client.get("/methodology")
    assert response.status_code == 200
    body = response.json()
    assert "methodology_version" in body
    ids = {c["id"] for c in body["criterios"]}
    assert "CRI-PR-01" in ids
    assert "log.pattern@1" in body["tipos_evidencia"]


def test_methodology_exposes_implementation_coverage(api_client):
    """Contrato que consume el dashboard: claves hermanas de `criterios`, nunca anidadas en el.

    La cobertura DEL CATALOGO no se mezcla con la cobertura de evidencia de una evaluacion
    (docs/01 7), y la UI no debe recalcular ninguno de estos numeros.
    """

    body = api_client.get("/methodology").json()
    cobertura = body["cobertura_implementacion"]

    assert set(cobertura) == {
        "subcategorias_cubiertas",
        "subcategorias_totales",
        "ratio",
        "categorias_cubiertas",
        "categorias_totales",
        "por_funcion",
        "categorias_sin_criterio",
    }
    assert cobertura["subcategorias_totales"] == 106
    assert cobertura["categorias_totales"] == 22
    assert set(cobertura["por_funcion"]) == {"GV", "ID", "PR", "DE", "RS", "RC"}
    assert "nucleo_csf_version" in body


def test_list_organizations_returns_only_my_org(api_client, auth_user):
    response = api_client.get("/orgs")
    assert response.status_code == 200
    assert [o["id"] for o in response.json()] == [auth_user.org_id]
    assert response.json()[0]["nombre"] == TEST_ORG_NAME


def test_events_on_another_org_is_404(api_client):
    with (SCENARIOS / "e1_flujo_correcto.jsonl").open("rb") as fh:
        response = api_client.post(
            "/orgs/no-existe/events", files={"file": ("e1.jsonl", fh, "application/jsonl")}
        )
    assert response.status_code == 404


def test_ingesting_e1b_opens_an_incident(
    api_client, db_session, methodology, fake_redis, auth_user
):
    with (SCENARIOS / "e1b_fallos_sin_alerta.jsonl").open("rb") as fh:
        response = api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": ("e1b.jsonl", fh, "application/jsonl")},
        )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    run_pending_jobs(db_session, methodology, fake_redis)
    assert api_client.get(f"/jobs/{job_id}").json()["estado"] == "completado"

    incidents = api_client.get(f"/orgs/{auth_user.org_id}/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["severidad"] == "media"


def test_flujo_correcto_opens_no_incident(
    api_client, db_session, methodology, fake_redis, auth_user
):
    with (SCENARIOS / "e1_flujo_correcto.jsonl").open("rb") as fh:
        response = api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": ("e1.jsonl", fh, "application/jsonl")},
        )
    assert response.status_code == 202

    run_pending_jobs(db_session, methodology, fake_redis)
    assert api_client.get(f"/orgs/{auth_user.org_id}/incidents").json() == []


def test_get_incident_and_its_plans(api_client, db_session, methodology, fake_redis, auth_user):
    with (SCENARIOS / "e1b_fallos_sin_alerta.jsonl").open("rb") as fh:
        api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": ("e1b.jsonl", fh, "application/jsonl")},
        )
    run_pending_jobs(db_session, methodology, fake_redis)

    incident_id = api_client.get(f"/orgs/{auth_user.org_id}/incidents").json()[0]["id"]

    detail = api_client.get(f"/incidents/{incident_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == incident_id

    plans = api_client.get(f"/incidents/{incident_id}/plans")
    assert plans.status_code == 200
    assert len(plans.json()) == 1
    assert plans.json()[0]["origen"] == "evento"


def test_get_unknown_incident_is_404(api_client):
    response = api_client.get("/incidents/no-existe")
    assert response.status_code == 404


def test_closing_an_incident_persists_the_state(
    api_client, db_session, methodology, fake_redis, auth_user
):
    with (SCENARIOS / "e1b_fallos_sin_alerta.jsonl").open("rb") as fh:
        api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": ("e1b.jsonl", fh, "application/jsonl")},
        )
    run_pending_jobs(db_session, methodology, fake_redis)
    incident_id = api_client.get(f"/orgs/{auth_user.org_id}/incidents").json()[0]["id"]

    response = api_client.patch(
        f"/incidents/{incident_id}",
        json={"estado": "closed", "motivo": "Falso positivo: pruebas de un administrador."},
    )
    assert response.status_code == 200
    assert response.json()["estado"] == "closed"
    assert response.json()["motivo_cierre"] == "Falso positivo: pruebas de un administrador."

    # Sale de "activos" (la UI filtra estado != closed) pero sigue en el historial.
    assert api_client.get(f"/incidents/{incident_id}").json()["estado"] == "closed"


def test_invalid_incident_state_is_422(api_client, db_session, methodology, fake_redis, auth_user):
    with (SCENARIOS / "e1b_fallos_sin_alerta.jsonl").open("rb") as fh:
        api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": ("e1b.jsonl", fh, "application/jsonl")},
        )
    run_pending_jobs(db_session, methodology, fake_redis)
    incident_id = api_client.get(f"/orgs/{auth_user.org_id}/incidents").json()[0]["id"]

    response = api_client.patch(f"/incidents/{incident_id}", json={"estado": "inexistente"})
    assert response.status_code == 422


# -- DELETE /orgs/{id}/events: limpiar para los logs de ejemplo ------------------------------------


def _ingest(api_client, db_session, methodology, fake_redis, auth_user, escenario):
    with (SCENARIOS / escenario).open("rb") as fh:
        api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": (escenario, fh, "application/jsonl")},
        )
    run_pending_jobs(db_session, methodology, fake_redis)


def test_clearing_events_removes_events_patterns_incidents_and_their_plans(
    api_client, db_session, methodology, fake_redis, auth_user
):
    from app.models.tables import Event, Incident, LogPatternRow, PlanRow

    _ingest(
        api_client, db_session, methodology, fake_redis, auth_user, "e1b_fallos_sin_alerta.jsonl"
    )
    assert api_client.get(f"/orgs/{auth_user.org_id}/incidents").json()

    response = api_client.delete(f"/orgs/{auth_user.org_id}/events")

    assert response.status_code == 200
    borrado = response.json()
    assert borrado["eventos"] == 6 and borrado["incidentes"] == 1 and borrado["planes"] == 1
    assert api_client.get(f"/orgs/{auth_user.org_id}/incidents").json() == []
    org = auth_user.org_id
    assert db_session.query(Event).filter_by(org_id=org).count() == 0
    assert db_session.query(LogPatternRow).filter_by(org_id=org).count() == 0
    assert db_session.query(Incident).filter_by(org_id=org).count() == 0
    assert db_session.query(PlanRow).filter(PlanRow.incident_id.isnot(None)).count() == 0


def test_after_clearing_the_same_log_opens_its_incident_again(
    api_client, db_session, methodology, fake_redis, auth_user
):
    """Sin limpiar, reingerir el mismo log no abre nada nuevo (dedup); limpiando, si."""

    _ingest(
        api_client, db_session, methodology, fake_redis, auth_user, "e1b_fallos_sin_alerta.jsonl"
    )
    api_client.delete(f"/orgs/{auth_user.org_id}/events")
    _ingest(
        api_client, db_session, methodology, fake_redis, auth_user, "e1b_fallos_sin_alerta.jsonl"
    )

    (incident,) = api_client.get(f"/orgs/{auth_user.org_id}/incidents").json()
    assert incident["estado"] == "open"


def test_clearing_is_refused_while_an_ingest_is_running(api_client, db_session, auth_user):
    from app.core import jobs as job_service

    job_service.create_job(db_session, "event_ingest", org_id=auth_user.org_id)

    response = api_client.delete(f"/orgs/{auth_user.org_id}/events")

    assert response.status_code == 409 and "en curso" in response.json()["detail"]


def test_clearing_another_organizations_events_is_forbidden(api_client):
    assert api_client.delete("/orgs/otra-org/events").status_code in (403, 404)
