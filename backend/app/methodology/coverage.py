"""Cobertura de implementacion del catalogo (AMP-04, docs/01 §7).

Deliberadamente fuera de `app/evaluation/aggregation.py`. Son dos metricas distintas que
docs/01 §7 obliga a no mezclar:

- **Cobertura de evidencia** (`aggregation.py`): por evaluacion. Cuantos criterios aplicables
  llegaron a un estado puntuable. Cambia en cada corrida y decide la marca `provisional`.
- **Cobertura de implementacion** (este modulo): del producto. Que parte del marco NIST tiene
  al menos un criterio. Es funcion pura de `criteria.yml` + `csf_subcategories.yml`, constante
  para una version de metodologia, y no toca ningun puntaje.

Tenerlas en el mismo modulo invitaria a alimentar una con la otra, que es justo el error que
hace ininteligible un valor agregado.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.methodology.schemas import CriterionDefinition, CsfCoreCatalog


@dataclass(frozen=True)
class CoberturaImplementacion:
    subcategorias_cubiertas: int
    subcategorias_totales: int
    ratio: float
    por_funcion: dict[str, tuple[int, int]]
    categorias_sin_criterio: list[str]
    criterios_por_subcategoria: dict[str, list[str]]


def compute(
    criterios: dict[str, CriterionDefinition],
    nucleo: CsfCoreCatalog,
) -> CoberturaImplementacion:
    """Que parte del nucleo de CSF 2.0 tiene al menos un criterio que la evalue."""

    criterios_por_subcategoria: dict[str, list[str]] = {}
    for criterio in sorted(criterios.values(), key=lambda c: c.id):
        for subcategoria in criterio.subcategorias:
            criterios_por_subcategoria.setdefault(subcategoria, []).append(criterio.id)

    cubiertas = set(criterios_por_subcategoria)
    totales = len(nucleo.subcategoria_ids)

    por_funcion: dict[str, tuple[int, int]] = {}
    categorias_sin_criterio: list[str] = []
    for funcion in nucleo.funciones:
        de_la_funcion = 0
        cubiertas_funcion = 0
        for categoria in funcion.categorias:
            ids = {sub.id for sub in categoria.subcategorias}
            de_la_funcion += len(ids)
            cubiertas_categoria = ids & cubiertas
            cubiertas_funcion += len(cubiertas_categoria)
            if not cubiertas_categoria:
                categorias_sin_criterio.append(categoria.id)
        por_funcion[funcion.id] = (cubiertas_funcion, de_la_funcion)

    return CoberturaImplementacion(
        subcategorias_cubiertas=len(cubiertas),
        subcategorias_totales=totales,
        ratio=len(cubiertas) / totales if totales else 0.0,
        por_funcion=por_funcion,
        categorias_sin_criterio=categorias_sin_criterio,
        criterios_por_subcategoria=criterios_por_subcategoria,
    )
