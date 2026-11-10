"""Cliente de IA (docs/05 §5, §7): una sola interfaz interna para que el resto del
sistema nunca dependa de DeepSeek directamente. Si la IA desaparece, el sistema sigue
funcionando con `S = B` y extraccion documental deshabilitada (D9, principio operativo).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

from app.ai.calllog import log_call

logger = logging.getLogger("app.ai.client")

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2
#: Espera antes del reintento n (1-based): BACKOFF_BASE_SECONDS * 2**(n-1) -> 1 s, 2 s (docs/05 §5).
BACKOFF_BASE_SECONDS = 1.0


class AIClient(Protocol):
    """Cualquier implementacion recibe un prompt de sistema/usuario y devuelve JSON o None.

    `None` significa "degradado": el caller debe continuar sin inventar un resultado
    (J4/R5 en docs/01 y docs/05), nunca propagar la excepcion hacia la evaluacion.
    """

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None: ...


@lru_cache(maxsize=1)
def _errores_transitorios() -> tuple[type[Exception], ...]:
    """Excepciones del SDK que si merecen un reintento (docs/05 §5)."""

    from openai import APIConnectionError, APITimeoutError, RateLimitError

    return (APITimeoutError, APIConnectionError, RateLimitError)


def _reintentable(exc: Exception) -> bool:
    """Timeout, conexion, 429 y 5xx: lo unico que puede cambiar en el siguiente intento.

    Un 400/401/402/403/404/422 no se arregla repitiendo la misma peticion: cada reintento solo
    gasta cuota y retrasa la degradacion que de todos modos va a ocurrir.
    """

    from openai import APIStatusError

    if isinstance(exc, _errores_transitorios()):
        return True
    return isinstance(exc, APIStatusError) and (exc.status_code == 429 or exc.status_code >= 500)


class DeepSeekClient:
    """Implementacion real: SDK `openai` apuntando a la API de DeepSeek (docs/05 §5)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sleep = sleep
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY no configurada")

        from openai import OpenAI  # import diferido: no requerido si no hay API key

        base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        #: Se incluye en la clave de cache junto al modelo: cambiar de endpoint cambia el resultado.
        self.base_url = base_url

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        inicio = time.monotonic()
        motivo = "sin_intentos"
        intentos = 0
        for intento in range(MAX_RETRIES + 1):
            if intento > 0:
                self._sleep(BACKOFF_BASE_SECONDS * 2 ** (intento - 1))
            intentos += 1
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=2000,
                )
            except Exception as exc:  # error de red o de la API: reintentar solo lo transitorio
                motivo = f"error:{type(exc).__name__}"
                if not _reintentable(exc):
                    break
                continue

            # docs/09: la API devuelve `usage` en cada respuesta; sin loguearlo, el consumo real
            # (tokens) es invisible desde el proceso -- solo se veria en la plataforma de DeepSeek,
            # y alli depende de que key/cuenta sea la que realmente se uso.
            usage = getattr(response, "usage", None)
            tokens = None
            if usage is not None:
                tokens = {
                    "prompt": usage.prompt_tokens,
                    "completion": usage.completion_tokens,
                    "total": usage.total_tokens,
                }
                logger.info(
                    "DeepSeek %s tokens: prompt=%s completion=%s total=%s",
                    self.model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                )

            content = response.choices[0].message.content
            if not content:
                motivo = "respuesta_vacia"
                continue
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                motivo = "json_invalido"
                continue
            log_call(
                resultado="ok",
                modelo=self.model,
                intentos=intentos,
                duracion_ms=round((time.monotonic() - inicio) * 1000),
                tokens=tokens,
            )
            return parsed

        log_call(
            resultado="degradado",
            motivo=motivo,
            modelo=self.model,
            intentos=intentos,
            duracion_ms=round((time.monotonic() - inicio) * 1000),
        )
        return None


class FakeAIClient:
    """Doble de prueba determinista: NO es un extractor real, solo prueba el contrato de U1/U2
    sin red ni API key. Las respuestas se indexan por una palabra clave del prompt de usuario.
    """

    def __init__(self, responses_by_keyword: dict[str, dict]) -> None:
        self._responses = responses_by_keyword

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        for keyword, response in self._responses.items():
            if keyword in user_prompt:
                return response
        return None


class NullAIClient:
    """IA no configurada: siempre degrada. Usado cuando no hay DEEPSEEK_API_KEY (docs/05 §7)."""

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        return None


def build_default_client() -> AIClient:
    """Fabrica usada por la CLI/orquestacion: real (con cache) si hay API key, degradado si no."""

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return NullAIClient()

    from app.ai.cache import CachingAIClient  # evita import circular a nivel de modulo

    return CachingAIClient(DeepSeekClient(api_key=api_key))


def describe_client(client: AIClient) -> str:
    """Texto para logs: distingue "IA real" de "sin key, degradando en silencio" (docs/09 §18).

    Un worker que recibe `ai_requested=True` pero no ve la API key cae en `NullAIClient` y no
    hace ninguna llamada de red -- sin este log, eso es indistinguible de "todo funciono pero
    salio de cache"."""

    if isinstance(client, NullAIClient):
        return "no configurada (sin DEEPSEEK_API_KEY; degrada a S=B, sin llamadas ni costo)"
    return "activa (DeepSeek)"
