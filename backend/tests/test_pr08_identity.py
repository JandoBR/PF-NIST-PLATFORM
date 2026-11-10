"""CRI-PR-08: identidades y autenticacion (PR.AA-01/PR.AA-03, docs/09 §91).

Lo que mas importa fijar aqui es la **asimetria** de la rubrica: una politica debil declarada puntua
mas bajo que no declarar ninguna. Es intencionado y contraintuitivo, asi que sin un test que lo diga
el proximo que lo lea lo "arreglara".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation.rules import pr08_identity as regla
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality

_MFA_DOC = """{
  "Statement": [{
    "Effect": "Deny",
    "Condition": { "BoolIfExists": { "aws:MultiFactorAuthPresent": "false" } }
  }]
}"""


def _terraform(tmp_path, texto: str):
    (tmp_path / "iam.tf").write_text(texto, encoding="utf-8")
    return TerraformAdapter(source_id="s", scope="entorno:produccion").parse_path(tmp_path)


def _presente(tipo: str, nombre: str = "x") -> EvidenceInstance:
    return _evidencia(
        "tf.resource.present", tipo, f"{tipo}.{nombre}", {"tipo": tipo, "nombre": nombre}
    )


def _politica(longitud: int | None) -> EvidenceInstance:
    return _evidencia(
        "tf.identity.config",
        "aws_iam_account_password_policy",
        "aws_iam_account_password_policy.cuenta",
        {
            "tipo": "politica_de_contrasenas",
            "longitud_minima": longitud,
            "mfa_requerido": None,
            "estado": "declarado" if longitud is not None else "unknown",
        },
    )


def _mfa(exige: bool | None) -> EvidenceInstance:
    return _evidencia(
        "tf.identity.config",
        "aws_iam_policy",
        "aws_iam_policy.mfa",
        {
            "tipo": "mfa",
            "longitud_minima": None,
            "mfa_requerido": exige,
            "estado": "declarado" if exige is not None else "unknown",
        },
    )


def _evidencia(type_id: str, subject_type: str, subject_ref: str, value: dict) -> EvidenceInstance:
    return EvidenceInstance(
        type_id=type_id,
        type_version=1,
        subject_type=subject_type,
        subject_ref=subject_ref,
        scope="entorno:produccion",
        value=value,
        source_id="s",
        locator=Locator(file="iam.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:terraform",
    )


# -- lectura del IaC --------------------------------------------------------------


def test_mfa_is_read_from_the_policy_document(tmp_path):
    """En AWS no hay atributo "exigir MFA": esta en la condicion del documento de la politica."""

    evidencia = _terraform(
        tmp_path,
        'resource "aws_iam_policy" "mfa" {\n  policy = <<EOF\n' + _MFA_DOC + "\nEOF\n}\n",
    )
    config = [e for e in evidencia if e.type_id == "tf.identity.config"]

    assert [e.value["mfa_requerido"] for e in config] == [True]


def test_a_policy_without_the_condition_does_not_require_mfa(tmp_path):
    evidencia = _terraform(
        tmp_path,
        'resource "aws_iam_policy" "lectura" {\n'
        '  policy = <<EOF\n{"Statement": [{"Effect": "Allow", "Action": "s3:GetObject"}]}\nEOF\n'
        "}\n",
    )
    config = [e for e in evidencia if e.type_id == "tf.identity.config"]

    assert [e.value["mfa_requerido"] for e in config] == [False]


def _mfa_documento(tmp_path, documento: dict | str) -> EvidenceInstance:
    texto = documento if isinstance(documento, str) else json.dumps(documento)
    evidencia = _terraform(
        tmp_path,
        'resource "aws_iam_policy" "mfa" {\n  policy = <<EOF\n' + texto + "\nEOF\n}\n",
    )
    return next(e for e in evidencia if e.type_id == "tf.identity.config")


def test_an_allow_conditioned_on_mfa_true_requires_it(tmp_path):
    config = _mfa_documento(
        tmp_path,
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}},
                }
            ]
        },
    )

    assert config.value["mfa_requerido"] is True


def test_a_false_condition_on_an_allow_does_not_require_mfa(tmp_path):
    """La clave presente con `false` no exige MFA: el chequeo de subcadena decia que si."""

    config = _mfa_documento(
        tmp_path,
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "false"}},
                }
            ]
        },
    )

    assert config.value["mfa_requerido"] is False
    assert config.value["estado"] == "declarado"


def test_the_key_in_a_non_boolean_operator_does_not_require_mfa(tmp_path):
    config = _mfa_documento(
        tmp_path,
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Condition": {"StringEquals": {"aws:MultiFactorAuthPresent": "true"}},
                }
            ]
        },
    )

    assert config.value["mfa_requerido"] is False


def test_the_condition_key_is_case_insensitive(tmp_path):
    config = _mfa_documento(
        tmp_path,
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Condition": {"BoolIfExists": {"aws:multifactorauthpresent": "true"}},
                }
            ]
        },
    )

    assert config.value["mfa_requerido"] is True


def test_an_invalid_policy_document_is_unknown_not_a_denial(tmp_path):
    """Un documento que no es JSON no se puede valorar: `unknown`, no `false`."""

    config = _mfa_documento(tmp_path, "{ esto no es json")

    assert config.value["mfa_requerido"] is None
    assert config.value["estado"] == "unknown"
    assert config.limitations is not None


def test_a_generated_policy_document_is_unknown_not_a_denial(tmp_path):
    """Un documento construido por un `data` source no se puede leer: `unknown`, no `false`.

    Lo contrario convertiria una limitacion del parser en un incumplimiento (docs/02 §4).
    """

    evidencia = _terraform(
        tmp_path,
        'resource "aws_iam_policy" "generada" {\n'
        "  policy = data.aws_iam_policy_document.x.json\n"
        "}\n",
    )
    config = next(e for e in evidencia if e.type_id == "tf.identity.config")

    assert config.value["mfa_requerido"] is None
    assert config.value["estado"] == "unknown"
    assert config.limitations is not None


def test_the_password_policy_is_not_counted_as_an_asset():
    """`aws_iam_account_password_policy` configura la cuenta: ningun inventario la lista."""

    from app.adapters.terraform.adapter import CONFIG_RESOURCE_TYPES

    assert "aws_iam_account_password_policy" in CONFIG_RESOURCE_TYPES


# -- la rubrica -------------------------------------------------------------------


def test_no_iam_at_all_is_insufficient_not_zero():
    resultado = regla.evaluate([])

    assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert resultado.final_score is None


def test_a_declared_weak_policy_scores_lower_than_no_policy_at_all():
    """La asimetria deliberada: en IaC la ausencia no prueba la ausencia, una longitud de 6 si.

    La cuenta puede tener su politica puesta fuera de Terraform, asi que no verla no se penaliza
    como verla mal (mismo principio que el silencio documental, docs/09 §60).
    """

    sin_politica = regla.evaluate([_presente("aws_iam_role")])
    con_politica_debil = regla.evaluate([_presente("aws_iam_role"), _politica(6)])

    assert sin_politica.final_score == 50
    assert con_politica_debil.final_score == 0
    assert con_politica_debil.final_score < sin_politica.final_score


@pytest.mark.parametrize(
    ("longitud", "esperado"),
    [(6, 0), (7, 0), (8, 25), (13, 25), (14, 75), (20, 75)],
)
def test_the_length_threshold_is_the_cis_benchmark(longitud, esperado):
    resultado = regla.evaluate([_presente("aws_iam_role"), _politica(longitud)])

    assert resultado.final_score == esperado


def test_the_threshold_plus_mfa_is_what_reaches_100():
    resultado = regla.evaluate([_presente("aws_iam_role"), _politica(14), _mfa(True)])

    assert (resultado.estado, resultado.final_score) == (Estado.EVALUADO, 100)


def test_an_unreadable_mfa_policy_does_not_reach_100():
    """Si no se puede leer si exige MFA, no se puede afirmar que lo exige."""

    resultado = regla.evaluate([_presente("aws_iam_role"), _politica(14), _mfa(None)])

    assert resultado.final_score == 75


def test_the_weakest_declared_policy_decides():
    """Con dos politicas declaradas manda la mas debil: es la que la cuenta aplica de hecho."""

    resultado = regla.evaluate([_presente("aws_iam_role"), _politica(14), _politica(8)])

    assert resultado.final_score == 25


def test_a_policy_with_a_non_literal_length_cannot_be_valued():
    resultado = regla.evaluate([_presente("aws_iam_role"), _politica(None)])

    assert resultado.final_score == 50
    assert "no es literal" in resultado.explanation


def test_unresolved_expressions_are_declared_as_a_limitation(tmp_path):
    """El decorador `noting_unresolved` cita la expresion sin cambiar el puntaje."""

    evidencia = _terraform(
        tmp_path,
        'resource "aws_iam_role" "app" {\n  name = "app"\n}\n'
        'resource "aws_iam_account_password_policy" "cuenta" {\n'
        "  minimum_password_length = var.longitud\n"
        "}\n",
    )
    resultado = regla.evaluate(evidencia)

    assert "Limitacion" in resultado.explanation
    assert resultado.final_score == 50  # no se puede valorar, y no baja por la limitacion
