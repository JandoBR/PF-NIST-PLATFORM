"""CRUD de `Job` (docs/04 §4). Sin Redis aqui a proposito: esto solo toca la base de datos, que
es la fuente de verdad del estado de un trabajo; `app/core/queue.py` es lo unico que sabe de
Redis. `app/api` compone ambos al encolar; `app/workers` los compone al procesar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.tables import Job

#: Mismo valor por defecto que `app/workers/core.py`/`logs.py` (ambos lo leen de
#: `JOB_STALE_TIMEOUT_SECONDS`); se repite aqui solo como default de la funcion, no como otra
#: fuente de verdad.
DEFAULT_STALE_TIMEOUT_SECONDS = 600


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


def reap_stale_jobs(
    session: Session, tipo: str, timeout_seconds: int = DEFAULT_STALE_TIMEOUT_SECONDS
) -> list[Job]:
    """Jobs `en_progreso` cuyo `tomado_en` es mas viejo que `timeout_seconds`: el worker que
    los tomo probablemente crasheo antes de llamar a `mark_done`/`mark_failed` (no hay
    heartbeat real todavia, docs/09 §18) -- se marcan `fallido` para que no queden colgados
    para siempre. No se reintentan solos; quien los ve (CLI, API, frontend) decide si
    reintentar. Devuelve los jobs que se marcaron, para que el caller pueda reaccionar (p.ej.
    `app/workers/core.py` tambien marca `fallida` la `Assessment` ligada)."""

    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
    reaped = []
    for job in session.query(Job).filter_by(tipo=tipo, estado="en_progreso").all():
        tomado = job.tomado_en
        if tomado is None:
            continue
        if tomado.tzinfo is None:
            # SQLite descarta tzinfo al guardar `DateTime(timezone=True)`; siempre se escribe
            # en UTC (`mark_taken`), asi que reponerlo es seguro.
            tomado = tomado.replace(tzinfo=UTC)
        if tomado < cutoff:
            mark_failed(
                session,
                job,
                "Job perdido: el worker que lo tomo no respondio a tiempo (probable caida "
                "o reinicio). Volve a intentarlo.",
            )
            reaped.append(job)
    return reaped
