"""OP-11: el ciclo de vida del incidente se valida y cerrar exige un motivo (docs/08 §4)."""

import pytest

from app.models.tables import Incident, Organization
from app.ops.incidents import InvalidTransition, allowed_transitions, set_incident_estado

SCENARIOS = "e1b_fallos_sin_alerta.jsonl"


def _incident(db_session, estado="open") -> Incident:
    org = Organization(nombre=f"Org {estado}")
    db_session.add(org)
    db_session.flush()
    from datetime import UTC, datetime

    incident = Incident(
        org_id=org.id,
        scope="entorno:produccion",
        correlation_key=f"k-{estado}",
        titulo="t",
        estado=estado,
        severidad="media",
        first_event_time=datetime.now(UTC),
        last_event_time=datetime.now(UTC),
        event_ids=[],
        criterios=[],
        timeline=[],
    )
    db_session.add(incident)
    db_session.flush()
    return incident


def test_allowed_transitions_follow_the_lifecycle():
    assert allowed_transitions("open") == ["triaged", "closed"]
    assert allowed_transitions("triaged") == ["contained", "closed"]
    assert allowed_transitions("contained") == ["recovering", "closed"]
    assert allowed_transitions("recovering") == ["closed"]
    assert allowed_transitions("closed") == []
    assert allowed_transitions("desconocido") == []


def test_the_lifecycle_advances_one_step_at_a_time_and_records_each_transition(db_session):
    incident = _incident(db_session)

    for siguiente in ("triaged", "contained", "recovering"):
        set_incident_estado(incident, siguiente)
    set_incident_estado(incident, "closed", "Restauracion verificada con el ejercicio de RC-02.")

    assert incident.estado == "closed"
    assert [e["transicion"] for e in incident.timeline] == [
        "open->triaged",
        "triaged->contained",
        "contained->recovering",
        "recovering->closed",
    ]
    assert incident.timeline[-1]["motivo"].startswith("Restauracion verificada")
    assert incident.motivo_cierre.startswith("Restauracion verificada")


@pytest.mark.parametrize(
    "desde, hacia",
    [("open", "contained"), ("open", "recovering"), ("triaged", "recovering"), ("triaged", "open")],
)
def test_skipping_steps_or_going_back_is_rejected(db_session, desde, hacia):
    incident = _incident(db_session, desde)

    with pytest.raises(InvalidTransition) as exc:
        set_incident_estado(incident, hacia)

    assert desde in str(exc.value) and "puede pasar a" in str(exc.value)
    assert incident.estado == desde and incident.timeline == []  # no cambio nada


def test_a_closed_incident_cannot_be_reopened_or_closed_again(db_session):
    incident = _incident(db_session)
    set_incident_estado(incident, "closed", "Falso positivo.")

    for destino in ("open", "triaged", "closed"):
        with pytest.raises(InvalidTransition, match="terminal"):
            set_incident_estado(incident, destino, "otra vez")


@pytest.mark.parametrize("estado", ["open", "triaged", "contained", "recovering"])
def test_any_open_incident_can_be_closed_with_a_reason(db_session, estado):
    incident = _incident(db_session, estado)

    set_incident_estado(incident, "closed", "  Descartado tras revisar el log.  ")

    assert incident.estado == "closed"
    assert incident.motivo_cierre == "Descartado tras revisar el log."


@pytest.mark.parametrize("motivo", [None, "", "   "])
def test_closing_requires_a_reason(db_session, motivo):
    incident = _incident(db_session)

    with pytest.raises(InvalidTransition, match="motivo"):
        set_incident_estado(incident, "closed", motivo)

    assert incident.estado == "open" and incident.motivo_cierre is None


def test_a_reason_on_a_non_closing_transition_goes_to_the_timeline_only(db_session):
    incident = _incident(db_session)

    set_incident_estado(incident, "triaged", "Revisado por el SOC.")

    assert incident.timeline[-1]["motivo"] == "Revisado por el SOC."
    assert incident.motivo_cierre is None


# -- API ------------------------------------------------------------------------------------


def _api_incident(api_client, db_session, methodology, fake_redis, auth_user):
    from pathlib import Path

    from tests.conftest import run_pending_jobs

    path = Path(__file__).resolve().parent / "fixtures" / "scenarios" / SCENARIOS
    with path.open("rb") as fh:
        api_client.post(
            f"/orgs/{auth_user.org_id}/events",
            files={"file": ("e1b.jsonl", fh, "application/jsonl")},
        )
    run_pending_jobs(db_session, methodology, fake_redis)
    return api_client.get(f"/orgs/{auth_user.org_id}/incidents").json()[0]


def test_api_exposes_the_allowed_transitions(
    api_client, db_session, methodology, fake_redis, auth_user
):
    incident = _api_incident(api_client, db_session, methodology, fake_redis, auth_user)

    assert incident["transiciones"] == ["triaged", "closed"]
    advanced = api_client.patch(f"/incidents/{incident['id']}", json={"estado": "triaged"}).json()
    assert advanced["transiciones"] == ["contained", "closed"]


def test_api_rejects_an_invalid_transition_with_409(
    api_client, db_session, methodology, fake_redis, auth_user
):
    incident = _api_incident(api_client, db_session, methodology, fake_redis, auth_user)

    response = api_client.patch(f"/incidents/{incident['id']}", json={"estado": "recovering"})

    assert response.status_code == 409
    assert "puede pasar a: triaged, closed" in response.json()["detail"]
    assert api_client.get(f"/incidents/{incident['id']}").json()["estado"] == "open"


def test_api_requires_a_reason_to_close_and_keeps_it(
    api_client, db_session, methodology, fake_redis, auth_user
):
    incident = _api_incident(api_client, db_session, methodology, fake_redis, auth_user)

    sin_motivo = api_client.patch(f"/incidents/{incident['id']}", json={"estado": "closed"})
    assert sin_motivo.status_code == 409 and "motivo" in sin_motivo.json()["detail"]

    cerrado = api_client.patch(
        f"/incidents/{incident['id']}",
        json={"estado": "closed", "motivo": "Resuelto y verificado."},
    ).json()
    assert cerrado["estado"] == "closed" and cerrado["transiciones"] == []
    assert cerrado["motivo_cierre"] == "Resuelto y verificado."
    assert cerrado["timeline"][-1]["transicion"] == "open->closed"
