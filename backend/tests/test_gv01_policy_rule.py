from datetime import UTC, datetime, timedelta

from app.evaluation.rules import gv01_policy
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality

LOCATOR = Locator(file="politica.md")


def _claim(tipo_afirmacion, encontrado, contenido=None, confianza=0.9, limitations=None):
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": tipo_afirmacion,
            "contenido": contenido or {},
            "encontrado": encontrado,
            "confianza": confianza,
        },
        source_id="test:doc",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        limitations=limitations,
        created_by="ai:extraction",
    )


def test_no_claims_at_all_is_insufficient():
    result = gv01_policy.evaluate([])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


def test_explicit_not_found_is_no_implementado_zero():
    claims = [_claim("policy_exists", encontrado=False)]
    result = gv01_policy.evaluate(claims)
    assert result.estado == Estado.NO_IMPLEMENTADO
    assert result.final_score == 0


def test_informal_mention_without_name_scores_25():
    claims = [_claim("policy_exists", encontrado=True, contenido={})]
    result = gv01_policy.evaluate(claims)
    assert result.final_score == 25


def test_exists_without_approval_scores_50():
    claims = [_claim("policy_exists", encontrado=True, contenido={"nombre": "Politica X"})]
    result = gv01_policy.evaluate(claims)
    assert result.final_score == 50


def test_approved_without_review_scores_75():
    claims = [
        _claim(
            "policy_exists",
            encontrado=True,
            contenido={"nombre": "Politica X", "aprobada_por": "Direccion"},
        )
    ]
    result = gv01_policy.evaluate(claims)
    assert result.final_score == 75


def test_approved_with_review_within_frequency_scores_100():
    ultima_revision = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    claims = [
        _claim(
            "policy_exists",
            encontrado=True,
            contenido={"nombre": "Politica X", "aprobada_por": "Direccion"},
        ),
        _claim(
            "policy_review",
            encontrado=True,
            contenido={"frecuencia": "anual", "ultima_revision": ultima_revision},
        ),
    ]
    result = gv01_policy.evaluate(claims)
    assert result.final_score == 100


def test_approved_with_stale_review_scores_75():
    ultima_revision = (datetime.now(UTC) - timedelta(days=900)).date().isoformat()
    claims = [
        _claim(
            "policy_exists",
            encontrado=True,
            contenido={"nombre": "Politica X", "aprobada_por": "Direccion"},
        ),
        _claim(
            "policy_review",
            encontrado=True,
            contenido={"frecuencia": "anual", "ultima_revision": ultima_revision},
        ),
    ]
    result = gv01_policy.evaluate(claims)
    assert result.final_score == 75


def test_low_confidence_claim_is_not_usable():
    claims = [
        _claim(
            "policy_exists",
            encontrado=True,
            contenido={"nombre": "Politica X", "aprobada_por": "Direccion"},
            limitations="confianza baja (0.3 < 0.6)",
        )
    ]
    result = gv01_policy.evaluate(claims)
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
