"""Motor y sesion de base de datos (docs/04 §2, §4, §11).

SQLite por defecto: nada que montar para ver el siguiente corte funcionar, igual que el resto
del CLI. `DATABASE_URL` (shell o backend/.env) apunta a Postgres cuando exista el stack de
Docker (docs/04 §11); el modelo de datos es el mismo en ambos casos.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.tables import Base

logger = logging.getLogger("app.core.db")

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


def add_missing_columns(engine: Engine) -> list[str]:
    """Agrega a una BD SQLite existente las columnas **nullable** que el modelo tiene y la tabla no.

    `create_all` solo crea tablas que faltan, nunca columnas: una BD de dev creada antes de un
    cambio de modelo (`assessments.reproducibility`, `jobs.payload`) fallaba con "no such column"
    aunque los tests pasaran, porque estos usan BD nuevas. No toca datos ni tipos, y una columna
    NOT NULL sin default no se puede agregar a una tabla con filas: esas solo se avisan (hace falta
    recrear la BD). Devuelve las columnas agregadas, como `tabla.columna`."""

    inspector = inspect(engine)
    agregadas: list[str] = []
    with engine.begin() as conn:
        for tabla in Base.metadata.sorted_tables:
            if not inspector.has_table(tabla.name):
                continue
            existentes = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name in existentes:
                    continue
                if not columna.nullable:
                    logger.warning(
                        "%s.%s es NOT NULL y falta en la BD: recrea la BD de dev.",
                        tabla.name,
                        columna.name,
                    )
                    continue
                tipo = columna.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{tabla.name}" ADD COLUMN "{columna.name}" {tipo}'))
                agregadas.append(f"{tabla.name}.{columna.name}")
    for nombre in agregadas:
        logger.info("BD de dev actualizada: columna %s agregada.", nombre)
    return agregadas


def ensure_schema(engine: Engine) -> None:
    """Crea el esquema desde los modelos **solo en SQLite** (dev/CLI/tests).

    En Postgres el esquema lo administra Alembic (`alembic upgrade head`, docs/04 §11 regla C2).
    Correr `create_all` ahi crea una tabla que Alembic todavia no registro en `alembic_version`,
    y la proxima migracion falla con `DuplicateTable` -- incidente real al agregar `users`
    (docs/09 §22). Con esto, Postgres y Alembic son la unica fuente de verdad del esquema.

    En SQLite tambien se agregan las columnas nuevas a las tablas existentes (docs/09 §48)."""

    if engine.dialect.name == "sqlite":
        create_all(engine)
        add_missing_columns(engine)
