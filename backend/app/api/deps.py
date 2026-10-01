"""Dependencias de FastAPI: sesion de BD por request, metodologia cargada una vez."""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

import redis
from sqlalchemy.orm import Session

from app.core.db import build_engine, build_session_factory, create_all
from app.core.queue import build_redis_client
from app.methodology.loader import Methodology, load_methodology

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def _session_factory():
    engine = build_engine()
    create_all(engine)
    return build_session_factory(engine)


def get_session() -> Generator[Session]:
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


@lru_cache(maxsize=1)
def get_methodology() -> Methodology:
    return load_methodology(REPO_ROOT / "methodology")


@lru_cache(maxsize=1)
def _redis_singleton() -> redis.Redis:
    return build_redis_client()


def get_redis() -> redis.Redis:
    """Dependencia de FastAPI, no un singleton directo: los tests la sobreescriben con un
    cliente falso (`tests/conftest.py`) para no requerir un Redis real en la suite por defecto."""

    return _redis_singleton()
