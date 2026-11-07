"""Motor y sesion de base de datos (docs/04 §2, §4, §11).

SQLite por defecto: nada que montar para ver el siguiente corte funcionar, igual que el resto
del CLI. `DATABASE_URL` (shell o backend/.env) apunta a Postgres cuando exista el stack de
Docker (docs/04 §11); el modelo de datos es el mismo en ambos casos.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Engine,
    MetaData,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
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
    aunque los tests pasaran, porque estos usan BD nuevas. No toca datos ni tipos. Una columna
    NOT NULL se omite: `reconcile_sqlite_schema` reconstruye esa tabla con su default. Devuelve
    las columnas agregadas, como `tabla.columna`."""

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
                    logger.info(
                        "%s.%s es NOT NULL: se reconstruira la tabla para agregarla.",
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


def _unique_column_sets(table: Table) -> set[frozenset[str]]:
    return {
        frozenset(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _sqlite_table_needs_rebuild(inspector: Any, table: Table) -> bool:
    """Una tabla necesita reconstruirse si el modelo pide algo que `ALTER TABLE ADD COLUMN` no
    puede arreglar: una columna NOT NULL nueva, un cambio de nullability o una unique distinta."""

    existentes = {columna["name"]: columna for columna in inspector.get_columns(table.name)}
    for columna in table.columns:
        actual = existentes.get(columna.name)
        if actual is None:
            if not columna.nullable:
                return True
            continue
        if bool(actual["nullable"]) != bool(columna.nullable):
            return True
    unicas = {
        frozenset(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table.name)
    }
    return unicas != _unique_column_sets(table)


def _column_default_for_backfill(columna: Any) -> Any:
    """Valor para las filas viejas de una columna NOT NULL nueva: el default del modelo si lo
    tiene, y si no uno neutro segun el tipo (el modelo actual solo usa defaults)."""

    if columna.default is not None:
        if columna.default.is_scalar:
            return columna.default.arg
        if columna.default.is_callable:
            try:
                return columna.default.arg()
            except TypeError:
                return columna.default.arg(None)
    if columna.server_default is not None:
        return getattr(columna.server_default.arg, "text", columna.server_default.arg)
    try:
        tipo = columna.type.python_type
    except NotImplementedError:
        return ""
    if tipo is bool:
        return False
    if tipo in (int, float):
        return 0
    if tipo is list:
        return []
    if tipo is dict:
        return {}
    return ""


def _rebuild_sqlite_table(engine: Engine, table: Table) -> None:
    """Recrea una tabla desde el modelo, copiando las columnas que existen y rellenando las
    NOT NULL nuevas con su default. SQLite no permite cambiar nullability ni constraints con
    `ALTER TABLE`; la reconstruccion es el mismo mecanismo que usa Alembic en batch mode."""

    existentes = {columna["name"] for columna in inspect(engine).get_columns(table.name)}
    temporal = f"_pf_new_{table.name}"
    destino: list[str] = []
    origen: list[str] = []
    parametros: dict[str, Any] = {}

    for columna in table.columns:
        if columna.name in existentes:
            destino.append(f'"{columna.name}"')
            origen.append(f'"{columna.name}"')
        elif not columna.nullable:
            clave = f"valor_{len(parametros)}"
            valor = _column_default_for_backfill(columna)
            if isinstance(columna.type, JSON):
                valor = json.dumps(valor)
            parametros[clave] = valor
            destino.append(f'"{columna.name}"')
            origen.append(f":{clave}")

    metadata_temporal = MetaData()
    # La tabla temporal conserva sus FK: hay que copiar tambien las tablas referenciadas para
    # que SQLAlchemy pueda resolverlas al generar el CREATE TABLE.
    for foreign_key in table.foreign_keys:
        referenciada = foreign_key.column.table
        if referenciada.name not in metadata_temporal.tables:
            referenciada.to_metadata(metadata_temporal)
    tabla_temporal = table.to_metadata(metadata_temporal, name=temporal)

    with engine.connect() as conexion:
        conexion = conexion.execution_options(isolation_level="AUTOCOMMIT")
        conexion.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            conexion.exec_driver_sql(f'DROP TABLE IF EXISTS "{temporal}"')
            tabla_temporal.create(conexion)
            conexion.execute(
                text(
                    f'INSERT INTO "{temporal}" ({", ".join(destino)})'
                    f' SELECT {", ".join(origen)} FROM "{table.name}"'
                ),
                parametros,
            )
            conexion.exec_driver_sql(f'DROP TABLE "{table.name}"')
            conexion.exec_driver_sql(f'ALTER TABLE "{temporal}" RENAME TO "{table.name}"')
        finally:
            conexion.exec_driver_sql("PRAGMA foreign_keys=ON")


def reconcile_sqlite_schema(engine: Engine) -> list[str]:
    """Lleva las tablas SQLite existentes al esquema del modelo.

    `create_all` y `ALTER TABLE ADD COLUMN` no arreglan una columna NOT NULL nueva ni una unique
    vieja (incidentes por org antes de separar por scope). Las tablas con esas diferencias se
    reconstruyen copiando sus datos. Devuelve los nombres de las tablas reconstruidas."""

    inspector = inspect(engine)
    a_reconstruir = [
        tabla
        for tabla in Base.metadata.sorted_tables
        if inspector.has_table(tabla.name) and _sqlite_table_needs_rebuild(inspector, tabla)
    ]
    for tabla in a_reconstruir:
        _rebuild_sqlite_table(engine, tabla)
        logger.info("BD de dev actualizada: tabla %s reconstruida desde el modelo.", tabla.name)
    return [tabla.name for tabla in a_reconstruir]


def ensure_schema(engine: Engine) -> None:
    """Crea y pone al dia el esquema desde los modelos **solo en SQLite** (dev/CLI/tests).

    En Postgres el esquema lo administra Alembic (`alembic upgrade head`, docs/04 §11 regla C2).
    Correr `create_all` ahi crea una tabla que Alembic todavia no registro en `alembic_version`,
    y la proxima migracion falla con `DuplicateTable` -- incidente real al agregar `users`
    (docs/09 §22). Con esto, Postgres y Alembic son la unica fuente de verdad del esquema.

    En SQLite la BD de dev puede venir de `create_all` y no tener `alembic_version`, asi que
    `alembic upgrade head` no la puede tomar como base. En su lugar: crea las tablas faltantes,
    agrega las columnas nullable con `ALTER TABLE` (barato) y reconstruye solo las tablas que
    necesitan un cambio que SQLite no soporta in-place (NOT NULL, nullability, unique). Asi una
    BD vieja llega al esquema actual sin perder datos (docs/09 §48)."""

    if engine.dialect.name == "sqlite":
        create_all(engine)
        add_missing_columns(engine)
        reconcile_sqlite_schema(engine)
