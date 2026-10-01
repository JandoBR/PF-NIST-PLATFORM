import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.db import build_engine, build_session_factory, create_all
from app.methodology.loader import load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture
def db_session(tmp_path):
    """Sesion contra un SQLite temporal y aislado por test (ver app/core/db.py)."""

    engine = build_engine(f"sqlite:///{tmp_path}/test.db")
    create_all(engine)
    session_factory = build_session_factory(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


class FakeRedis:
    """Doble minimo de `redis.Redis` para tests de la API: listas en memoria, solo `rpush` y
    `blpop` (lo unico que usa `app/core/queue.py`). Los workers tienen sus propios tests que
    llaman `process_message` directamente (ver test_workers_core.py/test_workers_logs.py), asi
    que esto nunca necesita bloquear de verdad ni la suite por defecto necesita un Redis real
    corriendo -- ver tests/test_queue.py para la contraparte que si usa uno, saltandose si no
    hay ninguno alcanzable."""

    def __init__(self) -> None:
        self._lists: dict[str, list[str]] = {}

    def rpush(self, key: str, value: str) -> None:
        self._lists.setdefault(key, []).append(value)

    def blpop(self, keys: list[str], timeout: int = 0):
        for key in keys:
            lst = self._lists.get(key)
            if lst:
                return key, lst.pop(0)
        return None

    def drain(self, key: str) -> list[dict]:
        """Solo para tests: devuelve y vacia los mensajes pendientes de una cola, decodificados.
        No es parte de la interfaz real de `redis.Redis`."""

        raw = self._lists.pop(key, [])
        return [json.loads(item) for item in raw]


@pytest.fixture
def fake_redis():
    return FakeRedis()


def run_pending_jobs(db_session, methodology, fake_redis: FakeRedis) -> None:
    """Helper de test (no una fixture): drena ambas colas del `FakeRedis` de un `api_client` y
    procesa cada mensaje con el worker real correspondiente -- simula "el worker ya corrio" sin
    levantar un proceso en segundo plano, para que un test de la API pueda crear algo via
    `POST /assessments` o `POST /orgs/{id}/events` y luego pedir el resultado sin tener que
    sondear `GET /jobs/{id}` de verdad."""

    from app.core.queue import QUEUE_CORE, QUEUE_LOGS
    from app.workers import core as worker_core
    from app.workers import logs as worker_logs

    for message in fake_redis.drain(QUEUE_CORE):
        worker_core.process_message(db_session, methodology, message)
    for message in fake_redis.drain(QUEUE_LOGS):
        worker_logs.process_message(db_session, methodology, message)


@pytest.fixture
def api_client(db_session, fake_redis):
    """TestClient con `get_session`/`get_redis` sobreescritos: la misma BD efimera de
    `db_session` y un Redis falso en memoria, para que la suite no dependa de servicios
    externos. Un test que necesite simular que el worker ya proceso un job debe drenar
    `fake_redis` (via `fake_redis.drain(QUEUE_CORE)`/`QUEUE_LOGS`) y llamar
    `app.workers.core.process_message`/`app.workers.logs.process_message` el mismo."""

    from app.api.app import app
    from app.api.deps import get_redis, get_session

    def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
