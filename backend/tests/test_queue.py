"""Round-trip real contra Redis (no el `FakeRedis` de conftest.py): confirma que
`app/core/queue.py` de verdad sabe hablar con un Redis de verdad. Se salta si no hay ninguno
alcanzable (`REDIS_URL` o `redis://localhost:6379/0`) -- la suite por defecto no depende de
servicios externos (ver conftest.py), pero este archivo si los aprovecha cuando existen (dev
local con `redis-server`, o CI con un contenedor de Redis)."""

from __future__ import annotations

import uuid

import pytest
import redis as redis_lib

from app.core.queue import build_redis_client, dequeue_blocking, enqueue


@pytest.fixture
def redis_client():
    client = build_redis_client()
    try:
        client.ping()
    except redis_lib.exceptions.ConnectionError:
        pytest.skip(
            "Sin Redis alcanzable (REDIS_URL o localhost:6379); se salta el round-trip real."
        )
    yield client


def test_enqueue_dequeue_round_trip(redis_client):
    queue = f"pf:test:{uuid.uuid4()}"
    enqueue(redis_client, queue, {"hola": "mundo"})

    message = dequeue_blocking(redis_client, queue, timeout=1)

    assert message == {"hola": "mundo"}


def test_dequeue_times_out_on_empty_queue(redis_client):
    queue = f"pf:test:{uuid.uuid4()}"

    assert dequeue_blocking(redis_client, queue, timeout=1) is None
