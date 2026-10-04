"""OP-04 / TS-03: contradicciones tecnico-vs-documental y documento-vs-documento (docs/02 §5)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.ai.client import FakeAIClient
from app.core import assessment_service as svc
from app.evaluation import engine
from app.evaluation.contradictions import Contradiction, cap_contradicted
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


# -- efecto en el puntaje: la afirmacion contradicha no cuenta ----------------------------


def _encryption(estado: str = "enabled"):
    return EvidenceInstance(
        type_id="tf.encryption.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref="aws_db_instance.db",
        scope=SCOPE,
        value={"estado": estado, "mecanismo": None, "llave": None},
        source_id="t",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _score(methodology, evidence, criterion_id):
    results = engine.evaluate_all(methodology, evidence)
    return next(r for r in results if r.criterion_id == criterion_id)


def test_contradicted_policy_does_not_count_and_the_result_says_so(methodology):
    # retencion 7 vs politica 30: antes puntuaba 50; ahora la politica no cuenta
    evidence = [_backup(7), _encryption(), _claim("backup_policy", {"retencion": "30 dias"})]
    pr02 = _score(methodology, evidence, "CRI-PR-02")

    assert pr02.final_score == 75  # solo tecnico (>= 7 dias), sin politica: tope 75
    assert "Contradiccion entre fuentes" in pr02.explanation
    assert "no cuenta" in pr02.explanation
    claim_id = evidence[2].id
    assert claim_id not in pr02.evidence_ids  # no se cita como evidencia usada


def test_agreeing_policy_still_counts(methodology):
    evidence = [_backup(7), _encryption(), _claim("backup_policy", {"retencion": "7 dias"})]
    pr02 = _score(methodology, evidence, "CRI-PR-02")
    assert pr02.final_score == 100
    assert "Contradiccion" not in pr02.explanation


def test_technical_evidence_is_never_excluded(methodology):
    from app.evaluation.contradictions import exclude_contradicted

    evidence = [_backup(7), _claim("backup_policy", {"retencion": "30 dias"})]
    visibles, contradicciones = exclude_contradicted(evidence)
    assert len(contradicciones) == 1
    assert evidence[0] in visibles and evidence[1] not in visibles


def test_policy_declaring_backups_with_zero_retention_keeps_the_technical_25(methodology):
    evidence = [_backup(0), _claim("backup_policy", {"respaldo": True, "retencion": "7 dias"})]
    pr02 = _score(methodology, evidence, "CRI-PR-02")
    assert pr02.final_score == 25
    assert "Contradiccion entre fuentes" in pr02.explanation


def test_two_disagreeing_documents_both_stop_counting(methodology):
    politica = _claim("policy_exists", {"nombre": "Politica", "aprobada_por": "Direccion"})
    reciente = (date.today() - timedelta(days=30)).isoformat()
    review_a = _claim(
        "policy_review", {"frecuencia": "anual", "ultima_revision": reciente}, doc="politica"
    )

    solo_a = _score(methodology, [politica, review_a], "CRI-GV-01")
    assert solo_a.final_score == 100  # sin contradiccion, la revision vigente cuenta

    review_b = _claim(
        "policy_review", {"frecuencia": "trimestral", "ultima_revision": reciente}, doc="manual"
    )
    ambos = _score(methodology, [politica, review_a, review_b], "CRI-GV-01")
    assert ambos.final_score == 75  # como si ninguna revision existiera
    assert "Contradiccion entre fuentes" in ambos.explanation
    assert review_a.id not in ambos.evidence_ids and review_b.id not in ambos.evidence_ids


def test_same_document_repeating_itself_is_not_excluded(methodology):
    politica = _claim("policy_exists", {"nombre": "Politica", "aprobada_por": "Direccion"})
    reciente = (date.today() - timedelta(days=30)).isoformat()
    revisiones = [
        _claim("policy_review", {"frecuencia": f, "ultima_revision": reciente}, doc="politica")
        for f in ("anual", "trimestral")
    ]
    assert _score(methodology, [politica, *revisiones], "CRI-GV-01").final_score == 100


def test_evaluate_only_applies_the_same_exclusion(methodology):
    evidence = [_backup(7), _encryption(), _claim("backup_policy", {"retencion": "30 dias"})]
    (pr02,) = engine.evaluate_only(methodology, evidence, ["CRI-PR-02"])
    assert pr02.final_score == 75 and "no cuenta" in pr02.explanation


def test_no_contradiction_leaves_evaluation_untouched(methodology):
    evidence = [_backup(14), _encryption()]
    with_engine = engine.evaluate_all(methodology, evidence)
    assert all("Contradiccion" not in r.explanation for r in with_engine)


# -- tope mientras una contradiccion siga sin resolverse -------------------------


def _result_for(criterion_id: str, score: float | None) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=Estado.EVALUADO if score is not None else Estado.EVIDENCIA_INSUFICIENTE,
        base_score=score,
        final_score=score,
        explanation="x",
    )


def _contradiction(criterion_id="CRI-PR-02", titulo="t") -> Contradiction:
    return Contradiction(
        criterion_id=criterion_id,
        titulo=titulo,
        severidad="media",
        detalle="d",
        evidence_ids=[],
        excluded_claim_ids=[],
    )


def test_contradiction_cannot_raise_the_score():
    (r,) = cap_contradicted([_result_for("CRI-PR-02", 75)], [_contradiction()], {"CRI-PR-02": 50})
    assert (r.final_score, r.base_score) == (50, 75)  # base intacto; lo que cuenta es final
    assert "no puede superar el de la evaluacion anterior (50)" in r.explanation


def test_contradiction_can_still_lower_the_score():
    (r,) = cap_contradicted([_result_for("CRI-PR-02", 25)], [_contradiction()], {"CRI-PR-02": 50})
    assert r.final_score == 25 and "no puede superar" not in r.explanation


def test_no_previous_score_or_other_criterion_is_untouched():
    hay = [_contradiction()]
    sin_anterior = cap_contradicted([_result_for("CRI-PR-02", 75)], hay, {})
    assert sin_anterior[0].final_score == 75
    distinto = cap_contradicted([_result_for("CRI-PR-01", 90)], hay, {"CRI-PR-01": 10})
    assert distinto[0].final_score == 90


def test_no_contradiction_means_no_cap():
    (r,) = cap_contradicted([_result_for("CRI-PR-02", 75)], [], {"CRI-PR-02": 50})
    assert r.final_score == 75


def test_cap_holds_until_the_contradiction_is_resolved(db_session, methodology, tmp_path):
    tf = tmp_path / "main.tf"
    docs = FIXTURES / "documents" / "politica-seguridad.md"
    politica_30 = FakeAIClient(
        {
            "Direccion General": {
                "afirmaciones": [
                    {
                        "tipo": "backup_policy",
                        "encontrado": True,
                        "contenido": {"respaldo": True, "retencion": "30 dias"},
                        "cita": {"fragmento": "aprobada por la Direccion General"},
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )

    def run(retencion: int, **extra):
        tf.write_text(
            'resource "aws_db_instance" "db" {\n'
            f"  storage_encrypted = true\n  backup_retention_period = {retencion}\n}}\n"
        )
        assessment = svc.run_assessment(
            db_session,
            methodology,
            org_name="Tope",
            scope=SCOPE,
            terraform_path=tmp_path,
            **extra,
        )
        results = svc.load_criterion_results(db_session, assessment.id)
        return next(r for r in results if r.criterion_id == "CRI-PR-02")

    primera = run(3)  # sin politica, retencion 3 (< 7): 50
    assert primera.final_score == 50

    # El usuario corrige la retencion Y aparece una contradiccion nueva (14 < 30 de la politica):
    # lo tecnico valdria 75, pero el tope lo deja en el puntaje anterior.
    segunda = run(14, documents_path=docs, ai_client=politica_30)
    assert segunda.base_score == 75 and segunda.final_score == 50
    assert "no puede superar el de la evaluacion anterior (50)" in segunda.explanation

    # La contradiccion persiste: el tope sigue, no se levanta por esperar una evaluacion.
    tercera = run(14, documents_path=docs, ai_client=politica_30)
    assert tercera.base_score == 75 and tercera.final_score == 50

    # Se resuelve (retencion >= 30 dias, de acuerdo con la politica): se aplica normalmente.
    cuarta = run(30, documents_path=docs, ai_client=politica_30)
    assert cuarta.final_score >= 75 and "no puede superar" not in cuarta.explanation


def test_contradiction_only_excludes_the_claim_for_its_own_criterion(methodology):
    """La retencion de la politica contradice a Terraform (PR-02), pero su verificacion de
    integridad no: RC-02 y RC-01 la siguen leyendo. Antes la exclusion era global y ambos caian a
    evidencia_insuficiente sin ninguna nota."""

    politica = _claim(
        "backup_policy",
        {"respaldo": True, "verificacion_integridad": True, "retencion": "30 dias"},
    )
    evidence = [_backup(14), _encryption(), politica]

    pr02 = _score(methodology, evidence, "CRI-PR-02")
    assert pr02.final_score == 75 and "no cuenta" in pr02.explanation

    rc02 = _score(methodology, evidence, "CRI-RC-02")
    assert (rc02.estado, rc02.final_score) == (Estado.EVALUADO, 75)
    assert politica.id in rc02.evidence_ids and "Contradiccion" not in rc02.explanation

    rc01 = _score(methodology, evidence, "CRI-RC-01")
    assert (rc01.estado, rc01.final_score) == (Estado.EVALUADO, 50)


def test_disagreeing_review_frequencies_do_not_silence_gv04(methodology):
    reciente = (date.today() - timedelta(days=30)).isoformat()
    revisiones = [
        _claim("policy_review", {"frecuencia": f, "ultima_revision": reciente}, doc=doc)
        for f, doc in (("anual", "politica"), ("trimestral", "manual"))
    ]
    gv04 = _score(methodology, revisiones, "CRI-GV-04")
    assert (gv04.estado, gv04.final_score) == (Estado.EVALUADO, 50)
