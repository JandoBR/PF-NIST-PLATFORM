"""Guardias del nucleo de CSF 2.0 y de la cobertura de implementacion (AMP-04, docs/01 §7).

`csf_subcategories.yml` se escribio a mano y ahora es el denominador de una metrica que el
informe publica. Estos tests existen para que una edicion silenciosa no la falsee.
"""

from pathlib import Path

import pytest

from app.methodology.coverage import compute
from app.methodology.loader import load_methodology
from app.methodology.schemas import CsfCoreCatalog

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"

#: Subcategorias por categoria segun NIST CSF 2.0. Los huecos de numeracion son reales:
#: NIST retiro subcategorias de la v1.1 y no renumero las restantes.
CONTEO_ESPERADO = {
    "GV.OC": 5, "GV.RM": 7, "GV.RR": 4, "GV.PO": 2, "GV.OV": 3, "GV.SC": 10,
    "ID.AM": 7, "ID.RA": 10, "ID.IM": 4,
    "PR.AA": 6, "PR.AT": 2, "PR.DS": 4, "PR.PS": 6, "PR.IR": 4,
    "DE.CM": 5, "DE.AE": 6,
    "RS.MA": 5, "RS.AN": 4, "RS.CO": 2, "RS.MI": 2,
    "RC.RP": 6, "RC.CO": 2,
}  # fmt: skip

#: Ids retirados en la v1.1 que NO deben reaparecer "rellenando" los huecos.
HUECOS_REALES = [
    "ID.AM-06", "PR.DS-03", "PR.DS-09", "DE.CM-04", "DE.CM-08",
    "DE.AE-01", "DE.AE-05", "RS.AN-01", "RS.AN-05", "RS.CO-01",
    "RC.CO-01", "RC.CO-02",
]  # fmt: skip


@pytest.fixture(scope="module")
def nucleo() -> CsfCoreCatalog:
    return load_methodology(METHODOLOGY_DIR).nucleo_csf


def test_shape_matches_nist(nucleo):
    assert len(nucleo.funciones) == 6
    assert len(nucleo.categoria_ids) == 22
    assert len(nucleo.subcategoria_ids) == 106 == nucleo.total_declarado


def test_subcategories_per_category(nucleo):
    real = {
        categoria.id: len(categoria.subcategorias)
        for funcion in nucleo.funciones
        for categoria in funcion.categorias
    }
    assert real == CONTEO_ESPERADO


def test_retired_ids_are_absent(nucleo):
    assert not nucleo.subcategoria_ids & set(HUECOS_REALES)


def test_every_subcategory_has_a_title(nucleo):
    vacios = [
        sub.id
        for funcion in nucleo.funciones
        for categoria in funcion.categorias
        for sub in categoria.subcategorias
        if not sub.titulo.strip()
    ]
    assert vacios == []


# -- cobertura de implementacion ----------------------------------------------------


def test_coverage_counts_distinct_subcategories():
    methodology = load_methodology(METHODOLOGY_DIR)
    cobertura = methodology.cobertura_implementacion()

    declaradas = {s for c in methodology.criterios.values() for s in c.subcategorias}
    assert cobertura.subcategorias_cubiertas == len(declaradas)
    assert cobertura.subcategorias_totales == 106
    assert cobertura.ratio == pytest.approx(len(declaradas) / 106)

    # Cada funcion suma su total real, no el numero de criterios.
    assert sum(total for _, total in cobertura.por_funcion.values()) == 106
    for cubiertas, total in cobertura.por_funcion.values():
        assert 0 <= cubiertas <= total


def test_coverage_reports_categories_without_any_criterion():
    """La lista es el indicador legible de que la ampliacion hizo lo que dice."""

    methodology = load_methodology(METHODOLOGY_DIR)
    cobertura = methodology.cobertura_implementacion()

    con_criterio = {
        s.rsplit("-", 1)[0] for c in methodology.criterios.values() for s in c.subcategorias
    }
    assert (
        set(cobertura.categorias_sin_criterio)
        == set(methodology.nucleo_csf.categoria_ids) - con_criterio
    )


def test_coverage_maps_each_subcategory_to_its_criteria():
    methodology = load_methodology(METHODOLOGY_DIR)
    cobertura = methodology.cobertura_implementacion()

    for subcategoria, ids in cobertura.criterios_por_subcategoria.items():
        assert subcategoria in methodology.nucleo_csf.subcategoria_ids
        assert ids == sorted(ids), "los criterios se listan ordenados y sin duplicar"
        for criterio_id in ids:
            assert subcategoria in methodology.criterios[criterio_id].subcategorias


def test_coverage_is_pure_metadata():
    """Dos llamadas sobre la misma metodologia dan lo mismo: no depende de ninguna evaluacion."""

    methodology = load_methodology(METHODOLOGY_DIR)
    assert methodology.cobertura_implementacion() == methodology.cobertura_implementacion()


def test_compute_handles_an_empty_catalog(nucleo):
    cobertura = compute({}, nucleo)

    assert cobertura.subcategorias_cubiertas == 0
    assert cobertura.ratio == 0.0
    assert len(cobertura.categorias_sin_criterio) == 22
