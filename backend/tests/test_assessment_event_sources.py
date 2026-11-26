"""Consumo explicito de eventos por evaluacion (docs/08 §3, docs/09 §102).

Una evaluacion consume las ingestas de eventos que se le piden, no todo lo guardado del org+scope.
Los tres escenarios de la demo comparten los mismos sistemas emisores (`fuente`): solo la ingesta
(el archivo) separa un escenario de otro.
"""

from pathlib import Path

from app.core import assessment_service as svc
from app.core import operations
from app.models.tables import Event, EventIngest, Job
from tests.conftest import TEST_ORG_NAME, run_pending_jobs

SCOPE = "entorno:produccion"
DEMO = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo" / "events"
LOG_A = DEMO / "flujo-correcto-demo.jsonl"
LOG_B = DEMO / "incidentes-demo.jsonl"
LOG_C = DEMO / "respuesta-parcial-demo.jsonl"
TERRAFORM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"


def _ingest(db_session, methodology, org: str, path: Path):
    return operations.ingest_events(db_session, methodology, org, path)


def _patterns(evidence):
    return [e for e in evidence if e.type_id == "log.pattern"]


def _pattern_signature(evidence):
    return {
        (e.value["patron"], e.value["resultado"], e.value["conteo"]) for e in _patterns(evidence)
    }


def _upload_terraform(api_client, fixture: str, **form):
    path = TERRAFORM_FIXTURES / fixture / "main.tf"
    with path.open("rb") as fh:
        return api_client.post(
            "/assessments",
            data={"scope": SCOPE, **form},
            files={"terraform_files": ("main.tf", fh, "text/plain")},
        )


def test_a_scenario_is_isolated_even_when_the_emitting_systems_overlap(db_session, methodology):
    ingesta_a = _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    ingesta_b = _ingest(db_session, methodology, "Empresa Fuentes", LOG_B)
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_C)

    solo_b = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_ingest_ids=[ingesta_b.ingest_id],
    )
    _ingest(db_session, methodology, "Empresa Base", LOG_B)
    base = svc.run_assessment(db_session, methodology, org_name="Empresa Base", scope=SCOPE)
    todos = svc.run_assessment(db_session, methodology, org_name="Empresa Fuentes", scope=SCOPE)

    evidencia_b = svc.load_evidence(db_session, solo_b.id)
    assert _pattern_signature(evidencia_b) == _pattern_signature(
        svc.load_evidence(db_session, base.id)
    )
    assert _pattern_signature(evidencia_b) != _pattern_signature(
        svc.load_evidence(db_session, todos.id)
    )

    window = next(e for e in evidencia_b if e.type_id == "log.window")
    assert window.source_id == "siem-corp"
    assert solo_b.reproducibility["eventos"]["ingest_ids"] == [ingesta_b.ingest_id]
    assert solo_b.reproducibility["eventos"]["archivos"] == [LOG_B.name]
    assert ingesta_a.ingest_id != ingesta_b.ingest_id


def test_omitting_the_selection_keeps_using_every_ingest(db_session, methodology):
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_B)
    ingesta_c = _ingest(db_session, methodology, "Empresa Fuentes", LOG_C)

    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Fuentes", scope=SCOPE
    )
    patrones = {e.value["patron"] for e in _patterns(svc.load_evidence(db_session, assessment.id))}

    assert {"auth_failures_burst", "incident_declared", "containment_done"} <= patrones
    eventos = assessment.reproducibility["eventos"]
    assert eventos["todas"] is True
    assert eventos["conteo"] == 37
    assert len(eventos["ingest_ids"]) == 3
    assert ingesta_c.ingest_id in eventos["ingest_ids"]
    assert LOG_C.name in eventos["archivos"]


def test_empty_selection_consumes_no_events(db_session, methodology):
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_B)

    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_ingest_ids=[],
    )
    evidence = svc.load_evidence(db_session, assessment.id)

    assert not [e for e in evidence if e.type_id in {"log.window", "log.pattern"}]
    eventos = assessment.reproducibility["eventos"]
    assert eventos["todas"] is False
    assert eventos["ingest_ids"] == []
    assert eventos["archivos"] == []
    assert eventos["conteo"] == 0
    assert eventos["desde"] is None and eventos["hasta"] is None
    assert len(eventos["sha256"]) == 64


