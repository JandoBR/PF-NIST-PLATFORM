"""Esquemas de los catalogos versionados en methodology/*.yml (docs/04 §8, docs/01, docs/03)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.evidence import Modality


class CriterionType(StrEnum):
    TECNICO = "tecnico"
    PROCESO = "proceso"
    MIXTO = "mixto"


class EvidenceTypeDefinition(BaseModel):
    id: str
    version: int
    descripcion: str
    valor_schema: dict
    modalidad_permitida: list[Modality]
    requiere_locator: bool = True
    estado: str = "published"
    publicado: str | None = None
    notas: str | None = None


class CriterionDefinition(BaseModel):
    id: str
    version: int
    titulo: str
    tipo: CriterionType
    funcion: str
    categorias: list[str]
    subcategorias: list[str]
    peso: int
    ai_adjustable: bool
    evidencias: list[str]
    recomendacion: str
    regla: dict


class IASettings(BaseModel):
    alpha: float
    divergencia_maxima: float
    umbral_confianza_documental: float


class TierSettings(BaseModel):
    t2: dict[str, float]
    t3: dict[str, float]
    t4: dict[str, float]


class PlanesSettings(BaseModel):
    #: Un criterio con `final_score` por debajo de esto genera un hallazgo/plan (docs/05 §4).
    umbral_brecha: float = 75.0


class MethodologySettings(BaseModel):
    version: int
    ia: IASettings
    tier: TierSettings
    funciones: dict[str, float]
    planes: PlanesSettings = Field(default_factory=PlanesSettings)


class EvidenceTypesCatalog(BaseModel):
    version: int
    tipos: list[EvidenceTypeDefinition]


class CriteriaCatalog(BaseModel):
    version: int
    criterios: list[CriterionDefinition]
