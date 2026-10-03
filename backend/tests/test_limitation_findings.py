"""OP-04: lo que el analisis no pudo resolver sale como hallazgo `limitacion`."""

import pytest

from app.core import assessment_service as svc
from app.recommendations.findings import derive_findings

DB_CON_VARIABLES = """
resource "aws_db_instance" "db" {
  storage_encrypted       = var.cifrado
  backup_retention_period = var.dias
  publicly_accessible     = false
}
"""


def _assess(db_session, methodology, tmp_path, hcl):
    archivo = tmp_path / "main.tf"
    archivo.write_text(hcl)
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Limitaciones",
        scope="entorno:produccion",
        terraform_path=archivo,
    )
    results = svc.load_criterion_results(db_session, assessment.id)
    evidence = svc.load_evidence(db_session, assessment.id)
    return results, evidence


@pytest.fixture
def con_variables(db_session, methodology, tmp_path):
    return _assess(db_session, methodology, tmp_path, DB_CON_VARIABLES)


def test_an_unresolved_expression_becomes_a_limitation_finding(methodology, con_variables):
    results, evidence = con_variables

    limitaciones = [
        f for f in derive_findings(methodology, results, evidence) if f.tipo == "limitacion"
    ]

    por_criterio = {(f.criterion_id, f.titulo) for f in limitaciones}
    assert ("CRI-PR-01", "aws_db_instance.db.storage_encrypted sin resolver") in por_criterio
    assert ("CRI-PR-02", "aws_db_instance.db.backup_retention_period sin resolver") in por_criterio
    # El recurso desconocido por esa expresion no se repite como "estado desconocido".
    assert not any("estado desconocido" in f.titulo for f in limitaciones)
    for f in limitaciones:
        assert f.severidad == "baja" and f.score is None
        assert "var." in f.detalle and "solo refleja lo que si se pudo resolver" in f.detalle
        assert len(f.evidence_ids) == 1


def test_a_missing_attribute_is_an_unknown_state_limitation(db_session, methodology, tmp_path):
    results, evidence = _assess(
        db_session,
        methodology,
        tmp_path,
        'resource "aws_db_instance" "db" {\n  backup_retention_period = 14\n}\n',
    )

    limitaciones = [
        f for f in derive_findings(methodology, results, evidence) if f.tipo == "limitacion"
    ]

    desconocidos = [f for f in limitaciones if f.titulo == "aws_db_instance.db: estado desconocido"]
    assert desconocidos and desconocidos[0].criterion_id == "CRI-PR-01"
    assert "no lo cuenta como cumplido ni como incumplido" in desconocidos[0].detalle


def test_limitations_need_the_evidence_and_never_become_plans(methodology, con_variables):
    results, evidence = con_variables

    sin_evidencia = derive_findings(methodology, results)  # asi lo llama la generacion de planes
    assert all(f.tipo == "brecha" for f in sin_evidencia)
    con_evidencia = derive_findings(methodology, results, evidence)
    assert {f.tipo for f in con_evidencia} >= {"limitacion"}


def test_resolved_expressions_leave_no_limitations(methodology, db_session, tmp_path):
    """Con los valores resueltos no hay nada que advertir."""

    resueltos = DB_CON_VARIABLES.replace("var.cifrado", "true").replace("var.dias", "14")
    results_a, evidence_a = _assess(db_session, methodology, tmp_path, resueltos)
    assert all(f.tipo != "limitacion" for f in derive_findings(methodology, results_a, evidence_a))


def test_a_clean_file_has_no_limitations(db_session, methodology, tmp_path):
    results, evidence = _assess(
        db_session,
        methodology,
        tmp_path,
        'resource "aws_db_instance" "db" {\n  storage_encrypted = true\n'
        "  backup_retention_period = 14\n  publicly_accessible = false\n}\n",
    )

    findings = derive_findings(methodology, results, evidence)
    assert [f for f in findings if f.tipo == "limitacion"] == []


def test_the_api_returns_limitations_among_the_findings(
    api_client, db_session, methodology, fake_redis, tmp_path
):
    from tests.conftest import run_pending_jobs

    archivo = tmp_path / "main.tf"
    archivo.write_text(DB_CON_VARIABLES)
    with archivo.open("rb") as fh:
        accepted = api_client.post(
            "/assessments",
            data={"scope": "entorno:produccion"},
            files={"terraform_files": ("main.tf", fh, "text/plain")},
        ).json()
    run_pending_jobs(db_session, methodology, fake_redis)

    findings = api_client.get(f"/assessments/{accepted['assessment_id']}/findings").json()

    assert any(f["tipo"] == "limitacion" and f["criterion_id"] == "CRI-PR-01" for f in findings)
