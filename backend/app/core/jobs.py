"""CRUD de `Job` (docs/04 §4). Esto es la fuente de verdad del estado de un trabajo; encolar es
cosa de `app/core/queue.py`, que `app/api` compone con esto y `app/workers` compone al procesar.
El unico contacto con Redis aqui es de lectura: consultar el heartbeat de los workers para no
declarar perdido un job que solo esta esperando en la cola (docs/04 §5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.queue import QUEUE_BY_TIPO, job_worker_alive, worker_alive
from app.models.tables import Assessment, Job

#: Mismo valor por defecto que `app/workers/core.py`/`logs.py` (ambos lo leen de
#: `JOB_STALE_TIMEOUT_SECONDS`); se repite aqui solo como default de la funcion, no como otra
#: fuente de verdad.
DEFAULT_STALE_TIMEOUT_SECONDS = 600

#: Un job `pendiente` (nunca tomado por ningun worker) se falla mucho antes que uno `en_progreso`:
#: si hubiera un worker sano, lo habria tomado en segundos. Sin esto, un stack sin `worker-core`
#: deja el job `pendiente` para siempre y el cliente que sondea nunca ve un estado terminal
#: (docs/09 §20). Solo se aplica si ademas no hay ningun worker con heartbeat vivo en su cola.
DEFAULT_PENDING_TIMEOUT_SECONDS = 120

#: Motivo exacto con el que el reaper marca un job que murio esperando en la cola. ``tomado_en``
#: nulo + este texto identifica el caso que el worker puede adoptar si el mensaje sigue en Redis
#: (docs/09 §104).
LOST_IN_QUEUE_ERROR = (
    "El job no fue tomado por ningun worker a tiempo. Revisa que `worker-core`/"
    "`worker-logs` esten corriendo, o volve a intentarlo."
)


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


def fail_linked_assessment(session: Session, job: Job) -> None:
    """Si el job fallido tenia una evaluacion ligada que quedo `pendiente`/`en_progreso`, la marca
    `fallida` con el mismo error. Sin esto el job se ve fallido pero la evaluacion queda en un
    estado no terminal para siempre (el worker que murio nunca llego a marcarla)."""

    if not job.assessment_id:
        return
    assessment = session.get(Assessment, job.assessment_id)
    if assessment is not None and assessment.estado in ("pendiente", "en_progreso"):
        assessment.estado = "fallida"
        assessment.error = job.error
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
        return LOST_IN_QUEUE_ERROR
    return (
        "Job perdido: el worker que lo tomo no respondio a tiempo (probable caida o "
        "reinicio). Volve a intentarlo."
    )


def _is_stale(
    job: Job,
    stale_timeout_seconds: int,
    pending_timeout_seconds: int,
    *,
    queue_worker_alive: bool | None,
    job_alive: bool | None,
) -> bool:
    """`pendiente` se mide desde `creado_en`; `en_progreso` desde `tomado_en`.

    Estar en la cola no es un fallo: un job `pendiente` solo se declara perdido cuando el timeout
    paso **y** el chequeo de heartbeat dice que no hay ningun worker vivo en su cola. Un
    `en_progreso` solo se reapea cuando el latido de ese job desaparecio (el worker que lo tomo
    murio); mientras el worker lo refresque, un pipeline de IA largo no se mata por viejo."""

    now = datetime.now(UTC)
    if job.estado == "pendiente":
        reference, timeout = _as_utc(job.creado_en), pending_timeout_seconds
    elif job.estado == "en_progreso":
        reference, timeout = _as_utc(job.tomado_en) or _as_utc(job.creado_en), stale_timeout_seconds
    else:
        return False
    if reference is None or reference >= now - timedelta(seconds=timeout):
        return False
    if job.estado == "pendiente":
        return queue_worker_alive is False
    return job_alive is not True


def fail_if_stale(
    session: Session,
    job: Job,
    *,
    stale_timeout_seconds: int = DEFAULT_STALE_TIMEOUT_SECONDS,
    pending_timeout_seconds: int = DEFAULT_PENDING_TIMEOUT_SECONDS,
    redis_client=None,
) -> bool:
    """Marca `fallido` un unico job si se quedo colgado; `True` si lo hizo.

    Variante de `reap_stale_jobs` para un solo job, pensada para `GET /jobs/{id}`: asi un cliente
    que sondea ve un estado terminal aunque no haya ningun worker corriendo que haga el barrido
    (docs/09 §20). `redis_client` es lo que permite distinguir "esperando en la cola" de
    "perdido": sin el, un `pendiente` nunca se falla y un `en_progreso` cae al timeout viejo."""

    queue = QUEUE_BY_TIPO.get(job.tipo)
    job_alive = job_worker_alive(redis_client, job.id) if job.estado == "en_progreso" else None
    if _is_stale(
        job,
        stale_timeout_seconds,
        pending_timeout_seconds,
        queue_worker_alive=worker_alive(redis_client, queue) if queue else None,
        job_alive=job_alive,
    ):
        mark_failed(session, job, _stale_message(job.estado))
        return True
    return False


def reap_stale_jobs(
    session: Session,
    tipo: str,
    timeout_seconds: int = DEFAULT_STALE_TIMEOUT_SECONDS,
    pending_timeout_seconds: int = DEFAULT_PENDING_TIMEOUT_SECONDS,
    *,
    redis_client=None,
) -> list[Job]:
    """Jobs `en_progreso` cuyo worker dejo de latir (el heartbeat del job expiro y ademas paso
    `timeout_seconds`), o `pendiente` que nadie tomo y cuya cola no tiene ningun worker con
    heartbeat vivo (docs/04 §5, docs/09 §104). Se marcan `fallido` para que no queden colgados
    para siempre. No se reintentan solos; quien los ve decide si reintentar. Devuelve los jobs
    marcados, para que el caller reaccione (p. ej. `app/workers/core.py` tambien marca `fallida` la
    `Assessment` ligada)."""

    queue = QUEUE_BY_TIPO.get(tipo)
    queue_worker_alive = worker_alive(redis_client, queue) if queue else None
    reaped = []
    for job in (
        session.query(Job)
        .filter(Job.tipo == tipo, Job.estado.in_(["pendiente", "en_progreso"]))
        .all()
    ):
        job_alive = job_worker_alive(redis_client, job.id) if job.estado == "en_progreso" else None
        if _is_stale(
            job,
            timeout_seconds,
            pending_timeout_seconds,
            queue_worker_alive=queue_worker_alive,
            job_alive=job_alive,
        ):
            mark_failed(session, job, _stale_message(job.estado))
            reaped.append(job)
    return reaped


def was_lost_in_queue(job: Job) -> bool:
    """El reaper lo marco `fallido` mientras esperaba en la cola y ningun worker llego a tomarlo."""

    return job.estado == "fallido" and job.error == LOST_IN_QUEUE_ERROR and job.tomado_en is None


def _has_successor(session: Session, job: Job) -> bool:
    """Hay otro intento posterior para la misma entrada? Un reintento crea un job nuevo
    (`dispatch.retry_job`); sea que este esperando, corriendo o ya haya terminado, este mensaje
    viejo no debe volver a ejecutarse."""

    query = session.query(Job).filter(
        Job.tipo == job.tipo,
        Job.id != job.id,
        Job.estado.in_(["pendiente", "en_progreso", "completado"]),
    )
    if job.assessment_id is not None:
        return query.filter(Job.assessment_id == job.assessment_id).first() is not None
    if job.org_id is None:
        return False
    return any(
        candidate.payload == job.payload
        for candidate in query.filter(Job.org_id == job.org_id).all()
    )


def adopt_lost_in_queue(session: Session, job: Job) -> bool:
    """`True` si el worker debe ejecutar este mensaje: el job sigue `pendiente` o fue dado por
    perdido en la cola y nadie lo reintento. En el segundo caso lo devuelve a `pendiente` (y la
    `Assessment` ligada a `pendiente`) para que `mark_taken` lo tome con normalidad.

    Defensa en profundidad: el reaper puede haber fallado el job justo antes de que el worker
    sacara el mensaje de Redis; descartarlo perderia trabajo que nadie mas va a hacer."""

    if job.estado == "pendiente":
        return True
    if not was_lost_in_queue(job) or _has_successor(session, job):
        return False
    job.estado = "pendiente"
    job.error = None
    job.actualizado_en = datetime.now(UTC)
    if job.assessment_id is not None:
        assessment = session.get(Assessment, job.assessment_id)
        if assessment is not None and assessment.estado == "fallida":
            assessment.estado = "pendiente"
            assessment.error = None
    session.commit()
    return True
