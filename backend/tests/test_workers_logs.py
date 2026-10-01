"""`app.workers.logs.process_message` es la logica real que corre `worker-logs` -- probada
directamente, igual que test_workers_core.py."""

from __future__ import annotations

from pathlib import Path

from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.workers import logs as worker_logs

SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


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

    incidents = svc.list_incidents(db_session, org.nombre)
    assert len(incidents) == 1
    assert incidents[0].severidad == "media"


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
