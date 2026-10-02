"""`publicly_accessible` de RDS: evidencia, puntaje en PR-05 y contradiccion con la politica
(ejemplo canonico de docs/02 §5: "BD no publica" vs `publicly_accessible = true`)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.terraform.adapter import TerraformAdapter
from app.ai.client import FakeAIClient
from app.core import assessment_service as svc
from app.evaluation.rules import pr05_public_access
from app.evaluation.schemas import Estado
from app.methodology.loader import load_methodology
from app.recommendations.contradictions import detect_contradictions
from app.recommendations.findings import derive_findings
from app.schemas.evidence import EvidenceInstance, Locator, Modality

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCOPE = "entorno:produccion"


def _parse(tmp_path, hcl: str) -> list[EvidenceInstance]:
    tf_file = tmp_path / "main.tf"
    tf_file.write_text(hcl)
    return TerraformAdapter(source_id="t", scope=SCOPE).parse_path(tf_file)


def _of(evidence, type_id):
    return [e for e in evidence if e.type_id == type_id]


def _db(publico, ref="aws_db_instance.db") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.db_exposure.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref=ref,
        scope=SCOPE,
        value={"publico": publico},
        source_id="t",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _policy(permitidas, **extra) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope=SCOPE,
        value={
            "tipo_afirmacion": "exposure_policy",
            "contenido": {"bases_publicas_permitidas": permitidas},
            "encontrado": True,
            "confianza": 0.9,
        },
        source_id="t",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
        **extra,
    )


# -- adaptador ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attr", "esperado"),
    [("publicly_accessible = true", True), ("publicly_accessible = false", False), ("", "unknown")],
)
def test_adapter_reports_publicly_accessible_without_assuming_defaults(tmp_path, attr, esperado):
    evidence = _parse(tmp_path, f'resource "aws_db_instance" "db" {{\n  {attr}\n}}')
    (exposure,) = _of(evidence, "tf.db_exposure.config")
    assert exposure.value == {"publico": esperado}
    assert (exposure.limitations is not None) == (esperado == "unknown")


def test_expression_is_unknown_and_reported_as_unresolved(tmp_path):
    evidence = _parse(
        tmp_path, 'resource "aws_db_instance" "db" { publicly_accessible = var.public }'
    )
    assert _of(evidence, "tf.db_exposure.config")[0].value == {"publico": "unknown"}
    assert [e.value["atributo"] for e in _of(evidence, "tf.expression.unresolved")] == [
        "publicly_accessible"
    ]


# -- PR-05 --------------------------------------------------------------------------------


def test_public_database_scores_zero():
    resultado = pr05_public_access.evaluate([_db(True)])
    assert (resultado.estado, resultado.final_score) == (Estado.EVALUADO, 0)
    assert "aws_db_instance.db" in resultado.explanation


def test_private_database_alone_is_fine_and_unknown_is_not_applicable():
    assert pr05_public_access.evaluate([_db(False)]).final_score == 100
    assert pr05_public_access.evaluate([_db("unknown")]).estado == Estado.NO_APLICABLE
    assert pr05_public_access.evaluate([]).estado == Estado.NO_APLICABLE


def test_public_database_overrides_a_well_configured_bucket(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_s3_bucket" "a" { bucket = "a" }
        resource "aws_s3_bucket_public_access_block" "pab" {
          bucket                  = aws_s3_bucket.a.id
          block_public_acls       = true
          block_public_policy     = true
          ignore_public_acls      = true
          restrict_public_buckets = true
        }
        resource "aws_db_instance" "db" { publicly_accessible = true }
        """,
    )
    resultado = pr05_public_access.evaluate(evidence)
    assert resultado.final_score == 0
    assert "bloqueo completo" in resultado.explanation  # el estado del bucket sigue visible


# -- contradiccion ------------------------------------------------------------------------


def test_policy_forbidding_public_databases_contradicts_a_public_one():
    db, policy = _db(True), _policy(False)
    (f,) = detect_contradictions([db, policy])
    assert (f.tipo, f.criterion_id, f.severidad) == ("contradiccion", "CRI-PR-05", "alta")
    assert set(f.evidence_ids) == {db.id, policy.id}
    assert "aws_db_instance.db" in f.detalle and "D7" in f.detalle


@pytest.mark.parametrize(
    "evidence",
    [
        [_db(True), _policy(True)],  # la politica lo permite
        [_db(False), _policy(False)],  # coherente
        [_db("unknown"), _policy(False)],  # desconocido: limitacion, no contradiccion
        [_db(True)],  # sin politica: no hay con que contradecir
        [_db(True), _policy(False, limitations="confianza baja")],
    ],
)
def test_no_contradiction_when_sources_agree_or_one_side_is_missing(evidence):
    assert detect_contradictions(evidence) == []


def test_end_to_end_policy_vs_gaps_fixture(db_session):
    methodology = load_methodology(METHODOLOGY_DIR)
    fake = FakeAIClient(
        {
            "Direccion General": {
                "afirmaciones": [
                    {
                        "tipo": "exposure_policy",
                        "encontrado": True,
                        "contenido": {"bases_publicas_permitidas": False},
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
        org_name="Exposicion",
        scope=SCOPE,
        terraform_path=FIXTURES / "terraform" / "gaps",
        documents_path=FIXTURES / "documents" / "politica-seguridad.md",
        ai_client=fake,
    )
    results = svc.load_criterion_results(db_session, assessment.id)
    evidence = svc.load_evidence(db_session, assessment.id)

    contradicciones = [
        f for f in derive_findings(methodology, results, evidence) if f.tipo == "contradiccion"
    ]
    assert [(f.criterion_id, f.severidad) for f in contradicciones] == [("CRI-PR-05", "alta")]
    pr05 = next(r for r in results if r.criterion_id == "CRI-PR-05")
    assert pr05.final_score == 0  # prevalece lo tecnico; la politica no lo cambia
