"""Cache de extraccion por hash de prompt (docs/04 §2, docs/05 §7: evitar pagar dos veces
por el mismo chunk). Sin Redis todavia, se persiste en disco; la clave ya es estable por
contenido asi que migrar a Redis despues es solo cambiar el backend de almacenamiento.

El degradado (`None`) nunca se cachea: si se agrega una API key mas tarde, no debe quedar
atascado repitiendo el resultado vacio de cuando no habia IA configurada.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from app.ai.calllog import log_call
from app.ai.store import bypass_active

if TYPE_CHECKING:
    from app.ai.client import AIClient

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "ai_extraction"


class CachingAIClient:
    """Envuelve cualquier `AIClient` real; las llamadas con el mismo prompt no repiten la red."""

    def __init__(self, inner: AIClient, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
        self._inner = inner
        self._cache_dir = cache_dir

    def _cache_file(self, system_prompt: str, user_prompt: str) -> Path:
        # El modelo (y la base URL, si el cliente la expone) forma parte del resultado: si cambia
        # `DEEPSEEK_MODEL`, la misma prompt debe ser un miss, no la respuesta del modelo anterior.
        modelo = getattr(self._inner, "model", type(self._inner).__name__)
        base_url = getattr(self._inner, "base_url", "")
        key = hashlib.sha256(
            f"{modelo}\n{base_url}\n{system_prompt}\n---\n{user_prompt}".encode()
        ).hexdigest()
        return self._cache_dir / f"{key}.json"

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        if bypass_active():
            # Votacion de U1 (docs/09 §105): cada corrida tiene que llegar al modelo; si la
            # segunda leyera esta cache, votar seria comparar una respuesta consigo misma.
            return self._inner.complete_json(system_prompt, user_prompt)
        cache_file = self._cache_file(system_prompt, user_prompt)
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = None
            if isinstance(cached, dict):
                log_call(resultado="cache")
                return cached
            # Entrada corrupta o de otro tipo: se trata como miss y se reescribe abajo.

        result = self._inner.complete_json(system_prompt, user_prompt)
        if result is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                dir=self._cache_dir,
                prefix=cache_file.stem,
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as fh:
                json.dump(result, fh)
                temporal = Path(fh.name)
            temporal.replace(cache_file)
        return result
