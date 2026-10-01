"""Cache de extraccion por hash de prompt (docs/04 §2, docs/05 §7: evitar pagar dos veces
por el mismo chunk). Sin Redis todavia, se persiste en disco; la clave ya es estable por
contenido asi que migrar a Redis despues es solo cambiar el backend de almacenamiento.

El degradado (`None`) nunca se cachea: si se agrega una API key mas tarde, no debe quedar
atascado repitiendo el resultado vacio de cuando no habia IA configurada.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ai.client import AIClient

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "ai_extraction"


class CachingAIClient:
    """Envuelve cualquier `AIClient` real; las llamadas con el mismo prompt no repiten la red."""

    def __init__(self, inner: AIClient, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
        self._inner = inner
        self._cache_dir = cache_dir

    def _cache_file(self, system_prompt: str, user_prompt: str) -> Path:
        key = hashlib.sha256(f"{system_prompt}\n---\n{user_prompt}".encode()).hexdigest()
        return self._cache_dir / f"{key}.json"

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        cache_file = self._cache_file(system_prompt, user_prompt)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        result = self._inner.complete_json(system_prompt, user_prompt)
        if result is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(result), encoding="utf-8")
        return result
