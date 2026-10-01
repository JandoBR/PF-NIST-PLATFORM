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
    """Crea el esquema directamente desde los modelos (SQLite de dev, CLI, tests)."""

    Base.metadata.create_all(engine)


def ensure_schema(engine: Engine) -> None:
    """Crea el esquema desde los modelos **solo en SQLite** (dev/CLI/tests).

    En Postgres el esquema lo administra Alembic (`alembic upgrade head`, docs/04 §11 regla C2).
    Correr `create_all` ahi crea una tabla que Alembic todavia no registro en `alembic_version`,
    y la proxima migracion falla con `DuplicateTable` -- incidente real al agregar `users`
    (docs/09 §22). Con esto, Postgres y Alembic son la unica fuente de verdad del esquema."""

    if engine.dialect.name == "sqlite":
        create_all(engine)
