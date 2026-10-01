"""Contratos de salida de IA (docs/05 §2.2 U1, §3.1 U2), validados estrictamente."""

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
    confianza: float = 0.0


class ExtractionResponse(BaseModel):
    afirmaciones: list[ExtractedClaim] = Field(default_factory=list)


class AdjustmentResponse(BaseModel):
    """U2 — ajuste contextual acotado (docs/05 §3.1)."""

    criterion_id: str
    puntaje_base_recibido: float
    puntaje_propuesto: float
    justificacion: str
    evidencias_referenciadas: list[str] = Field(default_factory=list)
    confianza: float = 0.0
