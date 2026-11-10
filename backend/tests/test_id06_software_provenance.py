"""CRI-ID-06: procedencia del codigo de terceros (ID.RA-09, docs/09 §90).

Prueba las dos piezas por separado: que el adaptador lea los bloques que antes ignoraba, y que la
rubrica distinga los cuatro tramos. Lo que la Oleada C aporta frente a las anteriores es que esta
subcategoria no depende de que U1 extraiga nada: la evidencia sale del `.tf`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.terraform.adapter import (
    TerraformAdapter,
    block_line_ranges,
    module_origin,
    module_pinned,
)
from app.evaluation.rules import id06_software_provenance as regla
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _terraform(tmp_path, texto: str):
    (tmp_path / "versiones.tf").write_text(texto, encoding="utf-8")
    return TerraformAdapter(source_id="s", scope="entorno:produccion").parse_path(tmp_path)


def _modulo(nombre: str, *, origen: str, fijada: bool) -> EvidenceInstance:
    estado = "propio" if origen == "local" else ("fijado" if fijada else "sin_fijar")
    return EvidenceInstance(
        type_id="tf.module.source",
        type_version=1,
        subject_type="module",
        subject_ref=f"module.{nombre}",
        scope="entorno:produccion",
        value={
            "nombre": nombre,
            "source": "x",
            "version": "1.0" if fijada else None,
            "origen": origen,
            "fijada": fijada,
            "estado": estado,
        },
        source_id="s",
        locator=Locator(file="versiones.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:terraform",
    )


def _proveedor(nombre: str, *, fijada: bool) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.provider.version",
        type_version=1,
        subject_type="provider",
        subject_ref=f"provider.{nombre}",
        scope="entorno:produccion",
        value={
            "proveedor": nombre,
            "restriccion": "~> 5.0" if fijada else None,
            "fijada": fijada,
            "estado": "fijado" if fijada else "sin_fijar",
        },
        source_id="s",
        locator=Locator(file="versiones.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:terraform",
    )


# -- clasificacion del `source` ---------------------------------------------------


@pytest.mark.parametrize(
    ("source", "esperado"),
    [
        ("terraform-aws-modules/vpc/aws", "registry"),
        ("terraform-aws-modules/vpc/aws//modules/subnets", "registry"),
        # Registry privado: `host/namespace/nombre/proveedor`. El host se distingue de un
        # namespace por el punto, asi que el publico de tres segmentos sigue funcionando.
        ("app.terraform.io/acme/vpc/aws", "registry"),
        ("registry.acme.local/infra/red/aws", "registry"),
        ("github.com/acme/red", "git"),
        ("git::https://git.acme.local/infra/red.git", "git"),
        ("git@github.com:acme/red.git", "git"),
        ("https://acme.local/modulos/red.zip", "externo"),
        ("./modulos/red", "local"),
        ("../../compartido/red", "local"),
        ("${var.fuente}", "desconocido"),
        (None, "desconocido"),
        ("", "desconocido"),
    ],
)
def test_module_origin_classifies_the_source(source, esperado):
    assert module_origin(source) == esperado


@pytest.mark.parametrize(
    ("source", "version", "esperado"),
    [
        ("terraform-aws-modules/vpc/aws", "5.8.1", True),
        ("terraform-aws-modules/vpc/aws", None, False),
        # Un modulo de git no se fija con `version` sino con un ref en la propia URL.
        ("git::https://git.acme.local/red.git?ref=v2.1.0", None, True),
        ("git::https://git.acme.local/red.git?ref=1.2.3", None, True),
        ("git::https://git.acme.local/red.git?ref=v1.2.3-rc.1", None, True),
        # Un SHA de commit fija la procedencia aunque no sea una etiqueta.
        ("git::https://git.acme.local/red.git?ref=3f2a1b4", None, True),
        (
            "git::https://git.acme.local/red.git?ref=3f2a1b4c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a",
            None,
            True,
        ),
        # Una rama, o un `ref` vacio, sigue lo que haya manana: no fija nada.
        ("git::https://git.acme.local/red.git?ref=main", None, False),
        ("git::https://git.acme.local/red.git?ref=develop", None, False),
        ("git::https://git.acme.local/red.git?ref=", None, False),
        ("git::https://git.acme.local/red.git", None, False),
        # Una version que es una expresion no fija nada: no se sabe a que resuelve.
        ("terraform-aws-modules/vpc/aws", "${var.v}", False),
        # Y una version literal sobre un `source` que no lo es tampoco: fijar la version de un
        # modulo que no se sabe cual es no hace reproducible su procedencia.
        ("${var.fuente}", "1.0.0", False),
        ("app.terraform.io/acme/vpc/aws", "1.0.0", True),
    ],
)
def test_module_pinned_needs_something_reproducible(source, version, esperado):
    assert module_pinned(source, version) is esperado


# -- el adaptador lee los bloques que antes ignoraba -------------------------------


def test_adapter_reads_modules_and_required_providers(tmp_path):
    evidencia = _terraform(
        tmp_path,
        "terraform {\n"  # 1
        '  required_version = ">= 1.6.0"\n'  # 2
        "  required_providers {\n"  # 3
        '    aws = { source = "hashicorp/aws", version = "~> 5.40" }\n'  # 4
        '    random = { source = "hashicorp/random" }\n'  # 5
        "  }\n"  # 6
        "}\n"  # 7
        "\n"  # 8
        'module "red" {\n'  # 9
        '  source  = "terraform-aws-modules/vpc/aws"\n'  # 10
        '  version = "5.8.1"\n'  # 11
        "}\n",  # 12
    )
    por_ref = {e.subject_ref: e for e in evidencia}

    assert por_ref["module.red"].value["origen"] == "registry"
    assert por_ref["module.red"].value["fijada"] is True
    assert por_ref["provider.aws"].value["restriccion"] == "~> 5.40"
    # Declarado sin `version`: entra con restriccion nula, no se omite.
    assert por_ref["provider.random"].value["restriccion"] is None
    assert por_ref["provider.random"].limitations == "declarado sin restriccion de version"
    # Un `module` no es un recurso desplegado: no debe aparecer como `tf.resource.present`.
    assert [e for e in evidencia if e.type_id == "tf.resource.present"] == []


def test_a_legacy_provider_string_is_a_version_constraint(tmp_path):
    """`aws = "~> 4.0"` es la forma heredada de `required_providers`, no un proveedor sin fijar."""

    evidencia = _terraform(
        tmp_path,
        'terraform {\n  required_providers {\n    aws = "~> 4.0"\n  }\n}\n',
    )
    proveedor = next(e for e in evidencia if e.type_id == "tf.provider.version")

    assert proveedor.value["restriccion"] == "~> 4.0"
    assert proveedor.value["fijada"] is True
    assert proveedor.limitations is None


def test_module_and_terraform_blocks_carry_real_line_ranges(tmp_path):
    """El locator es lo que hace auditable la evidencia: un bloque nuevo sin lineas no sirve."""

    evidencia = _terraform(
        tmp_path,
        "# comentario\n"  # 1
        "terraform {\n"  # 2
        "  required_providers {\n"  # 3
        '    aws = { source = "hashicorp/aws", version = "1.0" }\n'  # 4
        "  }\n"  # 5
        "}\n"  # 6
        'module "red" {\n'  # 7
        '  source = "./red"\n'  # 8
        "}\n",  # 9
    )
    por_ref = {e.subject_ref: e for e in evidencia}

    assert (
        por_ref["provider.aws"].locator.line_start,
        por_ref["provider.aws"].locator.line_end,
    ) == (
        2,
        6,
    )
    assert (por_ref["module.red"].locator.line_start, por_ref["module.red"].locator.line_end) == (
        7,
        9,
    )


def test_terraform_block_pattern_does_not_match_a_similar_word():
    """`terraform_remote_state` o `terraform = x` no abren un bloque `terraform`."""

    from app.adapters.terraform.adapter import _TERRAFORM_START

    texto = (
        'data "terraform_remote_state" "red" {\n'
        '  backend = "s3"\n'
        "}\n"
        'terraform = "no es un bloque"\n'
    )
    assert block_line_ranges(texto, _TERRAFORM_START) == {}


def test_unresolvable_source_is_unknown_not_a_guess(tmp_path):
    evidencia = _terraform(tmp_path, 'module "red" {\n  source = var.fuente\n}\n')
    modulo = next(e for e in evidencia if e.type_id == "tf.module.source")

    assert modulo.value["origen"] == "desconocido"
    assert modulo.value["source"] is None
    assert modulo.value["estado"] == "unknown"
    assert modulo.limitations is not None


# -- la rubrica -------------------------------------------------------------------


def test_no_modules_and_no_providers_is_not_applicable():
    """Sin `module` ni `required_providers` no hay adquisicion que evaluar: no es un cero."""

    resultado = regla.evaluate([])

    assert resultado.estado == Estado.NO_APLICABLE
    assert resultado.final_score is None


def test_everything_pinned_scores_100():
    resultado = regla.evaluate(
        [
            _modulo("red", origen="registry", fijada=True),
            _modulo("etiquetas", origen="local", fijada=False),
            _proveedor("aws", fijada=True),
        ]
    )

    assert (resultado.estado, resultado.final_score) == (Estado.EVALUADO, 100)


def test_a_local_module_is_never_counted_as_unpinned():
    """Codigo del mismo repositorio no se adquiere: pedirle `version` castigaria modularizar."""

    solo_locales = regla.evaluate(
        [_modulo("etiquetas", origen="local", fijada=False), _proveedor("aws", fijada=True)]
    )

    assert solo_locales.final_score == 100


def test_pinned_providers_with_an_unpinned_module_scores_75():
    resultado = regla.evaluate(
        [
            _modulo("red", origen="registry", fijada=True),
            _modulo("legacy", origen="git", fijada=False),
            _proveedor("aws", fijada=True),
        ]
    )

    assert resultado.final_score == 75
    assert "legacy" in resultado.explanation


def test_pinned_modules_without_a_provider_restriction_scores_50():
    resultado = regla.evaluate(
        [_modulo("red", origen="registry", fijada=True), _proveedor("aws", fijada=False)]
    )

    assert resultado.final_score == 50


def test_nothing_pinned_scores_25_not_0():
    """Un `source` sin version es silencio sobre la procedencia, no una negacion (docs/09 §60)."""

    resultado = regla.evaluate(
        [_modulo("legacy", origen="git", fijada=False), _proveedor("aws", fijada=False)]
    )

    assert resultado.final_score == 25
    assert resultado.estado == Estado.EVALUADO


def test_an_unreadable_source_counts_as_third_party():
    """Un `source` que no se pudo leer no se puede suponer propio: cuenta como adquirido."""

    resultado = regla.evaluate(
        [_modulo("misterio", origen="desconocido", fijada=False), _proveedor("aws", fijada=True)]
    )

    assert resultado.final_score == 75


def test_every_cited_evidence_is_real():
    evidencia = [_modulo("red", origen="registry", fijada=True), _proveedor("aws", fijada=True)]
    resultado = regla.evaluate(evidencia)

    assert set(resultado.evidence_ids) == {e.id for e in evidencia}


def test_a_pinned_module_is_never_reported_as_unreadable():
    """`fijada: true` con `estado: "unknown"` se contradecia en la cara.

    Un modulo de registry privado traia `source` literal y `version`, pero caia en `desconocido`
    porque el patron solo aceptaba tres segmentos: emitia un hallazgo diciendo que el `source` no
    era literal cuando si lo era. Apareció revisando la Oleada C.
    """

    for source, version in [
        ("app.terraform.io/acme/vpc/aws", "1.0.0"),
        ("terraform-aws-modules/vpc/aws", "5.8.1"),
        ("git::https://g.local/red.git?ref=v1.0", None),
        ("${var.fuente}", "1.0.0"),
    ]:
        origen = module_origin(source)
        fijada = module_pinned(source, version)
        assert not (fijada and origen == "desconocido"), (source, version)
