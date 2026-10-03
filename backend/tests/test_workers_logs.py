"""`app.workers.logs.process_message` es la logica real que corre `worker-logs` -- probada
directamente, igual que test_workers_core.py."""

from __future__ import annotations

from pathlib import Path

from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core import operations
from app.models.tables import Assessment, Job
from app.workers import logs as worker_logs
from tests.conftest import FakeRedis

SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


def _completed_assessment(db_session, methodology, org_nombre: str) -> Assessment:
    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name=org_nombre, scope="entorno:produccion"
    )
    assessment.estado = "completada"
    db_session.commit()
    return assessment


def test_process_message_ingests_events_and_opens_an_incident(db_session, methodology):
    org = svc.get_or_create_organization(db_session, "Empresa Worker Eventos")
    db_session.commit()
    job = job_service.create_job(db_session, "event_ingest", org_id=org.id)

    worker_logs.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "org_id": org.id,
            "org_nombre": org.nombre,
            "jsonl_path": str(SCENARIOS / "e1b_fallos_sin_alerta.jsonl"),
            "ai_requested": False,
        },
    )

    db_session.refresh(job)
    assert job.estado == "completado"
    # FN-03: el job guarda que hizo (nuevos vs ya existentes), ya que la API devuelve solo `job_id`.
    assert job.resultado == {
        "eventos_leidos": 6,
        "eventos_nuevos": 6,
        "eventos_existentes": 0,
        "patrones_nuevos": 1,
        "incidentes_nuevos": 1,
        "incidentes_actualizados": 0,
    }

    incidents = operations.list_incidents(db_session, org.nombre)
    assert len(incidents) == 1
    assert incidents[0].severidad == "media"


def test_ingest_refreshes_maturity_when_enough_new_patterns(db_session, methodology):
    """Una ingesta con suficientes patrones nuevos encola una reevaluacion del org+scope.

    Ver docs/08 §8.
    """

    org = svc.get_or_create_organization(db_session, "Empresa Refresco Madurez")
    db_session.commit()
    _completed_assessment(db_session, methodology, org.nombre)

    redis = FakeRedis()
    job = job_service.create_job(db_session, "event_ingest", org_id=org.id)
    worker_logs.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "org_id": org.id,
            "org_nombre": org.nombre,
            "jsonl_path": str(SCENARIOS / "incidentes_demo.jsonl"),
            "ai_requested": False,
        },
        redis,
    )

    db_session.refresh(job)
    assert job.estado == "completado"

    # Se creo una evaluacion nueva (pendiente) y se encolo su `assessment_run`.
    assessments = svc.list_assessments(db_session, org_id=org.id)
    assert len(assessments) == 2
    runs = db_session.query(Job).filter_by(tipo="assessment_run").all()
    assert len(runs) == 1
    assert runs[0].assessment_id is not None


def test_ingest_does_not_refresh_below_threshold(db_session, methodology):
    org = svc.get_or_create_organization(db_session, "Empresa Refresco Debajo")
    db_session.commit()
    _completed_assessment(db_session, methodology, org.nombre)

    job = job_service.create_job(db_session, "event_ingest", org_id=org.id)
    worker_logs.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "org_id": org.id,
            "org_nombre": org.nombre,
            "jsonl_path": str(SCENARIOS / "e1b_fallos_sin_alerta.jsonl"),  # 1 patron
            "ai_requested": False,
        },
        FakeRedis(),
    )

    assert len(svc.list_assessments(db_session, org_id=org.id)) == 1
    assert db_session.query(Job).filter_by(tipo="assessment_run").count() == 0


def test_ingest_without_previous_assessment_does_not_refresh(db_session, methodology):
    """Los eventos/incidentes no dependen de una evaluacion: sin evaluacion previa, la ingesta
    igual funciona y simplemente no hay nada que refrescar (docs/08 §8)."""

    org = svc.get_or_create_organization(db_session, "Empresa Refresco Sin Previa")
    db_session.commit()

    job = job_service.create_job(db_session, "event_ingest", org_id=org.id)
    worker_logs.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "org_id": org.id,
            "org_nombre": org.nombre,
            "jsonl_path": str(SCENARIOS / "incidentes_demo.jsonl"),
            "ai_requested": False,
        },
        FakeRedis(),
    )

    db_session.refresh(job)
    assert job.estado == "completado"
    assert len(operations.list_incidents(db_session, org.nombre)) == 3
    assert db_session.query(Job).filter_by(tipo="assessment_run").count() == 0


def test_process_message_marks_job_failed_on_bad_path(db_session, methodology):
    org = svc.get_or_create_organization(db_session, "Empresa Worker Eventos Falla")
    db_session.commit()
    job = job_service.create_job(db_session, "event_ingest", org_id=org.id)

    worker_logs.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "org_id": org.id,
            "org_nombre": org.nombre,
            "jsonl_path": "/no/existe/esta/ruta.jsonl",
            "ai_requested": False,
        },
    )

    db_session.refresh(job)
    assert job.estado == "fallido"
    assert job.error


def test_logs_worker_fails_a_job_with_a_newer_message_version(db_session, methodology):
    job = job_service.create_job(db_session, "event_ingest")

    worker_logs.process_message(
        db_session,
        methodology,
        {"schema_version": 99, "job_id": job.id, "org_nombre": "x", "jsonl_path": "no-importa"},
    )

    db_session.refresh(job)
    assert job.estado == "fallido" and "schema_version=99" in job.error
    assert job.tomado_en is None


def test_reingesting_reports_zero_new_events_in_the_job_result(db_session, methodology):
    org = svc.get_or_create_organization(db_session, "Empresa Reingesta")
    db_session.commit()
    mensaje = {
        "org_id": org.id,
        "org_nombre": org.nombre,
        "jsonl_path": str(SCENARIOS / "e1b_fallos_sin_alerta.jsonl"),
        "ai_requested": False,
    }
    for _ in range(2):
        job = job_service.create_job(db_session, "event_ingest", org_id=org.id)
        worker_logs.process_message(db_session, methodology, {"job_id": job.id, **mensaje})

    db_session.refresh(job)
    assert job.resultado["eventos_nuevos"] == 0 and job.resultado["eventos_existentes"] == 6
    assert job.resultado["patrones_nuevos"] == 0 and job.resultado["incidentes_nuevos"] == 0


def test_a_failed_ingest_has_no_result(db_session, methodology):
    job = job_service.create_job(db_session, "event_ingest")

    worker_logs.process_message(
        db_session,
        methodology,
        {"job_id": job.id, "org_nombre": "x", "jsonl_path": "/no/existe.jsonl"},
    )

    db_session.refresh(job)
    assert job.estado == "fallido" and job.resultado is None
