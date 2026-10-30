"""CRI-PR-09: resiliencia y capacidad (PR.IR-03/PR.IR-04, docs/09 §92)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation.rules import pr09_resilience as regla
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _terraform(tmp_path, texto: str):
    (tmp_path / "ha.tf").write_text(texto, encoding="utf-8")
    return TerraformAdapter(source_id="s", scope="entorno:produccion").parse_path(tmp_path)


def _señal(mecanismo: str, habilitado: bool | None, ref: str = "r") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.resilience.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref=ref,
        scope="entorno:produccion",
        value={
            "mecanismo": mecanismo,
            "habilitado": habilitado,
            "capacidad_minima": None,
            "capacidad_maxima": None,
            "estado": "declarado" if habilitado is not None else "no_declarado",
        },
        source_id="s",
        locator=Locator(file="ha.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:terraform",
    )


# -- lectura del IaC --------------------------------------------------------------


def test_a_replica_counts_as_high_availability(tmp_path):
    evidencia = _terraform(
        tmp_path,
        'resource "aws_db_instance" "replica" {\n'
        "  replicate_source_db = aws_db_instance.principal.identifier\n"
        "}\n",
    )
    señal = next(e for e in evidencia if e.type_id == "tf.resilience.config")

    assert señal.value["mecanismo"] == "replica"
    assert señal.value["habilitado"] is True


def test_a_group_that_cannot_grow_is_not_elastic_capacity(tmp_path):
    """`min_size == max_size` es capacidad fija con otro nombre."""

    evidencia = _terraform(
        tmp_path,
        'resource "aws_autoscaling_group" "fijo" {\n  min_size = 3\n  max_size = 3\n}\n',
    )
    señal = next(e for e in evidencia if e.type_id == "tf.resilience.config")

    assert señal.value["habilitado"] is False
    assert (señal.value["capacidad_minima"], señal.value["capacidad_maxima"]) == (3, 3)


def test_an_absent_multi_az_is_not_declared_rather_than_unknown(tmp_path):
    """`unknown` esta reservado a un valor que el parser no pudo leer.

    Un `multi_az` que simplemente no esta escrito no es un valor ilegible, y marcarlo `unknown`
    haria aparecer un hallazgo de limitacion por cada base de datos de cualquier `.tf` real.
    """

    evidencia = _terraform(
        tmp_path, 'resource "aws_db_instance" "db" {\n  storage_encrypted = true\n}\n'
    )
    señal = next(e for e in evidencia if e.type_id == "tf.resilience.config")

    assert señal.value["estado"] == "no_declarado"
    assert señal.value["habilitado"] is None
    # El convenio que dispara el hallazgo de limitacion es `estado == "unknown"`.
    assert señal.value["estado"] != "unknown"


# -- la rubrica -------------------------------------------------------------------


def test_no_resources_is_not_applicable():
    resultado = regla.evaluate([])

    assert resultado.estado == Estado.NO_APLICABLE


def test_high_availability_plus_elastic_capacity_scores_100():
    resultado = regla.evaluate(
        [_señal("multi_az", True, "db"), _señal("autoescalado", True, "asg")]
    )

    assert (resultado.estado, resultado.final_score) == (Estado.EVALUADO, 100)


def test_high_availability_without_capacity_scores_75():
    resultado = regla.evaluate([_señal("multi_az", True, "db")])

    assert resultado.final_score == 75
    assert "PR.IR-04" in resultado.explanation


def test_capacity_without_high_availability_scores_50():
    resultado = regla.evaluate(
        [_señal("multi_az", None, "db"), _señal("autoescalado", True, "asg")]
    )

    assert resultado.final_score == 50


def test_capacity_with_high_availability_explicitly_off_scores_25():
    """Crecer con la carga no compensa haber apagado la alta disponibilidad a mano."""

    resultado = regla.evaluate(
        [_señal("multi_az", False, "db"), _señal("autoescalado", True, "asg")]
    )

    assert resultado.final_score == 25


def test_high_availability_explicitly_off_and_no_capacity_scores_0():
    resultado = regla.evaluate([_señal("multi_az", False, "db")])

    assert resultado.final_score == 0


def test_nothing_declared_is_insufficient_not_zero():
    """Que el `.tf` calle no prueba que falte: el defecto de AWS no se supone."""

    resultado = regla.evaluate([_señal("multi_az", None, "db")])

    assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert resultado.final_score is None


@pytest.mark.parametrize("paquete", ["good", "mid", "gaps"])
def test_the_demo_packages_land_on_different_anchors(paquete):
    """La demo tiene que contar algo: 100 / 50 / 0 y no tres veces lo mismo."""

    from pathlib import Path

    demo = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"
    evidencia = TerraformAdapter("demo", "s").parse_path(demo / paquete / "terraform")
    esperado = {"good": 100, "mid": 50, "gaps": 0}[paquete]

    assert regla.evaluate(evidencia).final_score == esperado
