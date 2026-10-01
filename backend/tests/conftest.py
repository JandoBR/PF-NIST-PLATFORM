import pytest

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
