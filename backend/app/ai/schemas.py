"""Contratos de salida de IA (docs/05 §2.2 U1, §3.1 U2, §4.1 U3), validados estrictamente."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Cita(BaseModel):
    pagina: int | None = None
    seccion: str | None = None
    fragmento: str


class ExtractedClaim(BaseModel):
    tipo: str
    encontrado: bool
    contenido: dict = Field(default_factory=dict)
    cita: Cita | None = None
    #: 0.0-1.0. Un `NaN`/`Infinity` que `json.loads` acepta no es una confianza utilizable.
    confianza: float = Field(default=0.0, ge=0.0, le=1.0)


class ExtractionResponse(BaseModel):
    afirmaciones: list[ExtractedClaim] = Field(default_factory=list)


class AdjustmentResponse(BaseModel):
    """U2 — ajuste contextual acotado (docs/05 §3.1)."""

    criterion_id: str
    puntaje_base_recibido: float = Field(ge=0.0, le=100.0)
    puntaje_propuesto: float = Field(ge=0.0, le=100.0)
    justificacion: str
    evidencias_referenciadas: list[str] = Field(default_factory=list)
    confianza: float = Field(default=0.0, ge=0.0, le=1.0)


class PlanContentResponse(BaseModel):
    """U3 — contenido narrativo de un plan (docs/05 §4.1).

    La prioridad NO viene de aqui: la decide `app/recommendations/plans.py` a partir de la
    severidad del hallazgo (determinismo primero); la IA solo redacta objetivo/pasos/verificacion.
    """

    titulo: str
    objetivo: str
    pasos: list[str] = Field(default_factory=list)
    verificacion: str
    dependencias: list[str] = Field(default_factory=list)
    #: Lo fija `generate_plan_content`: la IA no decide si el contenido es suyo o la plantilla.
    generado_por: str = "plantilla"
