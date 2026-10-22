import shutil
from pathlib import Path

import pytest

from app.methodology.loader import MethodologyError, load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"

_SETTINGS_MINIMO = """
version: 1
ia: { alpha: 0.25, divergencia_maxima: 20, umbral_confianza_documental: 0.6 }
tier: { t2: {}, t3: {}, t4: {} }
funciones: { GV: 1, ID: 1, PR: 1, DE: 1, RS: 1, RC: 1 }
"""


def _metodologia_minima(tmp_path: Path, criterio: str) -> Path:
    """Metodologia de un solo criterio, con el nucleo CSF real (106 subcategorias).

    El nucleo se copia en vez de inventarse: es el catalogo contra el que se valida el
    mapeo a NIST, y una copia reducida dejaria pasar los ids que el test quiere atrapar.
    """

    (tmp_path / "criteria.yml").write_text(f"version: 1\ncriterios:\n{criterio}")
    (tmp_path / "evidence_types.yml").write_text("version: 1\ntipos: []\n")
    (tmp_path / "settings.yml").write_text(_SETTINGS_MINIMO)
    shutil.copy(METHODOLOGY_DIR / "csf_subcategories.yml", tmp_path / "csf_subcategories.yml")
    return tmp_path


def _criterio(**campos: str) -> str:
    base = {
        "id": "CRI-PR-99",
        "version": "1",
        "titulo": '"Criterio de prueba"',
        "tipo": "tecnico",
        "funcion": "PR",
        "categorias": "[PR.DS]",
        "subcategorias": "[PR.DS-01]",
        "peso": "1",
        "ai_adjustable": "false",
        "evidencias": "[]",
        "recomendacion": '"n/a"',
        "regla": "{}",
    }
    base.update(campos)
    campos_yaml = "\n".join(f"    {k}: {v}" for k, v in base.items())
    return f"  -{campos_yaml[3:]}\n"


def test_loads_expected_criteria():
    methodology = load_methodology(METHODOLOGY_DIR)

    assert set(methodology.criterios) == {
        "CRI-GV-01",
        "CRI-GV-02",
        "CRI-GV-03",
        "CRI-GV-04",
        "CRI-ID-01",
        "CRI-ID-02",
        "CRI-ID-03",
        "CRI-ID-04",
        "CRI-PR-01",
        "CRI-PR-02",
        "CRI-PR-03",
        "CRI-PR-04",
        "CRI-PR-05",
        "CRI-PR-06",
        "CRI-DE-01",
        "CRI-DE-02",
        "CRI-DE-03",
        "CRI-RS-01",
        "CRI-RS-02",
        "CRI-RS-03",
        "CRI-RC-01",
        "CRI-RC-02",
        "CRI-RC-03",
    }
    assert methodology.settings.ia.alpha == 0.25
    assert methodology.settings.ia.divergencia_maxima == 20
    assert methodology.settings.tier.t2["CRI-GV-01"] == 50


def test_rejects_criterion_with_unknown_evidence_type(tmp_path):
    _metodologia_minima(tmp_path, _criterio(evidencias="[tipo.inexistente@1]"))

    with pytest.raises(MethodologyError, match="tipo.inexistente@1"):
        load_methodology(tmp_path)


# -- mapeo a NIST: antes se cargaba en silencio (AMP-04, docs/01 §7) -----------------


def test_rejects_unknown_subcategory(tmp_path):
    _metodologia_minima(tmp_path, _criterio(subcategorias="[PR.DS-99]"))

    with pytest.raises(MethodologyError, match="subcategoria CSF desconocida 'PR.DS-99'"):
        load_methodology(tmp_path)


def test_rejects_subcategory_from_a_real_numbering_gap(tmp_path):
    """`PR.DS-03` parece valida pero NIST la retiro en la v1.1; no esta en el nucleo."""

    _metodologia_minima(tmp_path, _criterio(subcategorias="[PR.DS-03]"))

    with pytest.raises(MethodologyError, match="subcategoria CSF desconocida 'PR.DS-03'"):
        load_methodology(tmp_path)


def test_rejects_unknown_category(tmp_path):
    _metodologia_minima(tmp_path, _criterio(categorias="[PR.XX]", subcategorias="[]"))

    with pytest.raises(MethodologyError, match="categoria CSF desconocida 'PR.XX'"):
        load_methodology(tmp_path)


def test_rejects_category_from_another_function(tmp_path):
    _metodologia_minima(
        tmp_path, _criterio(funcion="GV", categorias="[PR.DS]", subcategorias="[PR.DS-01]")
    )

    with pytest.raises(MethodologyError, match="pertenece a otra funcion"):
        load_methodology(tmp_path)


def test_rejects_subcategory_whose_category_is_not_declared(tmp_path):
    _metodologia_minima(tmp_path, _criterio(subcategorias="[PR.DS-01, PR.AA-01]"))

    with pytest.raises(MethodologyError, match="no lista su categoria 'PR.AA'"):
        load_methodology(tmp_path)


def test_current_catalog_maps_cleanly_onto_nist():
    """Las subcategorias en uso existen y cuelgan de la categoria y funcion correctas.

    No fija el conteo: cada oleada del catalogo lo mueve y el numero vive en
    `cobertura_implementacion` (test_csf_core_catalog.py), no replicado aca.
    """

    methodology = load_methodology(METHODOLOGY_DIR)
    nucleo = methodology.nucleo_csf

    assert len(nucleo.subcategoria_ids) == nucleo.total_declarado == 106
    assert len(nucleo.categoria_ids) == 22

    declaradas = {s for c in methodology.criterios.values() for s in c.subcategorias}
    assert declaradas <= nucleo.subcategoria_ids
    assert len(declaradas) == methodology.cobertura_implementacion().subcategorias_cubiertas
