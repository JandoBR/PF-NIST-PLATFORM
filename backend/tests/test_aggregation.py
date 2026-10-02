from pathlib import Path

import pytest

from app.evaluation import aggregation, tier
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def _result(criterion_id, estado, score=None):
    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=estado,
        base_score=score,
        final_score=score,
        explanation="fixture",
    )


def test_categoria_aggregate_is_weighted_by_criterion_peso(methodology):
    # PR.DS agrupa CRI-PR-01 (peso 5) y CRI-PR-02 (peso 5); CRI-PR-05 tambien pesa 3 sobre PR.DS.
    results = [
        _result("CRI-PR-01", Estado.EVALUADO, 100),
        _result("CRI-PR-02", Estado.EVALUADO, 0),
        _result("CRI-PR-05", Estado.EVALUADO, 100),
    ]
    categorias = {a.ref: a for a in aggregation.aggregate_by_categoria(methodology, results)}

    # (100*5 + 0*5 + 100*3) / (5+5+3) = 800/13
    assert categorias["PR.DS"].score == pytest.approx(800 / 13, rel=1e-3)
    assert categorias["PR.DS"].cobertura == 1.0


def test_no_aplicable_excluded_from_denominator_entirely(methodology):
    results = [
        _result("CRI-PR-01", Estado.EVALUADO, 100),
        _result("CRI-PR-02", Estado.NO_APLICABLE),
    ]
    categorias = {a.ref: a for a in aggregation.aggregate_by_categoria(methodology, results)}

    # PR.DS.01 solo tiene CRI-PR-01; no_aplicable no resta cobertura (A2).
    assert categorias["PR.DS"].score == 100
    assert categorias["PR.DS"].cobertura == 1.0


def test_evidencia_insuficiente_reduces_coverage_but_not_score(methodology):
    results = [
        _result("CRI-PR-01", Estado.EVALUADO, 100),
        _result("CRI-PR-02", Estado.EVIDENCIA_INSUFICIENTE),
    ]
    categorias = {a.ref: a for a in aggregation.aggregate_by_categoria(methodology, results)}

    # score solo promedia lo evaluado (CRI-PR-01=100); cobertura cae a 1/2 (A3).
    assert categorias["PR.DS"].score == 100
    assert categorias["PR.DS"].cobertura == 0.5


def test_categoria_not_evaluable_when_all_results_insufficient(methodology):
    results = [_result("CRI-PR-01", Estado.EVIDENCIA_INSUFICIENTE)]
    categorias = {a.ref: a for a in aggregation.aggregate_by_categoria(methodology, results)}

    assert categorias["PR.DS"].score is None  # A5: "no evaluable"
    assert categorias["PR.DS"].cobertura == 0.0


def test_global_excludes_functions_with_no_score(methodology):
    results = [_result("CRI-PR-01", Estado.EVALUADO, 80)]
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    glob = aggregation.aggregate_global(methodology, funciones)

    assert glob.score == 80  # unica funcion con resultado (PR)


def test_global_is_none_when_everything_insufficient(methodology):
    results = [_result("CRI-PR-01", Estado.EVIDENCIA_INSUFICIENTE)]
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    glob = aggregation.aggregate_global(methodology, funciones)

    assert glob.score is None  # A6


def test_tier_is_not_estimable_without_t2_indicator_criteria(methodology):
    results = [_result("CRI-PR-01", Estado.EVALUADO, 100)]
    estimate = tier.estimate_tier(methodology.settings.tier, results)

    assert estimate.estimable is False
    assert estimate.tier is None


def test_tier_is_partial_when_only_one_of_three_t2_indicators_exists(methodology):
    # CRI-GV-01 ya esta en el catalogo; CRI-GV-02 y CRI-ID-03 todavia no tienen adaptador.
    results = [_result("CRI-GV-01", Estado.EVALUADO, 100)]
    estimate = tier.estimate_tier(methodology.settings.tier, results)

    assert estimate.estimable is True
    assert estimate.tier == 1
    assert any("CRI-GV-02" in f for f in estimate.faltantes)
    assert any("CRI-ID-03" in f for f in estimate.faltantes)


def test_tier_2_met_with_minimum_indicators():
    from app.methodology.schemas import TierSettings

    settings = TierSettings(
        t2={"CRI-GV-01": 50, "CRI-GV-02": 50, "CRI-ID-03": 50},
        t3={"CRI-GV-01": 75},
        t4={},
    )
    results = [
        _result("CRI-GV-01", Estado.EVALUADO, 60),
        _result("CRI-GV-02", Estado.EVALUADO, 50),
        _result("CRI-ID-03", Estado.EVALUADO, 70),
    ]
    estimate = tier.estimate_tier(settings, results)

    assert estimate.tier == 2
    assert estimate.provisional is False
    assert "CRI-GV-01" in estimate.faltantes[0]


def test_tier_marked_provisional_when_indicator_has_insufficient_evidence():
    from app.methodology.schemas import TierSettings

    settings = TierSettings(
        t2={"CRI-GV-01": 50, "CRI-GV-02": 50, "CRI-ID-03": 50},
        t3={},
        t4={},
    )
    results = [
        _result("CRI-GV-01", Estado.EVALUADO, 60),
        _result("CRI-GV-02", Estado.EVALUADO, 60),
        _result("CRI-ID-03", Estado.EVIDENCIA_INSUFICIENTE),
    ]
    estimate = tier.estimate_tier(settings, results)

    assert estimate.provisional is True


def test_low_coverage_marks_score_provisional(methodology):
    # 1 de 3 criterios con evidencia suficiente en PR -> cobertura 33% < umbral (50%).
    results = [
        _result("CRI-PR-01", Estado.EVALUADO, 100),
        _result("CRI-PR-02", Estado.EVIDENCIA_INSUFICIENTE),
        _result("CRI-PR-03", Estado.EVIDENCIA_INSUFICIENTE),
    ]
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    pr = next(a for a in funciones if a.ref == "PR")
    assert pr.cobertura == pytest.approx(1 / 3, abs=1e-3)
    assert pr.provisional is True
    assert aggregation.aggregate_global(methodology, funciones).provisional is True


def test_full_coverage_is_not_provisional(methodology):
    results = [
        _result("CRI-PR-01", Estado.EVALUADO, 80),
        _result("CRI-PR-02", Estado.EVALUADO, 60),
    ]
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    assert not any(a.provisional for a in funciones)
    assert aggregation.aggregate_global(methodology, funciones).provisional is False


def test_no_score_is_never_provisional(methodology):
    funciones = aggregation.aggregate_by_funcion(
        methodology, [_result("CRI-PR-01", Estado.EVIDENCIA_INSUFICIENTE)]
    )
    assert funciones[0].score is None and funciones[0].provisional is False
