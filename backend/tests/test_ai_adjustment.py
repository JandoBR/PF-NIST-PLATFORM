from datetime import UTC, datetime
from pathlib import Path

from app.ai.adjustment import adjust
from app.ai.client import FakeAIClient
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import load_methodology
from app.schemas.evidence import EvidenceInstance, Locator, Modality

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
ALPHA = 0.25
D = 20


def _methodology():
    return load_methodology(METHODOLOGY_DIR)


def _evidence_by_id(evidence_id: str = "ev1") -> dict[str, EvidenceInstance]:
    item = EvidenceInstance(
        id=evidence_id,
        type_id="tf.encryption.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref="aws_db_instance.principal",
        scope="entorno:produccion",
        value={"estado": "disabled", "mecanismo": None, "llave": None},
        source_id="test:tf",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:terraform",
    )
    return {evidence_id: item}


def _result(criterion_id="CRI-PR-01", estado=Estado.EVALUADO, base_score=25.0, evidence_ids=None):
    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=estado,
        base_score=base_score,
        final_score=base_score,
        explanation="base",
        evidence_ids=evidence_ids or ["ev1"],
    )


def _fake_response(**overrides):
    base = {
        "criterion_id": "CRI-PR-01",
        "puntaje_base_recibido": 25,
        "puntaje_propuesto": 45,
        "justificacion": "Politica formal reduce el impacto (ev1).",
        "evidencias_referenciadas": ["ev1"],
        "confianza": 0.8,
    }
    base.update(overrides)
    return base


def test_non_adjustable_criterion_is_never_touched():
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-03"]  # ai_adjustable: false
    result = _result(criterion_id="CRI-PR-03")
    client = FakeAIClient({"CRI-PR-01": _fake_response()})

    out = adjust(client, criterion, result, {}, {}, ALPHA, D)

    assert out is result
    assert out.degradado is False


def test_evidencia_insuficiente_is_never_adjusted():
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-01"]
    result = _result(estado=Estado.EVIDENCIA_INSUFICIENTE, base_score=None)
    client = FakeAIClient({"CRI-PR-01": _fake_response()})

    out = adjust(client, criterion, result, {}, {}, ALPHA, D)

    assert out is result
    assert out.degradado is False


def test_degrades_when_ai_returns_nothing():
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-01"]
    result = _result()
    client = FakeAIClient({})  # ninguna palabra clave coincide -> None

    out = adjust(client, criterion, result, _evidence_by_id(), {}, ALPHA, D)

    assert out.degradado is True
    assert out.final_score == result.base_score


def test_degrades_when_justification_cites_no_evidence():
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-01"]
    result = _result()
    client = FakeAIClient({"CRI-PR-01": _fake_response(evidencias_referenciadas=[])})

    out = adjust(client, criterion, result, _evidence_by_id(), {}, ALPHA, D)

    assert out.degradado is True


def test_degrades_when_justification_cites_invented_evidence():
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-01"]
    result = _result()
    client = FakeAIClient({"CRI-PR-01": _fake_response(evidencias_referenciadas=["ev_no_existe"])})

    out = adjust(client, criterion, result, _evidence_by_id(), {}, ALPHA, D)

    assert out.degradado is True


def test_applies_bounded_formula_exactly():
    # B=25, A=45, D=20 -> A_acotado=45 (dentro del margen); S = 0.75*25 + 0.25*45 = 30
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-01"]
    result = _result(base_score=25.0)
    client = FakeAIClient({"CRI-PR-01": _fake_response(puntaje_propuesto=45)})

    out = adjust(client, criterion, result, _evidence_by_id(), {}, ALPHA, D)

    assert out.final_score == 30.0
    assert out.degradado is False
    assert "Ajuste contextual: +5" in out.explanation


def test_proposal_beyond_divergence_is_clamped():
    # B=25, A=90, D=20 -> A_acotado=45 (25+20); S = 0.75*25+0.25*45 = 30, igual que arriba.
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-01"]
    result = _result(base_score=25.0)
    client = FakeAIClient({"CRI-PR-01": _fake_response(puntaje_propuesto=90)})

    out = adjust(client, criterion, result, _evidence_by_id(), {}, ALPHA, D)

    assert out.final_score == 30.0


def test_no_implementado_is_never_adjusted_upward():
    methodology = _methodology()
    criterion = methodology.criterios["CRI-GV-01"]
    result = _result(
        criterion_id="CRI-GV-01", estado=Estado.NO_IMPLEMENTADO, base_score=0.0
    )
    # La IA propone subirlo a 60; J2 lo recorta a 0 antes de aplicar la formula.
    client = FakeAIClient(
        {"CRI-GV-01": _fake_response(criterion_id="CRI-GV-01", puntaje_propuesto=60)}
    )

    out = adjust(client, criterion, result, _evidence_by_id(), {}, ALPHA, D)

    assert out.final_score == 0.0
    assert out.degradado is False


def test_no_change_is_still_recorded_in_explanation():
    methodology = _methodology()
    criterion = methodology.criterios["CRI-PR-01"]
    result = _result(base_score=25.0)
    client = FakeAIClient({"CRI-PR-01": _fake_response(puntaje_propuesto=25)})

    out = adjust(client, criterion, result, _evidence_by_id(), {}, ALPHA, D)

    assert out.final_score == 25.0
    assert "sin cambio" in out.explanation
