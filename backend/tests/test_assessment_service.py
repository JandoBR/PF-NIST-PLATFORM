import shutil
from pathlib import Path

import pytest

from app.core import assessment_service as svc
from app.evaluation.schemas import Estado
from app.methodology.loader import load_methodology
from app.models.tables import Assessment, Source

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"
ANSIBLE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ansible"


def _fix_rds_encryption(main_tf: Path) -> None:
    text = main_tf.read_text()
    main_tf.write_text(text.replace("storage_encrypted       = false", "storage_encrypted = true"))


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def test_run_assessment_persists_evidence_and_results(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Demo",
        scope="entorno:produccion",
        terraform_path=FIXTURES / "good",
    )

    assert assessment.estado == "completada"
    assert db_session.query(Source).filter_by(assessment_id=assessment.id).count() == 1

    results = svc.load_criterion_results(db_session, assessment.id)
    by_id = {r.criterion_id: r for r in results}
    assert by_id["CRI-PR-01"].estado == Estado.EVALUADO
    assert by_id["CRI-PR-01"].final_score == 100


def test_run_assessment_reuses_organization_by_name(db_session, methodology):
    first = svc.run_assessment(
        db_session, methodology, org_name="Empresa X", scope="s", terraform_path=FIXTURES / "good"
    )
    second = svc.run_assessment(
        db_session, methodology, org_name="Empresa X", scope="s", terraform_path=FIXTURES / "gaps"
    )

    assert first.org_id == second.org_id


def test_run_assessment_combines_terraform_and_ansible_evidence(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Mixta",
        scope="entorno:produccion",
        terraform_path=FIXTURES / "good",
        ansible_path=ANSIBLE_FIXTURES / "good",
    )

    assert {s.tipo for s in assessment.sources} == {"terraform", "ansible"}

    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    assert results["CRI-PR-04"].final_score == 100  # sshd endurecido via Ansible
    assert results["CRI-PR-06"].final_score == 100  # CloudTrail multirregion + rsyslog


def test_run_assessment_marks_failure_without_losing_the_row(db_session, methodology):
    missing = Path("/no/existe/main.tf")

    with pytest.raises(FileNotFoundError):
        svc.run_assessment(
            db_session,
            methodology,
            org_name="Empresa Rota",
            scope="s",
            terraform_path=missing,
        )

    failed = db_session.query(Assessment).filter_by(estado="fallida").one()
    assert failed.error is not None


def test_reevaluate_rereads_the_same_path_and_picks_up_fixes(db_session, methodology, tmp_path):
    workdir = tmp_path / "infra"
    shutil.copytree(FIXTURES / "gaps", workdir)

    before = svc.run_assessment(
        db_session, methodology, org_name="Empresa Mejora", scope="s", terraform_path=workdir
    )
    before_results = {
        r.criterion_id: r for r in svc.load_criterion_results(db_session, before.id)
    }
    assert before_results["CRI-PR-01"].final_score == 25  # cifrado deshabilitado

    main_tf = workdir / "main.tf"
    _fix_rds_encryption(main_tf)

    after = svc.reevaluate(db_session, methodology, before.id)
    after_results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, after.id)}

    assert after.id != before.id
    assert after_results["CRI-PR-01"].final_score == 100  # la correccion se refleja


def test_reevaluate_unknown_assessment_raises(db_session, methodology):
    with pytest.raises(svc.AssessmentNotFoundError):
        svc.reevaluate(db_session, methodology, "no-existe")


def test_compare_reports_per_criterion_and_global_change(db_session, methodology, tmp_path):
    workdir = tmp_path / "infra"
    shutil.copytree(FIXTURES / "gaps", workdir)

    before = svc.run_assessment(
        db_session, methodology, org_name="Empresa Compara", scope="s", terraform_path=workdir
    )
    main_tf = workdir / "main.tf"
    _fix_rds_encryption(main_tf)
    after = svc.reevaluate(db_session, methodology, before.id)

    report = svc.compare(db_session, methodology, before.id, after.id)

    pr01_diff = next(d for d in report.diffs if d.criterion_id == "CRI-PR-01")
    assert pr01_diff.score_antes == 25
    assert pr01_diff.score_despues == 100
    assert pr01_diff.cambio is True
    assert pr01_diff in report.cambios
    assert report.global_despues > report.global_antes


def test_compare_unknown_assessment_raises(db_session, methodology):
    with pytest.raises(svc.AssessmentNotFoundError):
        svc.compare(db_session, methodology, "a", "b")
