"""Heartbeat de workers (`app/core/queue.py`): es lo que le permite al reaper distinguir un job
esperando en la cola de uno que nadie va a procesar (docs/04 §5). Sin Redis real: el `FakeRedis`
de conftest.py guarda las claves y el `ex` se ignora, asi que "worker muerto" se simula dejando de
refrescar la clave."""

from __future__ import annotations

import time

from app.core.queue import (
    QUEUE_CORE,
    WorkerHeartbeat,
    heartbeat_key,
    job_heartbeat_key,
    job_worker_alive,
    worker_alive,
)
from tests.conftest import FakeRedis


def test_worker_alive_distinguishes_absent_unknown_and_live():
    assert worker_alive(None, QUEUE_CORE) is None
    assert job_worker_alive(None, "job-1") is None

    redis = FakeRedis()
    assert worker_alive(redis, QUEUE_CORE) is False
    assert job_worker_alive(redis, "job-1") is False

    redis.set(heartbeat_key(QUEUE_CORE, "worker-1"), "ahora")
    redis.set(job_heartbeat_key("job-1"), "ahora")
    assert worker_alive(redis, QUEUE_CORE) is True
    assert job_worker_alive(redis, "job-1") is True
    assert worker_alive(redis, "pf:jobs:otra") is False


def test_heartbeat_publishes_and_releases_the_job_key():
    redis = FakeRedis()
    heartbeat = WorkerHeartbeat(redis, QUEUE_CORE, worker_id="w1")

    heartbeat.beat()
    assert worker_alive(redis, QUEUE_CORE) is True
    assert job_worker_alive(redis, "job-1") is False

    heartbeat.track("job-1")
    assert job_worker_alive(redis, "job-1") is True

    heartbeat.track(None)
    assert job_worker_alive(redis, "job-1") is False
    assert worker_alive(redis, QUEUE_CORE) is True


def test_heartbeat_thread_keeps_refreshing_while_the_worker_is_busy():
    """El loop del worker se bloquea en un pipeline largo; el hilo es lo que mantiene vivo el
    latido (y con el, el job en curso) sin depender del loop."""

    redis = FakeRedis()
    heartbeat = WorkerHeartbeat(
        redis, QUEUE_CORE, worker_id="w1", ttl_seconds=5, interval_seconds=0.05
    )
    heartbeat.track("job-1")
    heartbeat.start()
    try:
        redis.delete(heartbeat.key, job_heartbeat_key("job-1"))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not job_worker_alive(redis, "job-1"):
            time.sleep(0.02)
        assert worker_alive(redis, QUEUE_CORE) is True
        assert job_worker_alive(redis, "job-1") is True
    finally:
        heartbeat.stop()
