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
    return {
        "methodology_version": methodology.methodology_version,
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
