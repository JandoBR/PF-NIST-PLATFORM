"""AMP-02: informe ejecutivo y comparacion en PDF."""

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from tests.test_api_assessments import _create_and_complete, _upload_terraform

FIXTURES_DOCS = Path(__file__).resolve().parent / "fixtures" / "documents"


def _text(response) -> str:
    reader = PdfReader(BytesIO(response.content))
    return "\n".join(page.extract_text() for page in reader.pages)


def _norm(text: str) -> str:
    return " ".join(text.split())


def test_executive_report_is_a_pdf_with_the_assessment_results(
    api_client, db_session, methodology, fake_redis
):
    detail = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")

    response = api_client.get(f"/assessments/{detail['id']}/report.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    text = _norm(_text(response))
    assert "Informe ejecutivo de madurez" in text
    assert "Empresa API Assessments" in text
    assert f"{detail['score_global']:g}" in text
    assert "CRI-PR-01" in text  # el cifrado deshabilitado es una brecha
    assert "Gobernar" in text and "Recuperar" in text
    assert detail["methodology_version"] in text.replace(" ", "")


def test_executive_report_matches_the_api_numbers(api_client, db_session, methodology, fake_redis):
    detail = _create_and_complete(api_client, db_session, methodology, fake_redis, "good")
    text = _norm(_text(api_client.get(f"/assessments/{detail['id']}/report.pdf")))
    for agg in detail["agregados_funcion"]:
        if agg["score"] is not None:
            assert f"{agg['ref']} - " in text
    assert f"Nivel {detail['tier']['tier']}" in text or "No estimable" in text


def test_comparison_report_lists_both_assessments(api_client, db_session, methodology, fake_redis):
    before = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    after = _create_and_complete(api_client, db_session, methodology, fake_redis, "good")

    response = api_client.get(f"/assessments/{before['id']}/compare/{after['id']}/report.pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    text = _norm(_text(response))
    assert "Comparacion de evaluaciones" in text
    assert "Criterios que cambiaron" in text
    assert "CRI-PR-01" in text  # cifrado: 25 -> mejora en "good"
    assert f"{before['score_global']:g}" in text and f"{after['score_global']:g}" in text


def test_comparison_report_says_what_changed_and_why(
    api_client, db_session, methodology, fake_redis
):
    """Lo mismo que la pantalla Comparar (docs/09 §67): cobertura, funciones, direccion de cada
    cambio, hallazgos y la explicacion de antes y de despues."""

    before = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    after = _create_and_complete(api_client, db_session, methodology, fake_redis, "good")
    text = _norm(
        _text(api_client.get(f"/assessments/{before['id']}/compare/{after['id']}/report.pdf"))
    )

    assert "Cobertura de evidencia" in text
    assert "Cambio por funcion" in text and "PR - " in text
    assert "Mejoro" in text and "Ahora se evalua" in text  # PR-06 no tenia evidencia en gaps
    assert "Hallazgos - ya no aparecen: " in text
    assert "Por que cambio cada criterio" in text
    assert "Antes: Puertos administrativos (22/3389) expuestos a Internet" in text
    assert "Despues: Ningun security group expone puertos administrativos" in text


def test_report_of_an_unfinished_assessment_is_409(api_client):
    accepted = _upload_terraform(api_client, "good").json()  # encolado, sin correr el job

    response = api_client.get(f"/assessments/{accepted['assessment_id']}/report.pdf")

    assert response.status_code == 409


def test_report_of_an_unknown_assessment_is_404(api_client):
    assert api_client.get("/assessments/no-existe/report.pdf").status_code == 404
    assert api_client.get("/assessments/no-existe/compare/tampoco/report.pdf").status_code == 404


def test_report_requires_a_session(anon_client):
    assert anon_client.get("/assessments/x/report.pdf").status_code == 401
    assert anon_client.get("/assessments/x/compare/y/report.pdf").status_code == 401


def test_report_of_another_organization_is_404(api_client, db_session, methodology, fake_redis):
    from app.api.app import app
    from app.api.deps import get_current_user
    from app.core.auth import hash_password
    from app.models.tables import Organization, User

    detail = _create_and_complete(api_client, db_session, methodology, fake_redis, "good")
    otra = Organization(nombre="Otra Organizacion")
    db_session.add(otra)
    db_session.flush()
    salt, digest = hash_password("x")
    intruso = User(
        org_id=otra.id, username="intruso", password_salt=salt, password_hash=digest, role="client"
    )
    db_session.add(intruso)
    db_session.flush()
    app.dependency_overrides[get_current_user] = lambda: intruso

    assert api_client.get(f"/assessments/{detail['id']}/report.pdf").status_code == 404
    other = f"/assessments/{detail['id']}/compare/{detail['id']}/report.pdf"
    assert api_client.get(other).status_code == 404


def test_executive_report_lists_open_plans_and_skips_done_ones(
    api_client, db_session, methodology, fake_redis
):
    detail = _create_and_complete(api_client, db_session, methodology, fake_redis, "gaps")
    plans = api_client.post(f"/assessments/{detail['id']}/plans").json()
    hecho = next(p for p in plans if p["criterion_id"] == "CRI-PR-05")
    api_client.patch(f"/assessments/{detail['id']}/plans/{hecho['id']}", json={"estado": "hecho"})

    text = _norm(_text(api_client.get(f"/assessments/{detail['id']}/report.pdf")))

    plan_section = text.split("Plan de accion recomendado")[1].split("Resultados por criterio")[0]
    assert "CRI-PR-01" in plan_section  # abierto
    assert "CRI-PR-05" not in plan_section  # ya hecho


def test_executive_report_lists_the_limitations(
    api_client, db_session, methodology, fake_redis, tmp_path
):
    archivo = tmp_path / "main.tf"
    archivo.write_text('resource "aws_db_instance" "db" {\n  storage_encrypted = var.cifrado\n}\n')
    with archivo.open("rb") as fh:
        accepted = api_client.post(
            "/assessments",
            data={"scope": "entorno:produccion"},
            files={"terraform_files": ("main.tf", fh, "text/plain")},
        ).json()
    from tests.conftest import run_pending_jobs

    run_pending_jobs(db_session, methodology, fake_redis)

    text = _norm(_text(api_client.get(f"/assessments/{accepted['assessment_id']}/report.pdf")))

    assert "Limitaciones del analisis" in text
    assert "storage_encrypted sin resolver" in text


def test_executive_report_lists_the_analyzed_documents(
    api_client, db_session, methodology, fake_redis
):
    from app.ai.client import FakeAIClient
    from app.core import assessment_service as svc

    doc = FIXTURES_DOCS / "politica-seguridad.md"
    cliente = FakeAIClient({"aprobada por la Direccion General": {"afirmaciones": []}})
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa API Assessments",
        scope="entorno:produccion",
        documents_path=doc,
        ai_client=cliente,
    )

    text = _norm(_text(api_client.get(f"/assessments/{assessment.id}/report.pdf")))

    assert "Documentos analizados" in text and "politica-seguridad.md" in text
