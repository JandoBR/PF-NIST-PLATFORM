"""Agregacion jerarquica, cobertura y promedio global (docs/01 §6-§7, reglas A1-A6)."""

from __future__ import annotations

from collections import defaultdict

from app.evaluation.schemas import SCORING_STATES, Aggregate, CriterionResult, Estado, Nivel
from app.methodology.loader import Methodology


def _weighted_aggregate(
    nivel: Nivel, ref: str, weighted: list[tuple[CriterionResult, float]]
) -> Aggregate:
    """Promedio ponderado por `peso` sobre los resultados que aportan puntaje (A1-A3)."""

    conteo_estados: dict[str, int] = defaultdict(int)
    for result, _ in weighted:
        conteo_estados[result.estado.value] += 1

    aplicables = [(r, w) for r, w in weighted if r.estado != Estado.NO_APLICABLE]  # A2
    puntuables = [(r, w) for r, w in aplicables if r.estado in SCORING_STATES]  # A1, A3

    peso_total = sum(w for _, w in puntuables)
    score = (
        sum((r.final_score or 0) * w for r, w in puntuables) / peso_total
        if peso_total > 0
        else None
    )
    cobertura = len(puntuables) / len(aplicables) if aplicables else None

    return Aggregate(
        nivel=nivel,
        ref=ref,
        score=round(score, 2) if score is not None else None,
        cobertura=round(cobertura, 4) if cobertura is not None else None,
        conteo_estados=dict(conteo_estados),
    )


def aggregate_by_subcategoria(
    methodology: Methodology, results: list[CriterionResult]
) -> list[Aggregate]:
    """Una subcategoria agrega los criterios que la listan en `subcategorias`."""

    by_subcategoria: dict[str, list[tuple[CriterionResult, float]]] = defaultdict(list)
    for result in results:
        criterio = methodology.criterios[result.criterion_id]
        for subcategoria in criterio.subcategorias:
            by_subcategoria[subcategoria].append((result, criterio.peso))

    return [
        _weighted_aggregate(Nivel.SUBCATEGORIA, subcategoria, weighted)
        for subcategoria, weighted in sorted(by_subcategoria.items())
    ]


def aggregate_by_categoria(
    methodology: Methodology, results: list[CriterionResult]
) -> list[Aggregate]:
    """Una categoria agrega los criterios que la listan en `categorias`, sin duplicar por subcat."""

    by_categoria: dict[str, list[tuple[CriterionResult, float]]] = defaultdict(list)
    for result in results:
        criterio = methodology.criterios[result.criterion_id]
        for categoria in criterio.categorias:
            by_categoria[categoria].append((result, criterio.peso))

    return [
        _weighted_aggregate(Nivel.CATEGORIA, categoria, weighted)
        for categoria, weighted in sorted(by_categoria.items())
    ]


def aggregate_by_funcion(
    methodology: Methodology, results: list[CriterionResult]
) -> list[Aggregate]:
    by_funcion: dict[str, list[tuple[CriterionResult, float]]] = defaultdict(list)
    for result in results:
        criterio = methodology.criterios[result.criterion_id]
        by_funcion[criterio.funcion].append((result, criterio.peso))

    return [
        _weighted_aggregate(Nivel.FUNCION, funcion, weighted)
        for funcion, weighted in sorted(by_funcion.items())
    ]


def aggregate_global(
    methodology: Methodology, funcion_aggregates: list[Aggregate]
) -> Aggregate:
    """Global = promedio ponderado de las funciones con puntaje (A6: sin ninguna, es None)."""

    pesos = methodology.settings.funciones
    con_score = [a for a in funcion_aggregates if a.score is not None]

    peso_total = sum(pesos.get(a.ref, 1.0) for a in con_score)
    score = (
        sum(a.score * pesos.get(a.ref, 1.0) for a in con_score) / peso_total
        if peso_total > 0
        else None
    )

    con_cobertura = [a for a in funcion_aggregates if a.cobertura is not None]
    cobertura = (
        sum(a.cobertura for a in con_cobertura) / len(con_cobertura) if con_cobertura else None
    )

    conteo_estados: dict[str, int] = defaultdict(int)
    for aggregate in funcion_aggregates:
        for estado, count in aggregate.conteo_estados.items():
            conteo_estados[estado] += count

    return Aggregate(
        nivel=Nivel.GLOBAL,
        ref="global",
        score=round(score, 2) if score is not None else None,
        cobertura=round(cobertura, 4) if cobertura is not None else None,
        conteo_estados=dict(conteo_estados),
    )
