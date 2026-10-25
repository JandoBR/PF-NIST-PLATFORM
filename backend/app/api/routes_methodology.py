"""GET /health, GET /methodology (docs/04 §6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_methodology
from app.methodology.loader import Methodology

router = APIRouter(tags=["methodology"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/methodology")
def get_methodology_catalog(methodology: Methodology = Depends(get_methodology)) -> dict:
    cobertura = methodology.cobertura_implementacion()
    return {
        "methodology_version": methodology.methodology_version,
        "nucleo_csf_version": methodology.nucleo_csf.version,
        # Cobertura DEL CATALOGO: que parte del marco tiene criterio. Metadato del producto,
        # constante para esta version de metodologia. No confundir con la cobertura de
        # evidencia de una evaluacion, que es la que marca un puntaje como provisional
        # (docs/01 §7 obliga a no mezclarlas).
        "cobertura_implementacion": {
            "subcategorias_cubiertas": cobertura.subcategorias_cubiertas,
            "subcategorias_totales": cobertura.subcategorias_totales,
            "ratio": round(cobertura.ratio, 4),
            "categorias_cubiertas": cobertura.categorias_cubiertas,
            "categorias_totales": cobertura.categorias_totales,
            "categorias_completas": cobertura.categorias_completas,
            "categorias_incompletas": cobertura.categorias_incompletas,
            "por_funcion": {f: list(v) for f, v in cobertura.por_funcion.items()},
            "categorias_sin_criterio": cobertura.categorias_sin_criterio,
        },
        "criterios": [
            {
                "id": c.id,
                "version": c.version,
                "titulo": c.titulo,
                "tipo": c.tipo.value,
                "funcion": c.funcion,
                "categorias": c.categorias,
                "subcategorias": c.subcategorias,
                "peso": c.peso,
                "ai_adjustable": c.ai_adjustable,
                "evidencias": c.evidencias,
                "recomendacion": c.recomendacion,
            }
            for c in sorted(methodology.criterios.values(), key=lambda c: c.id)
        ],
        "tipos_evidencia": sorted(methodology.tipos_evidencia),
    }
