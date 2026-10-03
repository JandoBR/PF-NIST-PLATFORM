"""CRUD de `Job` (docs/04 §4). Sin Redis aqui a proposito: esto solo toca la base de datos, que
es la fuente de verdad del estado de un trabajo; `app/core/queue.py` es lo unico que sabe de
Redis. `app/api` compone ambos al encolar; `app/workers` los compone al procesar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.tables import Assessment, Job

#: Mismo valor por defecto que `app/workers/core.py`/`logs.py` (ambos lo leen de
#: `JOB_STALE_TIMEOUT_SECONDS`); se repite aqui solo como default de la funcion, no como otra
#: fuente de verdad.
DEFAULT_STALE_TIMEOUT_SECONDS = 600

#: Un job `pendiente` (nunca tomado por ningun worker) se falla mucho antes que uno `en_progreso`:
#: si hubiera un worker sano, lo habria tomado en segundos. Sin esto, un stack sin `worker-core`
#: deja el job `pendiente` para siempre y el cliente que sondea nunca ve un estado terminal
#: (docs/09 §20).
DEFAULT_PENDING_TIMEOUT_SECONDS = 120


def create_job(
    session: Session,
    tipo: str,
    *,
    assessment_id: str | None = None,
    org_id: str | None = None,
    payload: dict | None = None,
) -> Job:
    job = Job(tipo=tipo, assessment_id=assessment_id, org_id=org_id, payload=payload)
    session.add(job)
    session.commit()
    return job


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def org_jobs_query(session: Session, org_id: str):
    """Jobs de una organizacion. Un `event_ingest` lleva `org_id`; un `assessment_run` solo lleva
    `assessment_id` (la organizacion sale de la evaluacion), asi que se buscan los dos caminos."""

    return session.query(Job).filter(
        or_(
            Job.org_id == org_id,
            Job.assessment_id.in_(select(Assessment.id).where(Assessment.org_id == org_id)),
        )
    )


def list_jobs(
    session: Session,
    org_id: str,
    *,
    estado: str | None = None,
    tipo: str | None = None,
    limit: int = 50,
) -> list[Job]:
    """Los jobs mas recientes de la organizacion, opcionalmente filtrados por estado y tipo."""

    query = org_jobs_query(session, org_id)
    if estado is not None:
        query = query.filter(Job.estado == estado)
    if tipo is not None:
        query = query.filter(Job.tipo == tipo)
    return query.order_by(Job.creado_en.desc(), Job.id).limit(limit).all()


def mark_taken(session: Session, job: Job) -> None:
    job.estado = "en_progreso"
    job.tomado_en = datetime.now(UTC)
    job.actualizado_en = datetime.now(UTC)
    session.commit()


def mark_done(session: Session, job: Job, resultado: dict | None = None) -> None:
    job.estado = "completado"
    job.resultado = resultado
    job.progreso = 100
    job.actualizado_en = datetime.now(UTC)
    session.commit()


def mark_failed(session: Session, job: Job, error: str) -> None:
    job.estado = "fallido"
    job.error = error
    job.actualizado_en = datetime.now(UTC)
    session.commit()


def _as_utc(moment: datetime | None) -> datetime | None:
    """SQLite descarta tzinfo al guardar `DateTime(timezone=True)`; siempre se escribe en UTC,
    asi que reponerlo es seguro."""

    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _stale_message(estado: str) -> str:
    if estado == "pendiente":
        return (
            "El job no fue tomado por ningun worker a tiempo. Revisa que `worker-core`/"
            "`worker-logs` esten corriendo, o volve a intentarlo."
        )
    return (
        "Job perdido: el worker que lo tomo no respondio a tiempo (probable caida o "
        "reinicio). Volve a intentarlo."
    )


def _is_stale(job: Job, stale_timeout_seconds: int, pending_timeout_seconds: int) -> bool:
    """`pendiente` se mide desde `creado_en`; `en_progreso` desde `tomado_en`."""

    now = datetime.now(UTC)
    if job.estado == "pendiente":
        reference, timeout = _as_utc(job.creado_en), pending_timeout_seconds
    elif job.estado == "en_progreso":
        reference, timeout = _as_utc(job.tomado_en) or _as_utc(job.creado_en), stale_timeout_seconds
    else:
        return False
    return reference is not None and reference < now - timedelta(seconds=timeout)


def fail_if_stale(
    session: Session,
    job: Job,
    *,
    stale_timeout_seconds: int = DEFAULT_STALE_TIMEOUT_SECONDS,
    pending_timeout_seconds: int = DEFAULT_PENDING_TIMEOUT_SECONDS,
) -> bool:
    """Marca `fallido` un unico job si se quedo colgado; `True` si lo hizo.

    Variante de `reap_stale_jobs` para un solo job, pensada para `GET /jobs/{id}`: asi un cliente
    que sondea ve un estado terminal aunque no haya ningun worker corriendo que haga el barrido
    (docs/09 §20)."""

    if _is_stale(job, stale_timeout_seconds, pending_timeout_seconds):
        mark_failed(session, job, _stale_message(job.estado))
        return True
    return False


def reap_stale_jobs(
    session: Session,
    tipo: str,
    timeout_seconds: int = DEFAULT_STALE_TIMEOUT_SECONDS,
    pending_timeout_seconds: int = DEFAULT_PENDING_TIMEOUT_SECONDS,
) -> list[Job]:
    """Jobs `en_progreso` cuyo `tomado_en` es mas viejo que `timeout_seconds` (el worker que los
    tomo probablemente crasheo antes de `mark_done`/`mark_failed`, no hay heartbeat real todavia,
    docs/09 §18), o `pendiente` que nunca fue tomado (no hay worker consumiendo la cola). Se
    marcan `fallido` para que no queden colgados para siempre. No se reintentan solos; quien los ve
    decide si reintentar. Devuelve los jobs marcados, para que el caller reaccione (p. ej.
    `app/workers/core.py` tambien marca `fallida` la `Assessment` ligada)."""

    reaped = []
    for job in (
        session.query(Job)
        .filter(Job.tipo == tipo, Job.estado.in_(["pendiente", "en_progreso"]))
        .all()
    ):
        if _is_stale(job, timeout_seconds, pending_timeout_seconds):
            mark_failed(session, job, _stale_message(job.estado))
            reaped.append(job)
    return reaped
