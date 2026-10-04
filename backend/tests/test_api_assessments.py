from pathlib import Path

from app.adapters.terraform.adapter import ADAPTER_VERSION as TERRAFORM_ADAPTER_VERSION
from tests.conftest import run_pending_jobs

TERRAFORM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"


def _upload_terraform(api_client, fixture: str, **form):
    path = TERRAFORM_FIXTURES / fixture / "main.tf"
    with path.open("rb") as fh:
        return api_client.post(
            "/assessments",
            data={"org_name": "Empresa API Assessments", "scope": "entorno:produccion", **form},
            files={"terraform_files": ("main.tf", fh, "text/plain")},
        )


def _create_and_complete(api_client, db_session, methodology, fake_redis, fixture: str, **form):
    """Sube Terraform, confirma el 202, y corre el job encolado como lo haria `worker-core` --
    devuelve el `AssessmentDetail` ya completo via `GET /assessments/{id}`."""

    accepted = _upload_terraform(api_client, fixture, **form).json()
    run_pending_jobs(db_session, methodology, fake_redis)
    return api_client.get(f"/assessments/{accepted['assessment_id']}").json()


def test_create_assessment_requires_at_least_one_file(api_client):
    response = api_client.post(
        "/assessments", data={"org_name": "Empresa Vacia", "scope": "entorno:produccion"}
    )
    assert response.status_code == 422


def test_invalid_context_is_422_and_creates_nothing(api_client, db_session):
    """Antes un `context` que no era JSON daba 500 despues de crear la evaluacion, que quedaba
    `pendiente` para siempre y sin job."""

    from app.models.tables import Assessment

    for context in ("{no es json", "[1, 2]"):
        response = _upload_terraform(api_client, "good", context=context)
        assert response.status_code == 422
    assert db_session.query(Assessment).count() == 0


