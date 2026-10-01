"""Motor y sesion de base de datos (docs/04 §2, §4, §11).

SQLite por defecto: nada que montar para ver el siguiente corte funcionar, igual que el resto
del CLI. `DATABASE_URL` (shell o backend/.env) apunta a Postgres cuando exista el stack de
Docker (docs/04 §11); el modelo de datos es el mismo en ambos casos.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.tables import Base

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = REPO_ROOT / ".data" / "pf.db"


def get_database_url() -> str:
    configured = os.environ.get("DATABASE_URL")
    if configured:
        return configured
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def build_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or get_database_url())


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    """Crea el esquema directamente desde los modelos.

    Para Postgres en el stack real, `alembic upgrade head` es la via oficial (docs/04 §11,
    regla C2); esto es el atajo que usan la CLI local y los tests contra SQLite.
    """

    Base.metadata.create_all(engine)
