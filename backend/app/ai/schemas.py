"""Contrato de salida de U1 — extraccion documental (docs/05 §2.2), validado estrictamente."""

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
