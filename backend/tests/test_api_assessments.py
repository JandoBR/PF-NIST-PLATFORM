from pathlib import Path

TERRAFORM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"


def _upload_terraform(api_client, fixture: str, **form):
    path = TERRAFORM_FIXTURES / fixture / "main.tf"
    with path.open("rb") as fh:
        return api_client.post(
            "/assessments",
            data={"org_name": "Empresa API Assessments", "scope": "entorno:produccion", **form},
            files={"terraform_files": ("main.tf", fh, "text/plain")},
        )


def test_create_assessment_requires_at_least_one_file(api_client):
    response = api_client.post(
        "/assessments", data={"org_name": "Empresa Vacia", "scope": "entorno:produccion"}
    )
    assert response.status_code == 422


def test_create_assessment_with_terraform_scores_criteria(api_client):
    response = _upload_terraform(api_client, "good")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "completada"
    assert body["org_nombre"] == "Empresa API Assessments"
    assert body["score_global"] is not None
    assert any(a["ref"] == "PR" for a in body["agregados_funcion"])
    # Solo Terraform, sin documentos: CRI-GV-01 (en el catalogo) queda evidencia_insuficiente,
    # asi que el Tier es "Partial" pero marcado provisional -- igual que en la CLI.
    assert body["tier"]["tier"] == 1
    assert body["tier"]["provisional"] is True


def test_get_assessment_and_sub_resources(api_client):
    created = _upload_terraform(api_client, "gaps").json()
    assessment_id = created["id"]

    detail = api_client.get(f"/assessments/{assessment_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == assessment_id

    criteria = api_client.get(f"/assessments/{assessment_id}/criteria").json()
    by_id = {c["criterion_id"]: c for c in criteria}
    assert by_id["CRI-PR-01"]["final_score"] == 25  # cifrado deshabilitado en el fixture gaps

    evidence = api_client.get(f"/assessments/{assessment_id}/evidence").json()
    assert len(evidence) > 0
    assert all("type_id" in e for e in evidence)

    findings = api_client.get(f"/assessments/{assessment_id}/findings").json()
    assert any(f["criterion_id"] == "CRI-PR-01" for f in findings)


def test_list_assessments_includes_created_ones(api_client):
    _upload_terraform(api_client, "good")
    response = api_client.get("/assessments")
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_get_unknown_assessment_is_404(api_client):
    for path in ["", "/criteria", "/evidence", "/findings", "/plans"]:
        response = api_client.get(f"/assessments/no-existe{path}")
        assert response.status_code == 404, path


def test_generate_and_list_plans(api_client):
    created = _upload_terraform(api_client, "gaps").json()
    assessment_id = created["id"]

    generated = api_client.post(f"/assessments/{assessment_id}/plans")
    assert generated.status_code == 200
    assert len(generated.json()) > 0
    assert all(p["generado_por"] == "plantilla" for p in generated.json())

    fetched = api_client.get(f"/assessments/{assessment_id}/plans")
    assert len(fetched.json()) == len(generated.json())


def test_reevaluate_picks_up_a_fix_to_the_uploaded_file(api_client):
    before = _upload_terraform(api_client, "gaps").json()
    assert before["score_global"] is not None

    # La subida se guarda en un directorio persistente (app/api/routes_assessments.py,
    # UPLOADS_DIR), no en uno temporal: `reevaluate` debe poder re-leerlo mas tarde.
    before_criteria = api_client.get(f"/assessments/{before['id']}/criteria").json()
    pr01_before = next(c for c in before_criteria if c["criterion_id"] == "CRI-PR-01")
    assert pr01_before["final_score"] == 25  # cifrado deshabilitado en el fixture gaps

    reeval = api_client.post(f"/assessments/{before['id']}/reevaluate")
    assert reeval.status_code == 200
    assert reeval.json()["id"] != before["id"]
    # Sin editar el archivo subido, la reevaluacion debe dar el mismo resultado (misma fuente).
    assert reeval.json()["score_global"] == before["score_global"]

    compare = api_client.get(f"/assessments/{before['id']}/compare/{reeval.json()['id']}")
    assert compare.status_code == 200
    assert compare.json()["assessment_id_a"] == before["id"]
    assert compare.json()["diffs"]  # el mismo criterio aparece en ambos lados, sin cambio


def test_reevaluate_after_editing_the_persisted_upload_shows_the_fix(api_client, db_session):
    """Prueba directa del bug real: un directorio temporal autolimpiado rompia esto porque el
    archivo subido ya no existia para la segunda corrida (ver UPLOADS_DIR en
    app/api/routes_assessments.py)."""

    from app.models.tables import Source

    before = _upload_terraform(api_client, "gaps").json()

    source = db_session.query(Source).filter_by(assessment_id=before["id"]).one()
    uploaded_main_tf = Path(source.ruta) / "main.tf"
    assert uploaded_main_tf.exists()  # el archivo sigue ahi: no se borro al terminar el request

    text = uploaded_main_tf.read_text()
    fixed = text.replace("storage_encrypted       = false", "storage_encrypted = true")
    uploaded_main_tf.write_text(fixed)

    reeval = api_client.post(f"/assessments/{before['id']}/reevaluate").json()
    after = api_client.get(f"/assessments/{reeval['id']}/criteria").json()
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
