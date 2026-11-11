"""Guarda de migraciones Alembic (cierra el gap del registro §6/§11): el resto de los tests usan
`create_all`, asi que un error en la cadena de migraciones no se detectaba en CI. Aqui se corre
`alembic upgrade head` sobre una BD efimera y se verifica el esquema real. Cubre el incidente de
`render_as_batch` en SQLite (doc 09 §10)."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
    "event_ingests",
    "log_patterns",
    "incidents",
}


def _upgrade(revision: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    command.upgrade(cfg, revision)


def _upgrade_head() -> None:
    _upgrade("head")


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
    assert unicas == [["correlation_key", "org_id", "scope"]]


def test_degradado_migration_backfills_existing_criterion_results(tmp_path, monkeypatch):
    """La columna NOT NULL nueva de aa43bbfb8944 no puede fallar con filas ya guardadas."""

    db_path = tmp_path / "degradado.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    _upgrade("1131f3a55f64")

    engine = create_engine(f"sqlite:///{db_path}")
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
                " criterion_version, estado, explanation, evidence_ids)"
                " VALUES ('cr1', 'a1', 'CR-01', 1, 'cumple', 'ok', '[]')"
            )
        )

    _upgrade("e3911d3a9d74")

    with engine.begin() as conn:
        degradado = conn.execute(
            text("SELECT degradado FROM criterion_results WHERE id = 'cr1'")
        ).scalar_one()
    assert degradado in (0, False)

    columnas = {c["name"]: c for c in inspect(engine).get_columns("criterion_results")}
    assert columnas["degradado"]["nullable"] is False


def test_ops_migration_backfills_existing_plans(tmp_path, monkeypatch):
    """hipotesis/comprobaciones_seguras (NOT NULL) se agregan con [] a los planes existentes."""

    db_path = tmp_path / "planes.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    _upgrade("e3911d3a9d74")

    engine = create_engine(f"sqlite:///{db_path}")
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
                "INSERT INTO plans (id, assessment_id, criterion_id, origen, titulo, prioridad,"
                " objetivo, pasos, verificacion, dependencias, generado_por, estado, creado_en)"
                " VALUES ('p1', 'a1', 'CR-01', 'criterio', 'Plan viejo', 'alta', 'objetivo',"
                " '[]', 'verificar', '[]', 'manual', 'pendiente', '2026-01-01')"
            )
        )

    _upgrade_head()

    with engine.begin() as conn:
        hipotesis, comprobaciones = conn.execute(
            text("SELECT hipotesis, comprobaciones_seguras FROM plans WHERE id = 'p1'")
        ).one()
    assert hipotesis == "[]"
    assert comprobaciones == "[]"

    columnas = {c["name"]: c for c in inspect(engine).get_columns("plans")}
    assert columnas["hipotesis"]["nullable"] is False
    assert columnas["comprobaciones_seguras"]["nullable"] is False


def test_existing_incidents_survive_the_scope_migration(tmp_path, monkeypatch):
    """La migracion agrega scope a la clave sin tocar las filas existentes."""

    db_path = tmp_path / "scope.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    _upgrade("b7e2f4c19d55")

    columnas = (
        "id, org_id, scope, correlation_key, titulo, estado, severidad, first_event_time,"
        " last_event_time, event_ids, criterios, timeline, creado_en, actualizado_en"
    )

    def incidente(ident: str, scope: str) -> str:
        return (
            f"INSERT INTO incidents ({columnas}) VALUES ("
            f"'{ident}', 'o1', '{scope}', 'ck', 't', 'open', 'media', '2026-01-01',"
            " '2026-01-01', '[]', '[]', '[]', '2026-01-01', '2026-01-01')"
        )

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, nombre) VALUES ('o1', 'Org')"))
        conn.execute(text(incidente("i1", "entorno:produccion")))

    _upgrade_head()

    with engine.begin() as conn:
        conn.execute(text(incidente("i2", "entorno:staging")))
        total = conn.execute(text("SELECT count(*) FROM incidents")).scalar_one()

    assert total == 2


def test_event_ingest_migration_keeps_existing_events_as_legacy(tmp_path, monkeypatch):
    """Los eventos guardados antes de la identidad por ingesta quedan sin `ingest_id` (legacy)."""

    db_path = tmp_path / "ingestas.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    _upgrade("f3a1c9d2e4b7")

    engine = create_engine(f"sqlite:///{db_path}")
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

    _upgrade_head()

    inspector = inspect(engine)
    assert "event_ingests" in inspector.get_table_names()
    columnas = {c["name"]: c for c in inspector.get_columns("events")}
    assert columnas["ingest_id"]["nullable"] is True
    with engine.begin() as conn:
        ingest_id = conn.execute(text("SELECT ingest_id FROM events WHERE id = 'ev1'")).scalar_one()
        ingestas = conn.execute(text("SELECT count(*) FROM event_ingests")).scalar_one()
    assert ingest_id is None and ingestas == 0
