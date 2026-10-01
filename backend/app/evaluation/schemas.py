"""Resultado de un criterio y agregados (docs/01-modelo-de-evaluacion.md §3, §6)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Estado(StrEnum):
    EVALUADO = "evaluado"
    NO_IMPLEMENTADO = "no_implementado"
    EVIDENCIA_INSUFICIENTE = "evidencia_insuficiente"
    NO_APLICABLE = "no_aplicable"
    ERROR = "error"


#: Estados que aportan puntaje y entran al promedio ponderado (docs/01 §3, A1).
SCORING_STATES = (Estado.EVALUADO, Estado.NO_IMPLEMENTADO)


class CriterionResult(BaseModel):
    criterion_id: str
    criterion_version: int
    estado: Estado
    base_score: float | None = None
    final_score: float | None = None
    explanation: str
    evidence_ids: list[str] = []


class Nivel(StrEnum):
    SUBCATEGORIA = "subcategoria"
    CATEGORIA = "categoria"
    FUNCION = "funcion"
    GLOBAL = "global"


class Aggregate(BaseModel):
    """Puntaje y cobertura agregados a un nivel de la jerarquia (docs/01 §6-§7)."""

    nivel: Nivel
    ref: str
    score: float | None
    cobertura: float | None
    conteo_estados: dict[str, int]


class TierEstimate(BaseModel):
    """Estimacion de Tier organizacional (docs/01 §8)."""

    tier: int | None
    nombre: str | None
    provisional: bool
    estimable: bool
    justificacion: str
    faltantes: list[str] = []
