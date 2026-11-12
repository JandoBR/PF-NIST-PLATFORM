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
    #: El ajuste de IA se intento pero no fue usable (R5/J4, docs/01 §5.3, docs/05 §3.3):
    #: `final_score` se queda igual a `base_score`, nunca se inventa un resultado.
    degradado: bool = False


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
    #: Cobertura por debajo de `cobertura.umbral_provisional`: el puntaje no es representativo
    #: (docs/01 §7). `None` si no hay puntaje o cobertura que juzgar.
    provisional: bool = False


class SiguienteNivel(BaseModel):
    """Avance hacia el primer nivel por encima del piso del Tier (docs/01 §8.3, T7)."""

    nivel: int
    cumplidos: int
    total: int


class TierEstimate(BaseModel):
    """Estimacion de Tier organizacional (docs/01 §8): piso confirmado y techo posible."""

    tier: int | None
    nombre: str | None
    provisional: bool
    estimable: bool
    justificacion: str
    faltantes: list[str] = []
    #: Mayor nivel alcanzable si los requisitos desconocidos se cumplieran (T7). `None` en
    #: estimaciones viejas o cuando el Tier no es estimable; la UI muestra solo el piso.
    techo: int | None = None
    #: Criterios desconocidos (sin evidencia suficiente) que impiden confirmar el techo.
    faltan_para_techo: list[str] = []
    siguiente_nivel: SiguienteNivel | None = None
