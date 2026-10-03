"""Agregacion jerarquica, cobertura y promedio global (docs/01 §6-§7, reglas A1-A6)."""

from __future__ import annotations

from collections import defaultdict

from app.evaluation.schemas import SCORING_STATES, Aggregate, CriterionResult, Estado, Nivel
from app.methodology.loader import Methodology


def is_provisional(score: float | None, cobertura: float | None, umbral: float) -> bool:
    """Un puntaje con cobertura baja es provisional (docs/01 §7: 80/100 con 30% de cobertura)."""

    return score is not None and cobertura is not None and cobertura < umbral


def _weighted_aggregate(
    nivel: Nivel,
    ref: str,
    weighted: list[tuple[CriterionResult, float]],
    umbral_provisional: float,
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
        provisional=is_provisional(score, cobertura, umbral_provisional),
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
        _weighted_aggregate(
            Nivel.SUBCATEGORIA,
            subcategoria,
            weighted,
            methodology.settings.cobertura.umbral_provisional,
        )
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
        _weighted_aggregate(
            Nivel.CATEGORIA,
            categoria,
            weighted,
            methodology.settings.cobertura.umbral_provisional,
        )
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
        _weighted_aggregate(
            Nivel.FUNCION, funcion, weighted, methodology.settings.cobertura.umbral_provisional
        )
        for funcion, weighted in sorted(by_funcion.items())
    ]


def aggregate_global(methodology: Methodology, funcion_aggregates: list[Aggregate]) -> Aggregate:
    """Global = promedio ponderado de las funciones con puntaje (A6: sin ninguna, es None); la
    cobertura se calcula sobre los criterios, no sobre las funciones."""

    pesos = methodology.settings.funciones
    con_score = [a for a in funcion_aggregates if a.score is not None]

    peso_total = sum(pesos.get(a.ref, 1.0) for a in con_score)
    score = (
        sum(a.score * pesos.get(a.ref, 1.0) for a in con_score) / peso_total
        if peso_total > 0
        else None
    )

    conteo_estados: dict[str, int] = defaultdict(int)
    for aggregate in funcion_aggregates:
        for estado, count in aggregate.conteo_estados.items():
            conteo_estados[estado] += count

    # Cobertura de evidencia (docs/01 §7): criterios aplicables con puntaje / criterios aplicables,
    # sobre todos los criterios (cada uno pertenece a una sola funcion, asi que sumar los conteos de
    # las funciones no duplica). No es el promedio de las coberturas por funcion: eso pesaba igual
    # una funcion de 3 criterios que una de 6.
    aplicables = sum(n for estado, n in conteo_estados.items() if estado != Estado.NO_APLICABLE)
    puntuables = sum(conteo_estados.get(estado.value, 0) for estado in SCORING_STATES)
    cobertura = puntuables / aplicables if aplicables else None

    return Aggregate(
        nivel=Nivel.GLOBAL,
        ref="global",
        score=round(score, 2) if score is not None else None,
        cobertura=round(cobertura, 4) if cobertura is not None else None,
        conteo_estados=dict(conteo_estados),
        provisional=is_provisional(
            round(score, 2) if score is not None else None,
            round(cobertura, 4) if cobertura is not None else None,
            methodology.settings.cobertura.umbral_provisional,
        ),
    )
