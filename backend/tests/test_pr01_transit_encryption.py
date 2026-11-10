"""CRI-PR-01 v2: el cifrado en transito como compuerta del 100 (PR.DS-02, docs/09 §93).

Lo que fija este archivo es que el ancla **bajo** a proposito: cifrar en reposo ya no basta para el
100. Declarar una subcategoria mas tiene que costar mas evidencia, o la cobertura sube y el puntaje
se abarata a la vez (docs/09 §77).
"""

from __future__ import annotations

from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation.rules import pr01_encryption as regla
from app.evaluation.schemas import Estado

_RDS_CIFRADA = 'resource "aws_db_instance" "d" {\n  storage_encrypted = true\n}\n'


def _evaluar(tmp_path, texto: str):
    (tmp_path / "main.tf").write_text(texto, encoding="utf-8")
    evidencia = TerraformAdapter(source_id="s", scope="entorno:produccion").parse_path(tmp_path)
    return regla.evaluate(evidencia), evidencia


# -- lectura del canal ------------------------------------------------------------


def test_an_https_listener_is_transit_encryption(tmp_path):
    _, evidencia = _evaluar(
        tmp_path,
        'resource "aws_lb_listener" "l" {\n'
        '  protocol   = "HTTPS"\n'
        '  ssl_policy = "ELBSecurityPolicy-TLS13-1-2-2021-06"\n'
        "}\n",
    )
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "enabled"
    assert señal.value["politica"] == "ELBSecurityPolicy-TLS13-1-2-2021-06"


def test_an_http_listener_is_a_channel_in_the_clear(tmp_path):
    _, evidencia = _evaluar(tmp_path, 'resource "aws_lb_listener" "l" {\n  protocol = "HTTP"\n}\n')
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "disabled"


def test_force_ssl_is_read_from_the_parameter_group(tmp_path):
    _, evidencia = _evaluar(
        tmp_path,
        'resource "aws_db_parameter_group" "g" {\n'
        "  parameter {\n"
        '    name  = "rds.force_ssl"\n'
        '    value = "1"\n'
        "  }\n"
        "}\n",
    )
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert (señal.value["mecanismo"], señal.value["estado"]) == ("rds_force_ssl", "enabled")


def test_a_parameter_group_about_other_things_says_nothing_about_transit(tmp_path):
    """Emitir `unknown` por cada grupo de parametros seria ruido: solo se lee el que declara el
    parametro."""

    _, evidencia = _evaluar(
        tmp_path,
        'resource "aws_db_parameter_group" "g" {\n'
        "  parameter {\n"
        '    name  = "log_statement"\n'
        '    value = "all"\n'
        "  }\n"
        "}\n",
    )

    assert [e for e in evidencia if e.type_id == "tf.transit_encryption.config"] == []


def test_force_ssl_as_a_native_boolean_is_enabled_too(tmp_path):
    """`value = true` no es el texto "true": el parser lo entrega como `bool`."""

    _, evidencia = _evaluar(
        tmp_path,
        'resource "aws_db_parameter_group" "g" {\n'
        "  parameter {\n"
        '    name  = "rds.force_ssl"\n'
        "    value = true\n"
        "  }\n"
        "}\n",
    )
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "enabled"


def test_force_ssl_in_capitals_is_enabled_too(tmp_path):
    _, evidencia = _evaluar(
        tmp_path,
        'resource "aws_db_parameter_group" "g" {\n'
        "  parameter {\n"
        '    name  = "rds.force_ssl"\n'
        '    value = "TRUE"\n'
        "  }\n"
        "}\n",
    )
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "enabled"


def test_an_http_listener_that_redirects_to_https_is_not_a_clear_channel(tmp_path):
    """El listener escucha en claro pero no sirve el dato: lo manda a HTTPS."""

    _, evidencia = _evaluar(
        tmp_path,
        'resource "aws_lb_listener" "l" {\n'
        '  protocol = "HTTP"\n'
        "  default_action {\n"
        '    type = "redirect"\n'
        "    redirect {\n"
        '      protocol = "HTTPS"\n'
        "    }\n"
        "  }\n"
        "}\n",
    )
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "enabled"


def test_an_http_redirect_to_http_is_still_a_clear_channel(tmp_path):
    _, evidencia = _evaluar(
        tmp_path,
        'resource "aws_lb_listener" "l" {\n'
        '  protocol = "HTTP"\n'
        "  default_action {\n"
        '    type = "redirect"\n'
        "    redirect {\n"
        '      protocol = "HTTP"\n'
        "    }\n"
        "  }\n"
        "}\n",
    )
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "disabled"


def test_a_tcp_listener_is_unknown_not_a_clear_channel(tmp_path):
    """En un NLB con `TCP` el cifrado depende del destino, y el `.tf` no lo dice."""

    _, evidencia = _evaluar(tmp_path, 'resource "aws_lb_listener" "l" {\n  protocol = "TCP"\n}\n')
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "unknown"
    assert señal.limitations is not None


# -- la compuerta del 100 ---------------------------------------------------------


def test_at_rest_alone_no_longer_reaches_100(tmp_path):
    resultado, _ = _evaluar(tmp_path, _RDS_CIFRADA)

    assert (resultado.estado, resultado.final_score) == (Estado.EVALUADO, 75)
    assert "PR.DS-02" in resultado.explanation


def test_at_rest_plus_an_encrypted_channel_reaches_100(tmp_path):
    resultado, _ = _evaluar(
        tmp_path,
        _RDS_CIFRADA + 'resource "aws_lb_listener" "l" {\n  protocol = "HTTPS"\n}\n',
    )

    assert resultado.final_score == 100


def test_a_channel_in_the_clear_lowers_a_fully_encrypted_store_to_50(tmp_path):
    resultado, _ = _evaluar(
        tmp_path,
        _RDS_CIFRADA + 'resource "aws_lb_listener" "l" {\n  protocol = "HTTP"\n}\n',
    )

    assert resultado.final_score == 50
    assert "viaja en claro" in resultado.explanation


def test_a_failure_at_rest_still_dominates(tmp_path):
    """D7: un fallo en reposo es una base entera legible; el canal no lo compensa."""

    resultado, _ = _evaluar(
        tmp_path,
        'resource "aws_db_instance" "d" {\n  storage_encrypted = false\n}\n'
        'resource "aws_lb_listener" "l" {\n  protocol = "HTTPS"\n}\n',
    )

    assert resultado.final_score == 0


def test_an_unreadable_protocol_does_not_count_as_a_clear_channel(tmp_path):
    """Un `protocol` que es una expresion no se puede leer: ni cifrado ni en claro."""

    resultado, evidencia = _evaluar(
        tmp_path,
        _RDS_CIFRADA + 'resource "aws_lb_listener" "l" {\n  protocol = var.protocolo\n}\n',
    )
    señal = next(e for e in evidencia if e.type_id == "tf.transit_encryption.config")

    assert señal.value["estado"] == "unknown"
    assert resultado.final_score == 75  # no baja a 50: no se observo un canal en claro