def test_reproducibility_records_the_ingest_range_and_a_stable_hash(db_session, methodology):
    ingesta_a = _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    ingesta_b = _ingest(db_session, methodology, "Empresa Fuentes", LOG_B)
    ingesta_c = _ingest(db_session, methodology, "Empresa Fuentes", LOG_C)

    solo_c = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_ingest_ids=[ingesta_c.ingest_id],
    )
    solo_b = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_ingest_ids=[ingesta_b.ingest_id],
    )

    eventos_c = solo_c.reproducibility["eventos"]
    eventos_b = solo_b.reproducibility["eventos"]
    assert eventos_c["ingest_ids"] == [ingesta_c.ingest_id]
    assert eventos_c["archivos"] == [LOG_C.name]
    assert eventos_c["conteo"] == 13
    assert eventos_c["desde"] == "2026-09-20T03:10:00+00:00"
    assert eventos_c["hasta"] == "2026-09-20T10:40:00+00:00"
    assert len(eventos_c["sha256"]) == 64
    assert eventos_c["sha256"] != eventos_b["sha256"]
    assert ingesta_a.ingest_id not in eventos_c["ingest_ids"]


def test_reingesting_the_same_file_keeps_the_first_ingest(db_session, methodology):
    first = _ingest(db_session, methodology, "Empresa Repetida", LOG_B)
    second = _ingest(db_session, methodology, "Empresa Repetida", LOG_B)

    assert (second.eventos_nuevos, second.eventos_existentes) == (0, 9)
    filas = db_session.query(EventIngest).order_by(EventIngest.ingerido_en).all()
    assert len(filas) == 2
    segunda = db_session.get(EventIngest, second.ingest_id)
    assert (segunda.eventos, segunda.eventos_leidos, segunda.eventos_existentes) == (0, 9, 9)
    assert {e.ingest_id for e in db_session.query(Event).all()} == {first.ingest_id}
    assert [i.ingest_id for i in svc.list_event_ingests(db_session, first.org_id, SCOPE)] == [
        first.ingest_id
    ]


def test_events_without_ingest_identity_stay_selectable_as_legacy(db_session, methodology):
    ingesta = _ingest(db_session, methodology, "Empresa Legado", LOG_B)
    for evento in db_session.query(Event).all():
        evento.ingest_id = None
    db_session.commit()

    resumen = svc.list_event_ingests(db_session, ingesta.org_id, SCOPE)
    assert [(i.ingest_id, i.archivo, i.eventos) for i in resumen] == [("legacy", None, 9)]

    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Legado",
        scope=SCOPE,
        event_ingest_ids=["legacy"],
    )
    patrones = {e.value["patron"] for e in _patterns(svc.load_evidence(db_session, assessment.id))}
    assert "incident_declared" in patrones
    eventos = assessment.reproducibility["eventos"]
    assert eventos["ingest_ids"] == ["legacy"]
    assert eventos["archivos"] == [None]
    assert eventos["conteo"] == 9


def test_patterns_are_detected_once_per_type_across_ingests(db_session, methodology):
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_C)

    assessment = svc.run_assessment(
        db_session, methodology, org_name="Empresa Fuentes", scope=SCOPE
    )
    patrones = [e.value["patron"] for e in _patterns(svc.load_evidence(db_session, assessment.id))]

    assert len(patrones) == len(set(patrones))
    assert patrones.count("auth_failures_burst") == 1


def test_event_ingests_endpoint_lists_file_count_and_range(
    api_client, db_session, methodology, auth_user
):
    ingesta_a = _ingest(db_session, methodology, TEST_ORG_NAME, LOG_A)
    ingesta_b = _ingest(db_session, methodology, TEST_ORG_NAME, LOG_B)

    response = api_client.get(f"/orgs/{auth_user.org_id}/event-ingests", params={"scope": SCOPE})

    assert response.status_code == 200
    by_id = {i["ingest_id"]: i for i in response.json()}
    assert set(by_id) == {ingesta_a.ingest_id, ingesta_b.ingest_id}
    assert by_id[ingesta_a.ingest_id]["archivo"] == LOG_A.name
    assert by_id[ingesta_a.ingest_id]["eventos"] == 15
    assert by_id[ingesta_a.ingest_id]["desde"].startswith("2026-09-20T03:10:00")
    assert by_id[ingesta_a.ingest_id]["ingerido_en"] is not None
    assert by_id[ingesta_a.ingest_id]["fuentes"] == [
        "edr-endpoints",
        "respaldo-bd",
        "siem-corp",
        "soar-respuesta",
    ]
    assert response.json()[0]["ingest_id"] == ingesta_b.ingest_id


