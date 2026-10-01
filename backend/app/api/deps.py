"""Dependencias de FastAPI: sesion de BD por request, metodologia cargada una vez."""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

import redis
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core import auth
from app.core.db import build_engine, build_session_factory, ensure_schema
from app.core.queue import build_redis_client
from app.methodology.loader import Methodology, load_methodology
from app.models.tables import User

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def _session_factory():
    engine = build_engine()
    ensure_schema(engine)
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


def get_current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    """Usuario de la sesion a partir de `Authorization: Bearer <token>` (doc 10 §3)."""

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Falta el token de autenticación (Authorization: Bearer ...).",
        )
    payload = auth.decode_token(authorization.split(" ", 1)[1].strip())
    if payload is None:
        raise HTTPException(status_code=401, detail="Token inválido o expirado.")
    user = session.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario inexistente.")
    return user


def require_same_org(user: User, org_id: str) -> None:
    """404 (no 403) si el recurso es de otra organizacion: no revelar que existe (doc 10 §4)."""

    if org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Recurso no encontrado.")
