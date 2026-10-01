import pytest
from fastapi.testclient import TestClient

from app.core.db import build_engine, build_session_factory, create_all


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


@pytest.fixture
def api_client(db_session):
    """TestClient con `get_session` sobreescrito para usar la misma BD efimera de `db_session`."""

    from app.api.app import app
    from app.api.deps import get_session

    def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
