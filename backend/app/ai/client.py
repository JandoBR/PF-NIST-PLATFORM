"""Cliente de IA (docs/05 §5, §7): una sola interfaz interna para que el resto del
sistema nunca dependa de DeepSeek directamente. Si la IA desaparece, el sistema sigue
funcionando con `S = B` y extraccion documental deshabilitada (D9, principio operativo).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol

logger = logging.getLogger("app.ai.client")

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2


class AIClient(Protocol):
    """Cualquier implementacion recibe un prompt de sistema/usuario y devuelve JSON o None.

    `None` significa "degradado": el caller debe continuar sin inventar un resultado
    (J4/R5 en docs/01 y docs/05), nunca propagar la excepcion hacia la evaluacion.
    """

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None: ...


class DeepSeekClient:
    """Implementacion real: SDK `openai` apuntando a la API de DeepSeek (docs/05 §5)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY no configurada")

        from openai import OpenAI  # import diferido: no requerido si no hay API key

        base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        for _ in range(MAX_RETRIES + 1):
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
            except Exception:  # error transitorio: reintentar, nunca propagar (docs/05 §5)
                continue

            # docs/09: la API devuelve `usage` en cada respuesta; sin loguearlo, el consumo real
            # (tokens) es invisible desde el proceso -- solo se veria en la plataforma de DeepSeek,
            # y alli depende de que key/cuenta sea la que realmente se uso.
            usage = getattr(response, "usage", None)
            if usage is not None:
                logger.info(
                    "DeepSeek %s tokens: prompt=%s completion=%s total=%s",
                    self.model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                )

            content = response.choices[0].message.content
            if not content:
                continue
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                continue
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
