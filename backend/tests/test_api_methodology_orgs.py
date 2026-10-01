from pathlib import Path

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


def test_create_organization_is_get_or_create(api_client):
    first = api_client.post("/orgs", json={"nombre": "Empresa API"})
    second = api_client.post("/orgs", json={"nombre": "Empresa API"})

    assert first.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_list_organizations(api_client):
    api_client.post("/orgs", json={"nombre": "Empresa Lista"})
    response = api_client.get("/orgs")

    assert response.status_code == 200
    assert any(o["nombre"] == "Empresa Lista" for o in response.json())


def test_events_on_unknown_org_is_404(api_client):
    with (SCENARIOS / "e1_flujo_correcto.jsonl").open("rb") as fh:
        response = api_client.post(
            "/orgs/no-existe/events", files={"file": ("e1.jsonl", fh, "application/jsonl")}
        )
    assert response.status_code == 404


def test_ingesting_e1b_opens_an_incident(api_client):
    org = api_client.post("/orgs", json={"nombre": "Empresa Eventos"}).json()

    with (SCENARIOS / "e1b_fallos_sin_alerta.jsonl").open("rb") as fh:
        response = api_client.post(
            f"/orgs/{org['id']}/events", files={"file": ("e1b.jsonl", fh, "application/jsonl")}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["eventos_ingeridos"] == 6
    assert len(body["nuevos_incidentes"]) == 1
    assert body["nuevos_incidentes"][0]["severidad"] == "media"

    incidents = api_client.get(f"/orgs/{org['id']}/incidents").json()
    assert len(incidents) == 1


def test_flujo_correcto_opens_no_incident(api_client):
    org = api_client.post("/orgs", json={"nombre": "Empresa Correcta"}).json()

    with (SCENARIOS / "e1_flujo_correcto.jsonl").open("rb") as fh:
        response = api_client.post(
            f"/orgs/{org['id']}/events", files={"file": ("e1.jsonl", fh, "application/jsonl")}
        )

    assert response.json()["nuevos_incidentes"] == []
    assert api_client.get(f"/orgs/{org['id']}/incidents").json() == []


def test_get_incident_and_its_plans(api_client):
    org = api_client.post("/orgs", json={"nombre": "Empresa Incidente"}).json()
    with (SCENARIOS / "e1b_fallos_sin_alerta.jsonl").open("rb") as fh:
        ingest = api_client.post(
            f"/orgs/{org['id']}/events", files={"file": ("e1b.jsonl", fh, "application/jsonl")}
        ).json()
    incident_id = ingest["nuevos_incidentes"][0]["id"]

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
