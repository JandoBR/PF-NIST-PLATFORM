import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.core.db import build_engine, build_session_factory, create_all
from app.methodology.loader import load_methodology
from app.models.tables import Organization, User

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"

#: Los tests no deben sembrar cuentas en la base real (el lifespan de la app correria el seed).
os.environ["SEED_DEMO_USERS"] = "0"

#: Organizacion del usuario de prueba: la usan los tests de API que asumen una organizacion fija
#: (a proposito coincide con el nombre que mandaban antes de la autenticacion, doc 10).
TEST_ORG_NAME = "Empresa API Assessments"
TEST_USERNAME = "tester"
TEST_PASSWORD = "test123"


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


@pytest.fixture
def auth_user(db_session) -> User:
    """Usuario de la organizacion `TEST_ORG_NAME`, sobre la sesion de prueba."""

    org = db_session.query(Organization).filter_by(nombre=TEST_ORG_NAME).one_or_none()
    if org is None:
        org = Organization(nombre=TEST_ORG_NAME)
        db_session.add(org)
        db_session.flush()
    salt, digest = hash_password(TEST_PASSWORD)
    user = User(
        org_id=org.id,
        username=TEST_USERNAME,
        password_salt=salt,
        password_hash=digest,
        role="client",
    )
    db_session.add(user)
    db_session.commit()
    return user


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

    # Loop: procesar logs puede encolar un `assessment_run` en core (refresco automatico de
    # madurez, docs/08 §8), y ese a su vez no encola mas; se drena hasta que ambas colas quedan
    # vacias para no dejar trabajo a medias en un test.
    while True:
        processed = False
        for message in fake_redis.drain(QUEUE_LOGS):
            worker_logs.process_message(db_session, methodology, message, fake_redis)
            processed = True
        for message in fake_redis.drain(QUEUE_CORE):
            worker_core.process_message(db_session, methodology, message)
            processed = True
        if not processed:
            break


def _client(db_session, fake_redis, *, authenticated: bool, auth_user: User | None = None):
    """Factory del `TestClient`: sobreescribe sesion/Redis, y opcionalmente `get_current_user`
    (los tests de auth dejan la dependencia real para ejercitar el token de verdad)."""

    from app.api.app import app
    from app.api.deps import get_current_user, get_redis, get_session

    def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    if authenticated:
        assert auth_user is not None
        app.dependency_overrides[get_current_user] = lambda: auth_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def api_client(db_session, fake_redis, auth_user):
    """Cliente autenticado como `auth_user` (la mayoria de los tests de API)."""

    yield from _client(db_session, fake_redis, authenticated=True, auth_user=auth_user)


@pytest.fixture
def anon_client(db_session, fake_redis):
    """Cliente **sin** autenticacion sobreescrita: ejercita el flujo real de token/401."""

    yield from _client(db_session, fake_redis, authenticated=False)
