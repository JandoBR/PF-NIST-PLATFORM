import json
import shutil
from pathlib import Path

import pytest

from app.core import assessment_service as svc
from app.core import comparison, operations, refresh
from app.evaluation.schemas import Estado
from app.methodology.loader import load_methodology
from app.models.tables import Assessment, CriterionResultRow, EvidenceRow, PlanRow, Source


class _EchoAdjustingClient:
    """Fake de prueba: lee los IDs de evidencia del propio prompt y los re-referencia, en vez
    de adivinar UUIDs generados en la corrida (cada EvidenceInstance se crea con uno nuevo)."""

    def __init__(self, delta: float) -> None:
        self.delta = delta

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        payload = json.loads(user_prompt)
        evidencia_ids = [e["id"] for e in payload["evidencias"]]
        if not evidencia_ids:
            return None
        base = payload["base_score"]
        return {
            "criterion_id": payload["criterion"]["id"],
            "puntaje_base_recibido": base,
            "puntaje_propuesto": base + self.delta,
            "justificacion": f"ajuste de prueba citando {evidencia_ids[0]}",
            "evidencias_referenciadas": evidencia_ids,
            "confianza": 0.9,
        }


METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"
ANSIBLE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ansible"
SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


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


def test_run_assessment_applies_ai_adjustment_within_bounds(db_session, methodology, tmp_path):
    # Una base cifrada y otra no: PR-01 = 25 (parcial), un puntaje que la IA si puede matizar.
    (tmp_path / "main.tf").write_text(
        'resource "aws_db_instance" "a" {\n  storage_encrypted = true\n}\n'
        'resource "aws_db_instance" "b" {\n  storage_encrypted = false\n}\n'
    )
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Ajuste",
        scope="s",
        terraform_path=tmp_path,
        ai_client=_EchoAdjustingClient(delta=40),  # fuera del margen D=20: debe acotarse
        apply_ai_adjustment=True,
    )

    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    pr01 = results["CRI-PR-01"]

    assert pr01.base_score == 25  # el ajuste nunca toca base_score
    assert pr01.final_score == 30  # B=25, A acotado a 45 (25+20), S=0.75*25+0.25*45
    assert pr01.degradado is False
    assert "Ajuste contextual" in pr01.explanation


def test_ai_adjustment_never_raises_an_explicit_absence(db_session, methodology):
    """En el fixture gaps ningun recurso cifra: PR-01 = 0 (`no_implementado`). La IA propone
    subirlo y J2 lo impide."""

    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Ausencia",
        scope="s",
        terraform_path=FIXTURES / "gaps",
        ai_client=_EchoAdjustingClient(delta=40),
        apply_ai_adjustment=True,
    )
    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    pr01 = results["CRI-PR-01"]
    assert (pr01.estado, pr01.base_score, pr01.final_score) == (Estado.NO_IMPLEMENTADO, 0, 0)


def test_run_assessment_without_ai_adjust_flag_leaves_base_score_as_final(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Sin Ajuste",
        scope="s",
        terraform_path=FIXTURES / "gaps",
        ai_client=_EchoAdjustingClient(delta=40),
        apply_ai_adjustment=False,  # el cliente existe pero no se usa para ajustar
    )

    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    assert results["CRI-PR-01"].final_score == 0


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
    before_results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, before.id)}
    assert before_results["CRI-PR-01"].final_score == 0  # ningun recurso cifrado

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

    report = comparison.compare(db_session, methodology, before.id, after.id)

    pr01_diff = next(d for d in report.diffs if d.criterion_id == "CRI-PR-01")
    assert pr01_diff.score_antes == 0
    assert pr01_diff.score_despues == 100
    assert pr01_diff.cambio is True
    assert pr01_diff in report.cambios
    assert report.global_despues > report.global_antes


def test_compare_unknown_assessment_raises(db_session, methodology):
    with pytest.raises(svc.AssessmentNotFoundError):
        comparison.compare(db_session, methodology, "a", "b")


def test_generate_plans_persists_one_plan_per_finding(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Planes",
        scope="s",
        terraform_path=FIXTURES / "gaps",
    )

    rows = svc.generate_plans(db_session, methodology, assessment.id)

    assert {r.criterion_id for r in rows} == {
        r.criterion_id
        for r in svc.load_criterion_results(db_session, assessment.id)
        if r.final_score is not None and r.final_score < 75
    }
    plans = svc.load_plans(db_session, assessment.id)
    assert all(p.generado_por == "plantilla" for p in plans)  # sin ai_client: degrada a plantilla


def test_generate_plans_is_idempotent(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Planes 2",
        scope="s",
        terraform_path=FIXTURES / "gaps",
    )

    first = svc.generate_plans(db_session, methodology, assessment.id)
    second = svc.generate_plans(db_session, methodology, assessment.id)

    assert len(first) == len(second)
    assert len(svc.load_plans(db_session, assessment.id)) == len(second)  # no se duplican


def test_generate_plans_unknown_assessment_raises(db_session, methodology):
    with pytest.raises(svc.AssessmentNotFoundError):
        svc.generate_plans(db_session, methodology, "no-existe")


