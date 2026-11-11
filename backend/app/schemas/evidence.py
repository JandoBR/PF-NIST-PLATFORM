"""Contrato de instancia de evidencia (docs/01-modelo-de-evaluacion.md §2.2)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Modality(StrEnum):
    DECLARADA = "declarada"
    DOCUMENTAL = "documental"
    OPERATIVA = "operativa"
    CONTEXTO = "contexto"


class Locator(BaseModel):
    """Ubicacion exacta de la observacion dentro de su fuente."""

    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    page: int | None = None
    section: str | None = None
    event_id: str | None = None


class Segmento(BaseModel):
    """Tramo de un chunk agrupado: rango de caracteres dentro de su texto y locator de la
    seccion/pagina que lo origino (docs/05 §2.1)."""

    inicio: int
    fin: int
    locator: Locator

    model_config = {"frozen": True}


class EvidenceInstance(BaseModel):
    """Observacion normalizada, append-only (docs/01 §2.2)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type_id: str
    type_version: int
    subject_type: str
    subject_ref: str
    scope: str
    value: Any
    source_id: str
    locator: Locator
    observed_at: datetime
    modality: Modality
    limitations: str | None = None
    created_by: str

    model_config = {"frozen": True}
