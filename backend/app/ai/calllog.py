"""Registro estructurado por llamada de IA (docs/05 §5, docs/11 OP-12).

Cada llamada deja una linea de log JSON con: paso (U1/U2/U3), version de prompt, criterio o
documento, resultado (`ok`/`cache`/`degradado`), intentos, duracion y tokens. Sirve para auditar
costo y comportamiento sin leer la plataforma del proveedor (docs/09 §17-§18).

El cliente no conoce el paso que lo llama, asi que el contexto viaja en un `ContextVar` que cada
caller (extraccion, ajuste, planes) fija con `call_context(...)`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("app.ai.calls")

_context: ContextVar[dict[str, Any] | None] = ContextVar("ai_call_context", default=None)


@contextmanager
def call_context(**fields: Any) -> Iterator[None]:
    """Fija `paso`, `prompt_version`, `criterion_id`, `doc_id`... para las llamadas del bloque."""

    token = _context.set({**(_context.get() or {}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict[str, Any]:
    return dict(_context.get() or {})


def log_call(*, resultado: str, **fields: Any) -> dict[str, Any]:
    """Escribe y devuelve el registro (devolverlo facilita probarlo)."""

    record = {**current_context(), "resultado": resultado, **fields}
    logger.info("ai_call %s", json.dumps(record, ensure_ascii=False, default=str))
    return record
