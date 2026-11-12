"""Store persistente de resultados de IA (docs/05 §7, docs/04 §4).

La cache anterior era un directorio por contenedor (`app/ai/cache.py`): api, worker-core y
worker-logs tenian cada uno su copia, no estaba montada y se perdia en cada `docker compose up`.
Aqui el resultado vive en `ai_results`, con la organizacion en la clave: dos contenedores con la
misma BD comparten el resultado, y una organizacion nunca reutiliza el de otra.

La clave es un insumo **canonico**, no el prompt tal cual:

- U1: JSON {texto del chunk, id del documento, tipos ordenados}.
- U2: JSON {criterio+version, base, estado, valores de evidencia sin ids, ordenados, contexto,
  alpha, D}; el prompt usa ids sinteticos (`e1`, `e2`, ...) y `adjust` los remapea a los ids
  reales de la evaluacion actual.
- U3: JSON {criterio+version, plantilla, severidad, score, cantidad de evidencia}.

Asi la misma evidencia con UUIDs distintos (otra evaluacion, otro contenedor) es el mismo insumo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.ai import voting
from app.ai.calllog import current_context, log_call
from app.core.db import build_session_factory
from app.models.tables import AIResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from app.ai.client import AIClient

logger = logging.getLogger("app.ai.store")

#: Se serializan las escrituras: SQLite no admite dos escritores a la vez y el segundo worker solo
#: necesita confirmar que la fila ya existe (se conserva la primera respuesta).
_write_lock = threading.Lock()

#: Durante una votacion de U1 cada corrida debe llegar al modelo: sin esto la segunda y tercera
#: encontrarian el resultado de la primera (en el store o en la cache de disco) y no votarian nada.
_bypass: ContextVar[bool] = ContextVar("ai_store_bypass", default=False)


@contextmanager
def store_bypass() -> Iterator[None]:
    """Desactiva lecturas y escrituras del store/cache durante el bloque."""

    token = _bypass.set(True)
    try:
        yield
    finally:
        _bypass.reset(token)


def bypass_active() -> bool:
    return _bypass.get()


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


class AIResultStore:
    """Reads/writes de `ai_results` para una organizacion, modelo y parametros concretos."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        org_id: str,
        *,
        model: str,
        base_url: str,
        params_hash: str,
        votes: int | None = None,
        reextraer: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self.org_id = org_id
        self.model = model
        self.base_url = base_url
        self.params_hash = params_hash
        self.votes = voting.votes() if votes is None else votes
        #: `reextraer` ignora lo guardado y reescribe la fila con la respuesta nueva (docs/09 §105).
        self.reextraer = reextraer
        self._stats: dict[str, dict[str, int]] = {
            kind: {"hits": 0, "misses": 0} for kind in ("U1", "U2", "U3")
        }
        self._stats_lock = threading.Lock()

    @classmethod
    def from_session(
        cls,
        session: Session,
        org_id: str,
        *,
        model: str,
        base_url: str,
        params_hash: str,
        votes: int | None = None,
        reextraer: bool = False,
    ) -> AIResultStore:
        return cls(
            build_session_factory(session.get_bind()),
            org_id,
            model=model,
            base_url=base_url,
            params_hash=params_hash,
            votes=votes,
            reextraer=reextraer,
        )

    def _key(self, kind: str, prompt_version: str, input_sha256: str) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "kind": kind,
            "model": self.model,
            "base_url": self.base_url,
            "params_hash": self.params_hash,
            "prompt_version": prompt_version,
            "input_sha256": input_sha256,
        }

    def _record(self, kind: str, result: str) -> None:
        with self._stats_lock:
            self._stats.setdefault(kind, {"hits": 0, "misses": 0})[result] += 1

    def stats(self) -> dict[str, dict[str, int]]:
        with self._stats_lock:
            return {kind: dict(values) for kind, values in self._stats.items()}

    def get(self, kind: str, prompt_version: str, input_sha256: str) -> dict | None:
        """Resultado guardado o `None`. Un fallo de BD degrada a miss, nunca tumba la evaluacion."""

        if self.reextraer:
            self._record(kind, "misses")
            return None
        session = self._session_factory()
        try:
            row = (
                session.query(AIResult)
                .filter_by(**self._key(kind, prompt_version, input_sha256))
                .one_or_none()
            )
        except SQLAlchemyError:
            logger.warning(
                "BD no disponible para leer ai_results; se trata como miss", exc_info=True
            )
            self._record(kind, "misses")
            return None
        finally:
            session.close()
        self._record(kind, "hits" if row is not None else "misses")
        if row is None:
            return None
        return row.output if isinstance(row.output, dict) else None

    def put(
        self,
        kind: str,
        prompt_version: str,
        input_sha256: str,
        output: dict,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Guarda el primero que llega; con `reextraer`, reemplaza la respuesta existente.

        Dos workers pueden calcular el mismo insumo a la vez: el segundo choca con la unique y
        conserva la respuesta del primero. Perder ese resultado es correcto: es el mismo insumo.
        """

        session = self._session_factory()
        try:
            with _write_lock:
                existente = (
                    session.query(AIResult)
                    .filter_by(**self._key(kind, prompt_version, input_sha256))
                    .one_or_none()
                )
                if existente is not None:
                    if self.reextraer:
                        existente.output = output
                        existente.meta = meta or {}
                        session.commit()
                    return
                session.add(
                    AIResult(
                        **self._key(kind, prompt_version, input_sha256),
                        output=output,
                        meta=meta or {},
                    )
                )
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
        except SQLAlchemyError:
            session.rollback()
            logger.warning("No se pudo guardar ai_results; la evaluacion continua", exc_info=True)
        finally:
            session.close()


def store_for(client: AIClient | None) -> AIResultStore | None:
    """Store del cliente, atravesando envoltorios (`_CountingClient`, caches, etc.)."""

    while client is not None:
        store = getattr(client, "result_store", None)
        if isinstance(store, AIResultStore):
            return store
        client = getattr(client, "_inner", None)
    return None


class StoreAIClient:
    """Envuelve un `AIClient` real y cachea U2/U3 (y U1 con una sola corrida) en `ai_results`.

    Con `U1_VOTES > 1`, U1 lo maneja `extraction.extract_claims`, que ejecuta N corridas antes de
    votar y guarda una sola respuesta votada: ahi el wrapper se salta con `store_bypass`. En el
    resto de los casos cachea cuando el caller fijo `kind`/`prompt_version`/`input_sha256` en el
    contexto de la llamada (`call_context`).
    """

    def __init__(self, inner: AIClient, store: AIResultStore) -> None:
        self._inner = inner
        self.result_store = store

    @property
    def model(self) -> str:
        return self.result_store.model

    @property
    def base_url(self) -> str:
        return self.result_store.base_url

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        if bypass_active():
            return self._inner.complete_json(system_prompt, user_prompt)

        context = current_context()
        kind = context.get("paso")
        prompt_version = context.get("prompt_version")
        input_sha256 = context.get("input_sha256")
        if not (kind and prompt_version and input_sha256):
            return self._inner.complete_json(system_prompt, user_prompt)

        guardado = self.result_store.get(kind, prompt_version, input_sha256)
        if guardado is not None:
            log_call(resultado="cache")
            return guardado

        result = self._inner.complete_json(system_prompt, user_prompt)
        if result is not None:
            self.result_store.put(
                kind, prompt_version, input_sha256, result, {"votos": 1, "origen": "store"}
            )
        return result
