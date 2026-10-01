from pathlib import Path

import pytest

from app.methodology.loader import MethodologyError, load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


def test_loads_expected_criteria():
    methodology = load_methodology(METHODOLOGY_DIR)

    assert set(methodology.criterios) == {
        "CRI-GV-01",
        "CRI-PR-01",
        "CRI-PR-02",
        "CRI-PR-03",
        "CRI-PR-04",
        "CRI-PR-05",
        "CRI-PR-06",
    }
    assert methodology.settings.ia.alpha == 0.25
    assert methodology.settings.ia.divergencia_maxima == 20
    assert methodology.settings.tier.t2["CRI-GV-01"] == 50


def test_rejects_criterion_with_unknown_evidence_type(tmp_path):
    (tmp_path / "criteria.yml").write_text(
        """
        version: 1
        criterios:
          - id: CRI-X-01
            version: 1
            titulo: "Criterio de prueba"
            tipo: tecnico
            funcion: PR
            categorias: [PR.DS]
            subcategorias: [PR.DS-01]
            peso: 1
            ai_adjustable: false
            evidencias: [tipo.inexistente@1]
            recomendacion: "n/a"
            regla: {}
        """
    )
    (tmp_path / "evidence_types.yml").write_text("version: 1\ntipos: []\n")
    (tmp_path / "settings.yml").write_text(
        """
        version: 1
        ia: { alpha: 0.25, divergencia_maxima: 20, umbral_confianza_documental: 0.6 }
        tier: { t2: {}, t3: {}, t4: {} }
        funciones: { GV: 1, ID: 1, PR: 1, DE: 1, RS: 1, RC: 1 }
        """
    )

    with pytest.raises(MethodologyError, match="tipo.inexistente@1"):
        load_methodology(tmp_path)
