"""`ensure_schema` pone al dia una BD SQLite de dev creada antes de un cambio de modelo (§48).

`create_all` no agrega columnas, y una BD vieja fallaba con "no such column" aunque los tests (que
usan BD nuevas) pasaran. Tampoco alcanza con agregar columnas nullable: una NOT NULL nueva, un
cambio de nullability o una unique vieja (incidentes por org antes de separar por scope) exigen
reconstruir la tabla."""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.core import jobs as job_service
from app.core.db import add_missing_columns, ensure_schema
from app.models.tables import (
    Assessment,
    CriterionResultRow,
    Job,
    Organization,
    PlanRow,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


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


def test_ensure_schema_adds_the_ingest_identity_to_old_events(tmp_path, monkeypatch):
    """Una BD de dev sin `events.ingest_id` ni `event_ingests` recibe ambos sin perder eventos."""

    engine = _legacy_database(tmp_path, monkeypatch, "f3a1c9d2e4b7")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, nombre) VALUES ('o1', 'Org')"))
        conn.execute(
            text(
                "INSERT INTO events (id, org_id, scope, event_id, event_time, tipo, recurso,"
                " detalle, source_id, creado_en) VALUES ('ev1', 'o1', 'entorno:produccion',"
                " 'e-1', '2026-09-20 03:10:00', 'auth_failure', 'srv-app-01', '{}',"
                " 'siem-corp', '2026-09-20 03:11:00')"
            )
        )

    ensure_schema(engine)

    assert "ingest_id" in _columns(engine, "events")
    assert "event_ingests" in inspect(engine).get_table_names()
    with engine.begin() as conn:
        ingest_id = conn.execute(text("SELECT ingest_id FROM events WHERE id = 'ev1'")).scalar_one()
    assert ingest_id is None


def test_ensure_schema_leaves_non_sqlite_engines_to_alembic(tmp_path):
    """`ensure_schema` no hace nada fuera de SQLite: ahi manda Alembic."""

    class Fake:
        class dialect:  # noqa: N801
            name = "postgresql"

    ensure_schema(Fake())  # no debe tocar el motor


def _legacy_database(tmp_path, monkeypatch, revision: str):
    """Una BD creada por Alembic en una revision vieja, sin `alembic_version` (como las que creo
    `create_all`): es el caso que `alembic upgrade head` no puede retomar solo."""

    db_path = tmp_path / f"legacy-{revision}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    command.upgrade(cfg, revision)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
    return engine


def _incidente(ident: str, scope: str, titulo: str = "t") -> str:
    return (
        "INSERT INTO incidents (id, org_id, scope, correlation_key, titulo, estado, severidad,"
        " first_event_time, last_event_time, event_ids, criterios, timeline, creado_en,"
        " actualizado_en) VALUES ("
        f"'{ident}', 'o1', '{scope}', 'ck', '{titulo}', 'open', 'media', '2026-01-01',"
        " '2026-01-01', '[]', '[]', '[]', '2026-01-01', '2026-01-01')"
    )


@pytest.mark.parametrize("revision", ["277dd5fd4475", "b7e2f4c19d55"])
def test_ensure_schema_relaxes_old_incident_keys_within_two_scopes(tmp_path, monkeypatch, revision):
    """Las dos unique viejas (solo correlation_key, y org+correlation_key) se reemplazan por
    org+scope+correlation_key; el mismo host/hora puede vivir en produccion y staging."""

    engine = _legacy_database(tmp_path, monkeypatch, revision)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, nombre) VALUES ('o1', 'Org')"))
        conn.execute(text(_incidente("i1", "entorno:produccion", "Produccion")))

    ensure_schema(engine)

    with engine.begin() as conn:
        conn.execute(text(_incidente("i2", "entorno:staging", "Staging")))
        filas = conn.execute(text("SELECT scope, titulo FROM incidents ORDER BY scope")).all()

    assert filas == [("entorno:produccion", "Produccion"), ("entorno:staging", "Staging")]


def test_ensure_schema_backfills_new_not_null_columns_and_keeps_the_rows(tmp_path):
    """degradado (bool) e hipotesis/comprobaciones_seguras (JSON) son NOT NULL sin default en el
    modelo; una BD que ya tenia filas debe recibir el default en vez de un error."""

    engine = create_engine(f"sqlite:///{tmp_path / 'not-null.db'}")
    ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, nombre) VALUES ('o1', 'Org')"))
        conn.execute(
            text(
                "INSERT INTO assessments (id, org_id, estado, methodology_version, scope,"
                " creado_en) VALUES ('a1', 'o1', 'completada', 'v1', 'entorno:produccion',"
                " '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO criterion_results (id, assessment_id, criterion_id,"
                " criterion_version, estado, explanation, evidence_ids, degradado)"
                " VALUES ('cr1', 'a1', 'CR-01', 1, 'cumple', 'ok', '[]', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO plans (id, assessment_id, criterion_id, origen, titulo, prioridad,"
                " objetivo, pasos, verificacion, dependencias, generado_por, estado, hipotesis,"
                " comprobaciones_seguras, creado_en) VALUES ('p1', 'a1', 'CR-01', 'criterio',"
                " 'Plan viejo', 'alta', 'objetivo', '[]', 'verificar', '[]', 'manual',"
                " 'pendiente', '[]', '[]', '2026-01-01')"
            )
        )
        # Esquema anterior a degradado/hipotesis/comprobaciones_seguras, con datos ya guardados.
        conn.execute(text("ALTER TABLE criterion_results DROP COLUMN degradado"))
        conn.execute(text("ALTER TABLE plans DROP COLUMN hipotesis"))
        conn.execute(text("ALTER TABLE plans DROP COLUMN comprobaciones_seguras"))

    ensure_schema(engine)

    session = sessionmaker(bind=engine)()
    try:
        criterio = session.get(CriterionResultRow, "cr1")
        plan = session.get(PlanRow, "p1")
        assert criterio.degradado is False  # backfill con el default del modelo
        assert plan.hipotesis == []
        assert plan.comprobaciones_seguras == []
    finally:
        session.close()

    columnas_criterio = {c["name"]: c for c in inspect(engine).get_columns("criterion_results")}
    columnas_plan = {c["name"]: c for c in inspect(engine).get_columns("plans")}
    assert columnas_criterio["degradado"]["nullable"] is False
    assert columnas_plan["hipotesis"]["nullable"] is False
    assert columnas_plan["comprobaciones_seguras"]["nullable"] is False

    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM plans")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM criterion_results")).scalar_one() == 1