def test_upload_rejects_disallowed_extension(api_client):
    response = api_client.post(
        "/assessments",
        data={"scope": "entorno:produccion"},
        files={"terraform_files": ("payload.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 422


def test_create_assessment_is_accepted_and_queued(api_client):
    response = _upload_terraform(api_client, "good")

    assert response.status_code == 202
    body = response.json()
    assert body["org_nombre"] == "Empresa API Assessments"
    assert body["job_id"]

    job = api_client.get(f"/jobs/{body['job_id']}").json()
    assert job["estado"] == "pendiente"
    assert job["assessment_id"] == body["assessment_id"]

    pending = api_client.get(f"/assessments/{body['assessment_id']}").json()
    assert pending["estado"] == "pendiente"
    assert pending["score_global"] is None


def test_worker_completes_the_job_and_the_assessment(
    api_client, db_session, methodology, fake_redis
):
    accepted = _upload_terraform(api_client, "good").json()

    run_pending_jobs(db_session, methodology, fake_redis)

    job = api_client.get(f"/jobs/{accepted['job_id']}").json()
    assert job["estado"] == "completado"

    body = api_client.get(f"/assessments/{accepted['assessment_id']}").json()
    assert body["estado"] == "completada"
    assert body["score_global"] is not None
    assert any(a["ref"] == "PR" for a in body["agregados_funcion"])
    # Solo Terraform, sin documentos: ningun indicador de Tier 2 (GV-01, GV-02, ID-03) tiene
    # evidencia para puntuar, asi que el Tier es "no estimable" (T3), no "Partial".
    assert body["tier"]["tier"] is None
    assert body["tier"]["estimable"] is False


def test_get_assessment_and_sub_resources(api_client, db_session, methodology, fake_redis):
    created = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    assessment_id = created["id"]

    detail = api_client.get(f"/assessments/{assessment_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == assessment_id

    criteria = api_client.get(f"/assessments/{assessment_id}/criteria").json()
    by_id = {c["criterion_id"]: c for c in criteria}
    assert by_id["CRI-PR-01"]["final_score"] == 0  # ningun recurso cifrado en el fixture gaps

    evidence = api_client.get(f"/assessments/{assessment_id}/evidence").json()
    assert len(evidence) > 0
    assert all("type_id" in e for e in evidence)

    findings = api_client.get(f"/assessments/{assessment_id}/findings").json()
    assert any(f["criterion_id"] == "CRI-PR-01" for f in findings)


def test_list_assessments_includes_created_ones(api_client, db_session, methodology, fake_redis):
    _create_and_complete(api_client, db_session, methodology, fake_redis, "good")
    response = api_client.get("/assessments")
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_get_unknown_assessment_is_404(api_client):
    for path in ["", "/criteria", "/evidence", "/findings", "/plans"]:
        response = api_client.get(f"/assessments/no-existe{path}")
        assert response.status_code == 404, path


def test_completed_assessment_already_has_template_plans(
    api_client, db_session, methodology, fake_redis
):
    """Los planes (plantilla) se generan solos al completar: el usuario no los pide.

    Ver docs/11 UI-02.
    """

    created = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")

    plans = api_client.get(f"/assessments/{created['id']}/plans").json()
    assert len(plans) > 0
    assert all(p["generado_por"] == "plantilla" for p in plans)


def test_generate_and_list_plans(api_client, db_session, methodology, fake_redis):
    created = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    assessment_id = created["id"]

    generated = api_client.post(f"/assessments/{assessment_id}/plans")
    assert generated.status_code == 200
    assert len(generated.json()) > 0
    assert all(p["generado_por"] == "plantilla" for p in generated.json())

    fetched = api_client.get(f"/assessments/{assessment_id}/plans")
    assert len(fetched.json()) == len(generated.json())


def test_plan_follow_up_state_is_persisted(api_client, db_session, methodology, fake_redis):
    """El estado de seguimiento del plan se guarda y NO toca el puntaje (docs/11 UI-08)."""

    created = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    assessment_id = created["id"]
    plans = api_client.get(f"/assessments/{assessment_id}/plans").json()
    plan_id = plans[0]["id"]
    assert plans[0]["estado"] == "pendiente"

    before_score = api_client.get(f"/assessments/{assessment_id}").json()["score_global"]

    response = api_client.patch(
        f"/assessments/{assessment_id}/plans/{plan_id}", json={"estado": "en_progreso"}
    )
    assert response.status_code == 200
    assert response.json()["estado"] == "en_progreso"

    updated = api_client.get(f"/assessments/{assessment_id}/plans").json()
    assert next(p for p in updated if p["id"] == plan_id)["estado"] == "en_progreso"
    # El score no cambia: el seguimiento no es evidencia.
    assert api_client.get(f"/assessments/{assessment_id}").json()["score_global"] == before_score


def test_plan_follow_up_invalid_state_is_422(api_client, db_session, methodology, fake_redis):
    created = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    plan_id = api_client.get(f"/assessments/{created['id']}/plans").json()[0]["id"]

    response = api_client.patch(
        f"/assessments/{created['id']}/plans/{plan_id}", json={"estado": "inventado"}
    )
    assert response.status_code == 422


def test_reevaluate_picks_up_a_fix_to_the_uploaded_file(
    api_client, db_session, methodology, fake_redis
):
    before = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    assert before["score_global"] is not None

    # La subida se guarda en un directorio persistente (app/api/routes_assessments.py,
    # UPLOADS_DIR), no en uno temporal: el job de reevaluacion debe poder re-leerlo.
    before_criteria = api_client.get(f"/assessments/{before['id']}/criteria").json()
    pr01_before = next(c for c in before_criteria if c["criterion_id"] == "CRI-PR-01")
    assert pr01_before["final_score"] == 0  # ningun recurso cifrado en el fixture gaps

    reeval_accepted = api_client.post(f"/assessments/{before['id']}/reevaluate")
    assert reeval_accepted.status_code == 202
    assert reeval_accepted.json()["assessment_id"] != before["id"]

    run_pending_jobs(db_session, methodology, fake_redis)
    reeval = api_client.get(f"/assessments/{reeval_accepted.json()['assessment_id']}").json()
    # Sin editar el archivo subido, la reevaluacion debe dar el mismo resultado (misma fuente).
    assert reeval["score_global"] == before["score_global"]

    compare = api_client.get(f"/assessments/{before['id']}/compare/{reeval['id']}")
    assert compare.status_code == 200
    assert compare.json()["assessment_id_a"] == before["id"]
    assert compare.json()["diffs"]  # el mismo criterio aparece en ambos lados, sin cambio


def test_reevaluate_inherits_plan_follow_up_state(api_client, db_session, methodology, fake_redis):
    """Una reevaluacion hereda el seguimiento desde la evaluacion anterior (docs/05 §4.4)."""

    before = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    target = api_client.get(f"/assessments/{before['id']}/plans").json()[0]
    api_client.patch(
        f"/assessments/{before['id']}/plans/{target['id']}", json={"estado": "en_progreso"}
    )

    reeval = api_client.post(f"/assessments/{before['id']}/reevaluate").json()
    run_pending_jobs(db_session, methodology, fake_redis)

    new_plans = api_client.get(f"/assessments/{reeval['assessment_id']}/plans").json()
    inherited = next(p for p in new_plans if p["criterion_id"] == target["criterion_id"])
    assert inherited["estado"] == "en_progreso"


def test_new_assessment_inherits_follow_up_from_same_org_scope(
    api_client, db_session, methodology, fake_redis
):
    """Volver a evaluar el mismo org+scope hereda el seguimiento sin usar Reevaluar.

    Ver docs/05 §4.4.
    """

    first = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    target = api_client.get(f"/assessments/{first['id']}/plans").json()[0]
    api_client.patch(f"/assessments/{first['id']}/plans/{target['id']}", json={"estado": "hecho"})

    second = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    assert second["id"] != first["id"]
    new_plans = api_client.get(f"/assessments/{second['id']}/plans").json()
    inherited = next(p for p in new_plans if p["criterion_id"] == target["criterion_id"])
    assert inherited["estado"] == "hecho"


def test_reevaluate_after_editing_the_persisted_upload_shows_the_fix(
    api_client, db_session, methodology, fake_redis
):
    """Prueba directa del bug real: un directorio temporal autolimpiado rompia esto porque el
    archivo subido ya no existia para la segunda corrida (ver UPLOADS_DIR en
    app/api/routes_assessments.py)."""

    from app.models.tables import Source

    before = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")

    source = db_session.query(Source).filter_by(assessment_id=before["id"]).one()
    uploaded_main_tf = Path(source.ruta) / "main.tf"
    assert uploaded_main_tf.exists()  # el archivo sigue ahi: no se borro al terminar el request

    text = uploaded_main_tf.read_text()
    fixed = text.replace("storage_encrypted       = false", "storage_encrypted = true")
    uploaded_main_tf.write_text(fixed)

    reeval_accepted = api_client.post(f"/assessments/{before['id']}/reevaluate").json()
    run_pending_jobs(db_session, methodology, fake_redis)
    after = api_client.get(f"/assessments/{reeval_accepted['assessment_id']}/criteria").json()
    criteria = {c["criterion_id"]: c for c in after}

    assert criteria["CRI-PR-01"]["final_score"] == 100  # la correccion se refleja


def test_reevaluate_unknown_assessment_is_404(api_client):
    response = api_client.post("/assessments/no-existe/reevaluate")
    assert response.status_code == 404


def test_compare_unknown_assessment_is_404(api_client):
    response = api_client.get("/assessments/no-existe/compare/also-no-existe")
    assert response.status_code == 404


def test_live_ai_guard_blocks_ai_adjust_with_a_real_key(api_client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real-for-test")
    response = _upload_terraform(api_client, "good", ai_adjust="true")
    assert response.status_code == 409


def test_detail_exposes_reproducibility(api_client, db_session, methodology, fake_redis):
    detail = _create_and_complete(api_client, db_session, methodology, fake_redis, "good")
    info = detail["reproducibility"]
    assert info["adapters"]["terraform"]["adapter"] == TERRAFORM_ADAPTER_VERSION
    assert info["ai"] is None