def test_api_rejects_event_ingests_from_another_org(api_client):
    response = _upload_terraform(api_client, "good", event_ingest_ids='["legacy"]')

    assert response.status_code == 400


def test_api_selection_reaches_the_worker_and_the_evidence(
    api_client, db_session, methodology, fake_redis, auth_user
):
    _ingest(db_session, methodology, TEST_ORG_NAME, LOG_A)
    ingesta_b = _ingest(db_session, methodology, TEST_ORG_NAME, LOG_B)

    accepted = _upload_terraform(
        api_client, "good", event_ingest_ids=f'["{ingesta_b.ingest_id}"]'
    ).json()
    run_pending_jobs(db_session, methodology, fake_redis)

    evidence = api_client.get(f"/assessments/{accepted['assessment_id']}/evidence").json()
    patrones = [e["value"]["patron"] for e in evidence if e["type_id"] == "log.pattern"]
    assert "containment_done" not in patrones

    detail = api_client.get(f"/assessments/{accepted['assessment_id']}").json()
    assert detail["reproducibility"]["eventos"]["ingest_ids"] == [ingesta_b.ingest_id]
    assert detail["reproducibility"]["eventos"]["archivos"] == [LOG_B.name]


def test_reevaluation_inherits_an_explicit_ingest_selection(
    api_client, db_session, methodology, fake_redis, auth_user
):
    _ingest(db_session, methodology, TEST_ORG_NAME, LOG_A)
    ingesta_b = _ingest(db_session, methodology, TEST_ORG_NAME, LOG_B)
    accepted = _upload_terraform(
        api_client, "good", event_ingest_ids=f'["{ingesta_b.ingest_id}"]'
    ).json()
    run_pending_jobs(db_session, methodology, fake_redis)

    reeval = api_client.post(f"/assessments/{accepted['assessment_id']}/reevaluate")

    assert reeval.status_code == 202
    job = db_session.get(Job, reeval.json()["job_id"])
    assert job.payload["event_ingest_ids"] == [ingesta_b.ingest_id]


def test_auto_refresh_inherits_the_explicit_ingest_selection(db_session, methodology, fake_redis):
    from app.core import refresh

    _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    ingesta_b = _ingest(db_session, methodology, "Empresa Fuentes", LOG_B)
    previous = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_ingest_ids=[ingesta_b.ingest_id],
    )

    _, job = refresh.enqueue_surveillance_refresh(db_session, methodology, fake_redis, previous.id)

    assert job.payload["event_ingest_ids"] == [ingesta_b.ingest_id]


def test_auto_refresh_is_skipped_when_the_selection_excludes_the_new_ingest(
    db_session, methodology, fake_redis
):
    from app.core import refresh

    ingesta_a = _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Fuentes",
        scope=SCOPE,
        event_ingest_ids=[ingesta_a.ingest_id],
    )
    ingesta_b = _ingest(db_session, methodology, "Empresa Fuentes", LOG_B)
    kwargs = {"org_id": ingesta_a.org_id, "scope": SCOPE, "nuevos_patrones": 99}

    omitida = refresh.maybe_enqueue_maturity_refresh(
        db_session, methodology, fake_redis, ingest_id=ingesta_b.ingest_id, **kwargs
    )
    propia = refresh.maybe_enqueue_maturity_refresh(
        db_session, methodology, fake_redis, ingest_id=ingesta_a.ingest_id, **kwargs
    )

    assert omitida is None
    assert propia is not None


def test_clearing_the_operational_data_also_removes_the_ingests(db_session, methodology):
    ingesta = _ingest(db_session, methodology, "Empresa Limpia", LOG_B)

    operations.clear_operational_data(db_session, ingesta.org_id)

    assert db_session.query(EventIngest).count() == 0
    assert svc.list_event_ingests(db_session, ingesta.org_id, SCOPE) == []


def test_event_ingests_are_scoped_to_the_org(db_session, methodology):
    _ingest(db_session, methodology, "Empresa Fuentes", LOG_A)
    _ingest(db_session, methodology, "Empresa Otra", LOG_B)
    org_id = db_session.query(Event).first().org_id

    ingests = svc.list_event_ingests(db_session, org_id, SCOPE)

    assert len(ingests) == 1
    assert ingests[0].archivo == LOG_A.name
    assert svc.list_event_ingests(db_session, "otra-org", SCOPE) == []
