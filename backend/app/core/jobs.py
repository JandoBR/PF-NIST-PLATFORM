"""CRUD de `Job` (docs/04 §4). Sin Redis aqui a proposito: esto solo toca la base de datos, que
es la fuente de verdad del estado de un trabajo; `app/core/queue.py` es lo unico que sabe de
Redis. `app/api` compone ambos al encolar; `app/workers` los compone al procesar.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.tables import Job


def create_job(
    session: Session, tipo: str, *, assessment_id: str | None = None, org_id: str | None = None
) -> Job:
    job = Job(tipo=tipo, assessment_id=assessment_id, org_id=org_id)
    session.add(job)
    session.commit()
    return job


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def mark_taken(session: Session, job: Job) -> None:
    job.estado = "en_progreso"
    job.tomado_en = datetime.now(UTC)
    job.actualizado_en = datetime.now(UTC)
    session.commit()


def mark_done(session: Session, job: Job) -> None:
    job.estado = "completado"
    job.progreso = 100
    job.actualizado_en = datetime.now(UTC)
    session.commit()


def mark_failed(session: Session, job: Job, error: str) -> None:
    job.estado = "fallido"
    job.error = error
    job.actualizado_en = datetime.now(UTC)
    session.commit()
