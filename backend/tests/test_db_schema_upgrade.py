"""`ensure_schema` pone al dia una BD SQLite de dev creada antes de un cambio de modelo (§48).

`create_all` no agrega columnas, y una BD vieja fallaba con "no such column" aunque los tests (que
usan BD nuevas) pasaran."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.core import jobs as job_service
from app.core.db import add_missing_columns, ensure_schema
from app.models.tables import Assessment, Job, Organization


def _old_database(tmp_path):
    """Una BD con el esquema de antes de `jobs.payload` y `assessments.reproducibility`."""

    engine = create_engine(f"sqlite:///{tmp_path / 'viejo.db'}")
    ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs DROP COLUMN payload"))
        conn.execute(text("ALTER TABLE assessments DROP COLUMN reproducibility"))
        conn.execute(text("INSERT INTO organizations (id, nombre) VALUES ('o1', 'Vieja Org')"))
        conn.execute(
            text(
                "INSERT INTO jobs (id, tipo, estado, progreso, org_id, creado_en, actualizado_en)"
                " VALUES ('j1', 'event_ingest', 'completado', 100, 'o1', '2026-01-01',"
                " '2026-01-01')"
            )
        )
    return engine


def _columns(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_old_database_fails_without_the_upgrade(tmp_path):
    engine = _old_database(tmp_path)
    assert "payload" not in _columns(engine, "jobs")
    with engine.connect() as conn:
        # Lo que pasaba antes: el ORM selecciona la columna que no existe.
        session = sessionmaker(bind=conn)()
        try:
            session.query(Job).all()
            raised = False
        except Exception:  # noqa: BLE001
            raised = True
    assert raised


def test_ensure_schema_adds_missing_nullable_columns_and_keeps_the_data(tmp_path):
    engine = _old_database(tmp_path)

    ensure_schema(engine)

    assert "payload" in _columns(engine, "jobs")
    assert "reproducibility" in _columns(engine, "assessments")
    session = sessionmaker(bind=engine)()
    job = session.get(Job, "j1")
    assert job.estado == "completado" and job.payload is None  # dato viejo intacto
    assert session.get(Organization, "o1").nombre == "Vieja Org"
    nuevo = job_service.create_job(session, "event_ingest", org_id="o1", payload={"a": 1})
    assert session.get(Job, nuevo.id).payload == {"a": 1}
    assert session.query(Assessment).count() == 0


def test_upgrade_is_idempotent(tmp_path):
    engine = _old_database(tmp_path)

    first = add_missing_columns(engine)
    second = add_missing_columns(engine)

    assert set(first) == {"jobs.payload", "assessments.reproducibility"}
    assert second == []


def test_ensure_schema_leaves_non_sqlite_engines_to_alembic(tmp_path):
    """`ensure_schema` no hace nada fuera de SQLite: ahi manda Alembic."""

    class Fake:
        class dialect:  # noqa: N801
            name = "postgresql"

    ensure_schema(Fake())  # no debe tocar el motor
