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
from typing import TYPE_CHECKING, Protocol

from app.ai.calllog import log_call

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("app.ai.client")

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
#: Con razonamiento activo el p90 medido fue 54 s y los chunks que agotan 16k tokens se reintentan
#: a 32k (hasta ~3 min): 60 s mataba respuestas que si iban a llegar (docs/09 §105).
DEFAULT_TIMEOUT_SECONDS = 180
#: Techo del timeout de un reintento por longitud; se duplica junto con `max_tokens`.
MAX_TIMEOUT_SECONDS = 600
#: Techo de tokens por respuesta, no gasto: se factura solo lo generado. `deepseek-flash` es un
#: modelo de razonamiento por defecto y el razonamiento consume el mismo presupuesto que el JSON;
#: con 2000 el JSON quedaba vacio (`finish_reason="length"`, docs/09 §100).
DEFAULT_MAX_TOKENS = 16000
#: Si el primer intento se agota por longitud, el reintento duplica el techo hasta este valor:
#: repetir la misma peticion con el mismo presupuesto da el mismo resultado (docs/09 §100).
MAX_TOKENS_CEILING = 64000
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


def _max_tokens_configurado() -> int:
    """`DEEPSEEK_MAX_TOKENS` (docs/05 §5); un valor invalido no debe tumbar una evaluacion."""

    raw = os.environ.get("DEEPSEEK_MAX_TOKENS")
    if not raw:
        return DEFAULT_MAX_TOKENS
    try:
        return int(raw)
    except ValueError:
        logger.warning("DEEPSEEK_MAX_TOKENS=%r no es un entero; uso %s", raw, DEFAULT_MAX_TOKENS)
        return DEFAULT_MAX_TOKENS


def _timeout_configurado() -> int:
    """`DEEPSEEK_TIMEOUT_SECONDS` (docs/05 §5): la IA con razonamiento tarda mas que un chat."""

    raw = os.environ.get("DEEPSEEK_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "DEEPSEEK_TIMEOUT_SECONDS=%r no es un entero; uso %s", raw, DEFAULT_TIMEOUT_SECONDS
        )
        return DEFAULT_TIMEOUT_SECONDS


class DeepSeekClient:
    """Implementacion real: SDK `openai` apuntando a la API de DeepSeek (docs/05 §5)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        max_tokens: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sleep = sleep
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY no configurada")

        from openai import OpenAI  # import diferido: no requerido si no hay API key

        base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        self.timeout = timeout or _timeout_configurado()
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=self.timeout)
        self.model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens or _max_tokens_configurado()
        self.max_tokens_ceiling = max(MAX_TOKENS_CEILING, self.max_tokens)
        #: Se incluye en la clave de cache junto al modelo: cambiar de endpoint cambia el resultado.
        self.base_url = base_url

    def params(self) -> dict:
        """Parametros que, si cambian, invalidan una respuesta guardada (docs/05 §7)."""

        from app.ai.store import FORMATO

        return {
            "temperature": 0.0,
            "max_tokens": self.max_tokens,
            "razonamiento": True,
            "formato": FORMATO,
        }

    @property
    def params_hash(self) -> str:
        from app.ai.store import sha256_json  # evita cargar la BD para usar el cliente solo

        return sha256_json(self.params())

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        """JSON o `None`. El motivo del degradado queda en el log, con `finish_reason`.

        Un contenido vacio no siempre es "el modelo no dijo nada": con `finish_reason="length"` es
        el presupuesto de tokens agotado -- el razonamiento del modelo lo consumio antes de escribir
        el JSON. En ese caso el reintento sube `max_tokens` en vez de repetir la misma peticion.
        """

        inicio = time.monotonic()
        motivo = "sin_intentos"
        intentos = 0
        max_tokens = self.max_tokens
        timeout = self.timeout
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
                    max_tokens=max_tokens,
                    timeout=timeout,
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
                    "DeepSeek %s tokens: prompt=%s completion=%s total=%s max_tokens=%s"
                    " finish=%s razonamiento=%s",
                    self.model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                    max_tokens,
                    response.choices[0].finish_reason,
                    bool(getattr(response.choices[0].message, "reasoning_content", None)),
                )

            finish_reason = response.choices[0].finish_reason
            content = (response.choices[0].message.content or "").strip()
            if not content:
                motivo = f"respuesta_vacia:{finish_reason}"
                if finish_reason == "length":
                    if max_tokens >= self.max_tokens_ceiling:
                        break
                    max_tokens = min(max_tokens * 2, self.max_tokens_ceiling)
                    timeout = min(timeout * 2, MAX_TIMEOUT_SECONDS)
                    continue
                if finish_reason == "content_filter":
                    break  # la misma peticion volveria a filtrarse: no se insiste
                continue
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                motivo = f"json_invalido:{finish_reason}"
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


def build_default_client(
    *,
    session: Session | None = None,
    org_id: str | None = None,
    reextraer: bool = False,
) -> AIClient:
    """Fabrica usada por la API/workers/CLI.

    Con `session` + `org_id` (camino de produccion: api y workers) el resultado se cachea en la
    tabla `ai_results`, por organizacion. Sin ellos (CLI/local) se mantiene la cache en disco
    historica; `reextraer` ignora lo guardado y reescribe la respuesta nueva (docs/09 §105).
    """

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return NullAIClient()

    from app.ai.cache import CachingAIClient  # evita import circular a nivel de modulo

    real = DeepSeekClient(api_key=api_key)
    if session is None or not org_id:
        return CachingAIClient(real)

    from app.ai.store import AIResultStore, StoreAIClient

    store = AIResultStore.from_session(
        session,
        org_id,
        model=real.model,
        base_url=real.base_url,
        params_hash=real.params_hash,
        reextraer=reextraer,
    )
    return StoreAIClient(real, store)


def describe_client(client: AIClient) -> str:
    """Texto para logs: distingue "IA real" de "sin key, degradando en silencio" (docs/09 §18).

    Un worker que recibe `ai_requested=True` pero no ve la API key cae en `NullAIClient` y no
    hace ninguna llamada de red -- sin este log, eso es indistinguible de "todo funciono pero
    salio de cache"."""

    if isinstance(client, NullAIClient):
        return "no configurada (sin DEEPSEEK_API_KEY; degrada a S=B, sin llamadas ni costo)"
    return "activa (DeepSeek)"