def test_assessment_is_not_published_as_completed_before_plans(
    monkeypatch, db_session, methodology
):
    visto = {}
    original = svc.generate_plans

    def espia(session, methodology, assessment_id, **kwargs):
        visto["estado"] = session.get(Assessment, assessment_id).estado
        return original(session, methodology, assessment_id, **kwargs)

    monkeypatch.setattr(svc, "generate_plans", espia)

    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Orden Planes",
        scope="entorno:produccion",
        terraform_path=FIXTURES / "gaps",
    )

    assert visto["estado"] == "en_progreso"
    assert assessment.estado == "completada"


def test_methodology_version_is_stamped_when_the_worker_runs(db_session, methodology):
    assessment = svc.create_pending_assessment(
        db_session,
        methodology,
        org_name="Empresa Version Tardia",
        scope="entorno:produccion",
    )
    assessment.methodology_version = "criterios=1,tipos=1,settings=1,csf=1"
    db_session.commit()

    svc.run_pending_assessment(
        db_session, methodology, assessment.id, terraform_path=FIXTURES / "gaps"
    )

    db_session.refresh(assessment)
    assert assessment.methodology_version == methodology.methodology_version


def test_enqueue_refresh_falls_back_to_full_run_when_methodology_changed(
    db_session, methodology, fake_redis
):
    org = "Empresa Refresh Metodologia"
    previous = svc.run_assessment(
        db_session,
        methodology,
        org_name=org,
        scope="entorno:produccion",
        terraform_path=FIXTURES / "gaps",
    )
    previous.methodology_version = "criterios=1,tipos=1,settings=1,csf=1"
    db_session.commit()

    _, job = refresh.enqueue_surveillance_refresh(db_session, methodology, fake_redis, previous.id)

    assert "selective_refresh" not in job.payload
    assert job.payload["terraform_path"]
    assert job.payload["ai_requested"] is False


def test_selective_refresh_refuses_a_different_methodology(db_session, methodology):
    org = "Empresa Refresh Guardia"
    previous = svc.run_assessment(
        db_session,
        methodology,
        org_name=org,
        scope="entorno:produccion",
        terraform_path=FIXTURES / "gaps",
    )
    previous.methodology_version = "criterios=1,tipos=1,settings=1,csf=1"
    db_session.commit()
    refreshed, _paths = svc.create_pending_reevaluation(db_session, methodology, previous.id)

    with pytest.raises(ValueError, match="misma metodologia"):
        refresh.run_surveillance_refresh(db_session, methodology, refreshed.id, previous.id)

    db_session.refresh(refreshed)
    assert refreshed.estado == "fallida"
    assert "misma metodologia" in refreshed.error


def test_surveillance_refresh_reuses_unaffected_and_recomputes_operational(db_session, methodology):
    """Refresco selectivo (docs/06 §6, FN-06): conserva lo no operativo (incluida la IA) y
    recalcula solo los criterios de vigilancia."""

    org = "Empresa Refresh Selectivo"
    previous = svc.run_assessment(
        db_session,
        methodology,
        org_name=org,
        scope="entorno:produccion",
        terraform_path=FIXTURES / "gaps",
    )

    # Simular lo que aporta la IA: un resultado documental/tecnico con texto propio y un plan
    # "generado_por IA". Un criterio NO de vigilancia no debe recomputarse.
    db_session.query(CriterionResultRow).filter_by(
        assessment_id=previous.id, criterion_id="CRI-PR-01"
    ).one().explanation = "SENTINEL-PR01"
    db_session.query(PlanRow).filter_by(
        assessment_id=previous.id, criterion_id="CRI-PR-01"
    ).one().generado_por = "ai:plan_v1"
    # Un criterio de vigilancia: su resultado SI debe recomputarse.
    db_session.query(CriterionResultRow).filter_by(
        assessment_id=previous.id, criterion_id="CRI-DE-02"
    ).one().explanation = "SENTINEL-DE02"
    db_session.commit()

    # Eventos nuevos: alimentan la evidencia operativa fresca.
    operations.ingest_events(db_session, methodology, org, SCENARIOS / "incidentes_demo.jsonl")

    refreshed, _paths = svc.create_pending_reevaluation(db_session, methodology, previous.id)
    refresh.run_surveillance_refresh(db_session, methodology, refreshed.id, previous.id)

    assert refreshed.estado == "completada"
    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, refreshed.id)}
    assert results["CRI-PR-01"].explanation == "SENTINEL-PR01"  # reusado
    assert results["CRI-DE-02"].explanation != "SENTINEL-DE02"  # recomputado

    plans = {p.criterion_id: p for p in svc.load_plans(db_session, refreshed.id)}
    assert plans["CRI-PR-01"].generado_por == "ai:plan_v1"  # plan con IA preservado

    # La evidencia operativa es la fresca del org (log.pattern de los eventos recien ingeridos).
    refreshed_evidence = db_session.query(EvidenceRow).filter_by(assessment_id=refreshed.id).all()
    assert any(row.type_id == "log.pattern" for row in refreshed_evidence)
    assert all(
        row.type_id in {"log.pattern", "log.window"}
        for row in refreshed_evidence
        if row.source_id == "surveillance:org"
    )
