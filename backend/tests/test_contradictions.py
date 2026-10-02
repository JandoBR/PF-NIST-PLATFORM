"""OP-04 / TS-03: contradicciones tecnico-vs-documental y documento-vs-documento (docs/02 §5)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ai.client import FakeAIClient
from app.core import assessment_service as svc
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import load_methodology
from app.recommendations.contradictions import detect_contradictions
from app.recommendations.findings import derive_findings
from app.recommendations.plans import generate_plans
from app.schemas.evidence import EvidenceInstance, Locator, Modality

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCOPE = "entorno:produccion"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def _backup(retencion: int, ref: str = "aws_db_instance.db", scope: str = SCOPE):
    return EvidenceInstance(
        type_id="tf.backup.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref=ref,
        scope=scope,
        value={"retencion_dias": retencion, "habilitado": retencion > 0, "ventana": None},
        source_id="t",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _claim(tipo: str, contenido: dict, doc: str = "politica", scope: str = SCOPE, **extra):
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref=f"doc:{doc}",
        scope=scope,
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido,
            "encontrado": True,
            "confianza": 0.9,
        },
        source_id="t",
        locator=Locator(file=f"{doc}.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
        **extra,
    )


def _only(findings, criterion_id):
    return [f for f in findings if f.criterion_id == criterion_id]


# -- tecnico vs documental --------------------------------------------------------------------


def test_retention_below_policy_is_a_contradiction_citing_both_sides():
    tf, doc = _backup(7), _claim("backup_policy", {"respaldo": True, "retencion": "30 dias"})
    findings = detect_contradictions([tf, doc])

    assert len(findings) == 1
    f = findings[0]
    assert (f.tipo, f.criterion_id, f.severidad, f.score) == (
        "contradiccion",
        "CRI-PR-02",
        "media",
        None,
    )
    assert set(f.evidence_ids) == {tf.id, doc.id}
    assert "30 dias" in f.detalle and "7" in f.detalle and "D7" in f.detalle


def test_policy_declaring_backups_while_terraform_disables_them_is_high_severity():
    tf, doc = _backup(0), _claim("backup_policy", {"respaldo": True, "retencion": "7 dias"})
    (f,) = detect_contradictions([tf, doc])
    assert f.severidad == "alta"
    assert set(f.evidence_ids) == {tf.id, doc.id}


def test_consistent_sources_do_not_contradict():
    evidence = [_backup(14), _claim("backup_policy", {"respaldo": True, "retencion": "7 dias"})]
    assert detect_contradictions(evidence) == []


def test_policy_with_nothing_technical_to_compare_is_not_a_contradiction():
    # docs/02 §5: "Terraform no aporta nada" -> se acepta la evidencia documental
    solo_politica = [_claim("backup_policy", {"respaldo": True, "retencion": "30 dias"})]
    assert detect_contradictions(solo_politica) == []


def test_different_scopes_are_never_compared():
    evidence = [
        _backup(7, scope="entorno:staging"),
        _claim("backup_policy", {"respaldo": True, "retencion": "30 dias"}, scope=SCOPE),
    ]
    assert detect_contradictions(evidence) == []


def test_low_confidence_claims_do_not_create_contradictions():
    evidence = [
        _backup(7),
        _claim(
            "backup_policy",
            {"respaldo": True, "retencion": "30 dias"},
            limitations="confianza baja",
        ),
    ]
    assert detect_contradictions(evidence) == []


def test_unknown_retention_is_a_limitation_not_a_contradiction():
    tf = _backup(7)
    tf.value["retencion_dias"] = None
    assert detect_contradictions([tf, _claim("backup_policy", {"retencion": "30 dias"})]) == []


def test_several_resources_produce_a_single_finding():
    evidence = [
        _backup(1, "aws_db_instance.a"),
        _backup(2, "aws_db_instance.b"),
        _claim("backup_policy", {"respaldo": True, "retencion": "30 dias"}),
    ]
    findings = detect_contradictions(evidence)
    assert len(findings) == 1  # "hallazgo registrado una sola vez" (docs/07)
    assert "aws_db_instance.a" in findings[0].detalle and "aws_db_instance.b" in findings[0].detalle


# -- documento vs documento -------------------------------------------------------------------


def test_two_documents_with_different_retention_contradict_each_other():
    a = _claim("backup_policy", {"retencion": "7 dias"}, doc="politica")
    b = _claim("backup_policy", {"retencion": "30 dias"}, doc="manual")
    (f,) = detect_contradictions([a, b])
    assert (f.criterion_id, f.tipo) == ("CRI-PR-02", "contradiccion")
    assert set(f.evidence_ids) == {a.id, b.id}


def test_same_document_repeating_a_value_or_agreeing_documents_do_not_contradict():
    same_doc = [
        _claim("backup_policy", {"retencion": "7 dias"}, doc="politica"),
        _claim("backup_policy", {"retencion": "30 dias"}, doc="politica"),
    ]
    agree = [
        _claim("backup_policy", {"retencion": "7 dias"}, doc="politica"),
        _claim("backup_policy", {"retencion": "7 d"}, doc="manual"),
    ]
    assert detect_contradictions(same_doc) == []
    assert detect_contradictions(agree) == []


def test_review_frequency_disagreement_is_reported_on_gv01():
    a = _claim("policy_review", {"frecuencia": "anual"}, doc="politica")
    b = _claim("policy_review", {"frecuencia": "Trimestral"}, doc="manual")
    (f,) = detect_contradictions([a, b])
    assert f.criterion_id == "CRI-GV-01"
    assert "anual" in f.detalle and "trimestral" in f.detalle


# -- integracion con hallazgos y planes -------------------------------------------------------


def _result(score: float) -> CriterionResult:
    return CriterionResult(
        criterion_id="CRI-PR-02",
        criterion_version=1,
        estado=Estado.EVALUADO,
        base_score=score,
        final_score=score,
        explanation="x",
    )


def test_contradictions_appear_only_when_evidence_is_given(methodology):
    evidence = [_backup(7), _claim("backup_policy", {"retencion": "30 dias"})]
    sin = derive_findings(methodology, [_result(50)])
    con = derive_findings(methodology, [_result(50)], evidence)
    assert [f.tipo for f in sin] == ["brecha"]
    assert sorted(f.tipo for f in con) == ["brecha", "contradiccion"]


def test_contradiction_never_changes_a_score_nor_creates_a_plan(methodology):
    results = [_result(50)]
    plans = generate_plans(methodology, results)
    assert [p.criterion_id for p in plans] == ["CRI-PR-02"]  # solo la brecha
    assert results[0].final_score == 50  # no se penaliza doble


# -- E2E: Terraform real + politica extraida --------------------------------------------------


def test_end_to_end_policy_says_backups_but_terraform_disables_them(db_session, methodology):
    fake = FakeAIClient(
        {
            "Direccion General": {
                "afirmaciones": [
                    {
                        "tipo": "backup_policy",
                        "encontrado": True,
                        "contenido": {"respaldo": True, "retencion": "7 dias"},
                        "cita": {"fragmento": "aprobada por la Direccion General"},
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Contradiccion",
        scope=SCOPE,
        terraform_path=FIXTURES / "terraform" / "gaps",
        documents_path=FIXTURES / "documents" / "politica-seguridad.md",
        ai_client=fake,
    )
    results = svc.load_criterion_results(db_session, assessment.id)
    evidence = svc.load_evidence(db_session, assessment.id)
    findings = derive_findings(methodology, results, evidence)

    (contradiccion,) = [f for f in findings if f.tipo == "contradiccion"]
    assert contradiccion.criterion_id == "CRI-PR-02" and contradiccion.severidad == "alta"
    by_id = {e.id: e for e in evidence}
    lados = {by_id[i].type_id for i in contradiccion.evidence_ids}
    assert lados == {"tf.backup.config", "doc.claim"}
    # prevalece lo tecnico: el criterio puntua con retencion 0, no con la politica
    pr02 = next(r for r in results if r.criterion_id == "CRI-PR-02")
    assert pr02.final_score == 25
