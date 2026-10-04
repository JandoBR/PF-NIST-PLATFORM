"""Guarda de migraciones Alembic (cierra el gap del registro §6/§11): el resto de los tests usan
`create_all`, asi que un error en la cadena de migraciones no se detectaba en CI. Aqui se corre
`alembic upgrade head` sobre una BD efimera y se verifica el esquema real. Cubre el incidente de
`render_as_batch` en SQLite (doc 09 §10)."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "alembic_version",
    "organizations",
    "assessments",
    "sources",
    "evidence",
    "criterion_results",
    "plans",
    "events",
    "log_patterns",
    "incidents",
}


def _upgrade_head() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    command.upgrade(cfg, "head")


def test_alembic_upgrade_head_creates_expected_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _upgrade_head()

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    assert EXPECTED_TABLES <= set(inspector.get_table_names())


def test_migrated_plans_table_matches_ops_model(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _upgrade_head()

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"]: c for c in inspector.get_columns("plans")}
    # El plan de un incidente no tiene assessment_id (docs/08 §7): nullable desde la migracion.
    assert columns["assessment_id"]["nullable"] is True
    assert "incident_id" in columns


def test_migrated_jobs_table_stores_the_retry_payload(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _upgrade_head()

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"]: c for c in inspector.get_columns("jobs")}
    # Nullable: los jobs anteriores a FN-09 no tienen entradas guardadas y no son reintentables.
    assert columns["payload"]["nullable"] is True


def test_migrated_log_patterns_store_their_event_origins(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _upgrade_head()

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"]: c for c in inspector.get_columns("log_patterns")}
    assert columns["fuentes"]["nullable"] is True  # patrones anteriores a FN-07: sin origen


def test_migrated_jobs_table_stores_the_result(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _upgrade_head()

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"]: c for c in inspector.get_columns("jobs")}
    assert columns["resultado"]["nullable"] is True


def test_migrated_incidents_store_the_closing_reason(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _upgrade_head()

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    columns = {c["name"]: c for c in inspector.get_columns("incidents")}
    assert columns["motivo_cierre"]["nullable"] is True


def test_migrated_incidents_correlation_key_is_unique_per_organization(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _upgrade_head()

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    unicas = [sorted(u["column_names"]) for u in inspector.get_unique_constraints("incidents")]
    assert unicas == [["correlation_key", "org_id"]]
