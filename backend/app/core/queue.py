"""Colas de trabajos sobre Redis (docs/04 §4-§5, §11): el `api` encola, los workers consumen.

Simplificado a proposito frente a docs/04 (que habla de Redis Streams con consumer groups,
P2/P7): una lista de Redis con `RPUSH`/`BLPOP` alcanza para un solo worker por tipo de trabajo
sin autoscaling, que es el alcance real de este prototipo. Streams + consumer groups quedan como
evolucion (docs/09), no como deuda -- nada en el contrato de `Job` (la fuente de verdad real,
en la base de datos) depende de como viaja el mensaje.
"""

from __future__ import annotations

import json
import os
from typing import Any

import redis

#: Cola para `tipo="assessment_run"` (pipeline completo de evaluacion), consumida por
#: `app/workers/core.py`.
QUEUE_CORE = "pf:jobs:core"

#: Cola para `tipo="event_ingest"` (pipeline de eventos: patrones, disparadores, incidentes),
#: consumida por `app/workers/logs.py`.
QUEUE_LOGS = "pf:jobs:logs"


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
    se tratan igual aqui en vez de dejar que tumbe el loop."""

    try:
        item = client.blpop([queue], timeout=timeout)
    except redis.exceptions.TimeoutError:
        return None
    if item is None:
        return None
    _, raw = item
    return json.loads(raw)
