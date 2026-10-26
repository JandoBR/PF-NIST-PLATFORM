"""Esquema e ingesta de eventos (docs/06 §2). Pipeline stateless (docs/04 §3.1, P1): parsear un
archivo JSONL no requiere nada mas que el archivo mismo."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class SurveillanceError(Exception):
    """JSONL de eventos invalido: se falla rapido con la linea exacta, no se ingiere a medias."""


class RawEvent(BaseModel):
    event_id: str
    event_time: datetime
    tipo: str
    recurso: str
    scope: str
    actor: str | None = None
    detalle: dict = Field(default_factory=dict)
    fuente: str | None = None


def load_events_jsonl(path: Path) -> list[RawEvent]:
    """Un evento por linea (docs/06 §2). `event_time` es tiempo de evento, no de lectura."""

    events: list[RawEvent] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SurveillanceError(f"{path}:{line_number}: JSON invalido: {exc}") from exc
            try:
                event = RawEvent.model_validate(raw)
            except ValidationError as exc:
                raise SurveillanceError(f"{path}:{line_number}: evento invalido: {exc}") from exc
            # Un `event_time` sin zona se interpreta como UTC. Sin normalizar, ordenar una mezcla
            # de naive y aware lanza TypeError y tumba la ingesta entera.
            event.event_time = (
                event.event_time.replace(tzinfo=UTC)
                if event.event_time.tzinfo is None
                else event.event_time.astimezone(UTC)
            )
            events.append(event)

    return sorted(events, key=lambda e: e.event_time)
