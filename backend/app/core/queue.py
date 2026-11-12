"""Colas de trabajos sobre Redis (docs/04 §4-§5, §11): el `api` encola, los workers consumen.

Simplificado a proposito frente a docs/04 (que habla de Redis Streams con consumer groups,
P2/P7): una lista de Redis con `RPUSH`/`BLPOP` alcanza para un solo worker por tipo de trabajo
sin autoscaling, que es el alcance real de este prototipo. Streams + consumer groups quedan como
evolucion (docs/09), no como deuda -- nada en el contrato de `Job` (la fuente de verdad real,
en la base de datos) depende de como viaja el mensaje.

Ademas del transporte, aqui vive el heartbeat de los workers (`WorkerHeartbeat`): `app/core/jobs.py`
lo consulta para no declarar perdido un job que solo esta esperando en la cola (docs/04 §5).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from datetime import UTC, datetime
from typing import Any

import redis

#: Cola para `tipo="assessment_run"` (pipeline completo de evaluacion), consumida por
#: `app/workers/core.py`.
QUEUE_CORE = "pf:jobs:core"

#: Cola para `tipo="event_ingest"` (pipeline de eventos: patrones, disparadores, incidentes),
#: consumida por `app/workers/logs.py`.
QUEUE_LOGS = "pf:jobs:logs"

#: Cola que atiende cada `tipo` de job (la usan `dispatch.py` al encolar y el reaper para saber si
#: hay un worker vivo de esa cola, docs/04 §5).
QUEUE_BY_TIPO = {"assessment_run": QUEUE_CORE, "event_ingest": QUEUE_LOGS}

#: Segundos de vida del heartbeat de un worker en Redis. Un worker vivo lo refresca cada
#: `WORKER_HEARTBEAT_INTERVAL_SECONDS`; si el proceso muere, la clave expira y el reaper puede
#: declarar perdido el job que tenia en curso. Default 60 s: bastante menos que
#: `JOB_STALE_TIMEOUT_SECONDS` (600 s) y comodo frente al intervalo.
WORKER_HEARTBEAT_TTL_SECONDS = int(os.environ.get("JOB_HEARTBEAT_TTL_SECONDS", "60"))

#: Cada cuanto el hilo del heartbeat lo refresca (tambien mientras el worker procesa un job largo
#: de IA). Se repite como default de `WorkerHeartbeat`, no es otra fuente de verdad.
WORKER_HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("JOB_HEARTBEAT_INTERVAL_SECONDS", "20"))

logger = logging.getLogger("queue")


#: Version del contrato del mensaje (docs/04 §3.1, docs/11 OP-13). Se sube cuando un campo cambia de
#: significado o se vuelve obligatorio; agregar un campo opcional no la sube. Protege el caso en que
#: `api` y los workers se despliegan por separado: un worker viejo que recibe un mensaje de una
#: version que no entiende debe fallar el job con un motivo claro, no interpretarlo a medias.
MESSAGE_SCHEMA_VERSION = 1


def message_version_error(message: dict[str, Any]) -> str | None:
    """Motivo por el que este worker no debe procesar el mensaje, o `None` si puede.

    Un mensaje sin `schema_version` es de antes de OP-13 (version 1): se acepta."""

    version = message.get("schema_version", 1)
    es_entero = isinstance(version, int) and not isinstance(version, bool)
    if es_entero and 1 <= version <= MESSAGE_SCHEMA_VERSION:
        return None
    return (
        f"El mensaje del job usa schema_version={version!r} y este worker solo entiende hasta"
        f" {MESSAGE_SCHEMA_VERSION}. Actualiza el worker y reintenta el job."
    )


def get_redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def build_redis_client(redis_url: str | None = None) -> redis.Redis:
    return redis.from_url(redis_url or get_redis_url(), decode_responses=True)


def enqueue(client: redis.Redis, queue: str, message: dict[str, Any]) -> None:
    client.rpush(queue, json.dumps(message))


def dequeue_blocking(client: redis.Redis, queue: str, timeout: int = 5) -> dict[str, Any] | None:
    """Bloquea hasta `timeout` segundos esperando un mensaje. `None` si no llego ninguno.

    `BLPOP` sin mensajes deberia devolver `None` al agotar `timeout`, pero contra un Redis real
    (no el `FakeRedis` de los tests) el socket del cliente a veces agota su propio timeout una
    fraccion de segundo antes de que llegue la respuesta nil del servidor, y redis-py lo
    reporta como `TimeoutError` en vez de como un `None` normal (visto en real en
    `worker-core`/`worker-logs` contra el Redis de docker-compose). Para el worker, ambas cosas
    significan exactamente lo mismo: "no llego nada en este ciclo, seguir esperando" -- por eso
    se tratan igual aqui en vez de dejar que tumbe el loop.

    Un mensaje que no es JSON se descarta con un aviso en el log: un elemento corrupto en la cola
    no puede tumbar al worker (docs/09 §114)."""

    try:
        item = client.blpop([queue], timeout=timeout)
    except redis.exceptions.TimeoutError:
        return None
    if item is None:
        return None
    _, raw = item
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Mensaje corrupto en %s (no es JSON); se descarta.", queue)
        return None


def heartbeat_key(queue: str, worker_id: str) -> str:
    return f"pf:jobs:hb:{queue}:{worker_id}"


def heartbeat_pattern(queue: str) -> str:
    return f"pf:jobs:hb:{queue}:*"


def job_heartbeat_key(job_id: str) -> str:
    return f"pf:jobs:hb:job:{job_id}"


def worker_alive(client: redis.Redis | None, queue: str) -> bool | None:
    """`True` si hay al menos un worker con heartbeat vivo para esa cola; `False` si el chequeo
    funciono y no hay ninguno; `None` si no se pudo saber (sin cliente o Redis inalcanzable).

    `None` no significa "no hay worker": es evidencia ausente, y el reaper lo trata distinto segun
    el estado del job (docs/04 §5)."""

    if client is None:
        return None
    try:
        return bool(client.keys(heartbeat_pattern(queue)))
    except redis.exceptions.RedisError:
        logger.warning("No se pudo leer el heartbeat de %s; se asume desconocido.", queue)
        return None


def job_worker_alive(client: redis.Redis | None, job_id: str) -> bool | None:
    """Igual que `worker_alive` pero para el latido del job concreto que un worker esta
    procesando: `True` mientras lo refresca, `False` cuando el worker que lo tomo desaparecio."""

    if client is None:
        return None
    try:
        return bool(client.exists(job_heartbeat_key(job_id)))
    except redis.exceptions.RedisError:
        logger.warning("No se pudo leer el heartbeat del job %s; se asume desconocido.", job_id)
        return None


class WorkerHeartbeat:
    """Publica en Redis el latido de un worker y el del job que tiene en curso (docs/04 §5).

    Un hilo daemon lo refresca cada `interval_seconds` -- tambien mientras el worker esta metido en
    un pipeline largo de IA, que es lo que bloquea el loop principal. `track()` marca el job en
    curso; sin latido por job, el reaper no distingue un job sano de uno huerfano del mismo worker.
    """

    def __init__(
        self,
        client: redis.Redis,
        queue: str,
        *,
        worker_id: str | None = None,
        ttl_seconds: int | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self._client = client
        self.queue = queue
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.ttl_seconds = ttl_seconds or WORKER_HEARTBEAT_TTL_SECONDS
        self.interval_seconds = interval_seconds or WORKER_HEARTBEAT_INTERVAL_SECONDS
        self._job_id: str | None = None
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def key(self) -> str:
        return heartbeat_key(self.queue, self.worker_id)

    def beat(self) -> None:
        """Refresca las claves del worker y (si hay) del job en curso. Un Redis caido no tumba al
        worker: sin heartbeat el reaper reapea por timeout, que es el comportamiento viejo."""

        now = datetime.now(UTC).isoformat()
        try:
            self._client.set(self.key, now, ex=self.ttl_seconds)
            job_id = self._job_id
            if job_id is not None:
                self._client.set(job_heartbeat_key(job_id), now, ex=self.ttl_seconds)
        except redis.exceptions.RedisError:
            logger.warning("No se pudo publicar el heartbeat de %s", self.key)

    def track(self, job_id: str | None) -> None:
        """Marca el job que este worker esta procesando (`None` al terminar). Lo publica de
        inmediato y borra la clave del anterior para no dejar vivo un job ya cerrado."""

        previous, self._job_id = self._job_id, job_id
        self.beat()
        if previous is not None and previous != job_id:
            try:
                self._client.delete(job_heartbeat_key(previous))
            except redis.exceptions.RedisError:
                logger.warning("No se pudo borrar el heartbeat del job %s", previous)

    def start(self) -> None:
        """Publica un latido ya y arranca el hilo que lo repite hasta `stop()`."""

        self.beat()
        self._thread = threading.Thread(
            target=self._run, name=f"heartbeat-{self.queue}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds + 1)
            self._thread = None

    def _run(self) -> None:
        while not self._stopped.wait(self.interval_seconds):
            self.beat()
