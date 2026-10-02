"""Crear un `Job` y encolarlo, y reintentar uno fallido (docs/11 FN-09).

`jobs.py` (base de datos) y `queue.py` (Redis) no se conocen a proposito; esto es lo unico que
compone ambos. El mensaje que se encola se guarda tambien en `Job.payload` (sin `job_id`): sin eso
un job perdido o fallido no tiene de donde reencolarse, porque las rutas de los archivos subidos
solo viajaban en el mensaje de Redis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.core import jobs as job_service
from app.core.queue import QUEUE_CORE, QUEUE_LOGS, enqueue
from app.models.tables import Assessment, CriterionResultRow, EvidenceRow, Job, PlanRow, Source

QUEUE_BY_TIPO = {"assessment_run": QUEUE_CORE, "event_ingest": QUEUE_LOGS}

#: Claves del payload que apuntan a archivos subidos que el worker vuelve a leer.
_INPUT_PATH_KEYS = ("terraform_path", "ansible_path", "documents_path", "jsonl_path")


class JobRetryError(Exception):
    """El job no se puede reintentar; el mensaje explica por que (la API lo devuelve como 409)."""


def dispatch_job(
    session: Session,
    redis_client: redis.Redis,
    tipo: str,
    payload: dict[str, Any],
    *,
    assessment_id: str | None = None,
    org_id: str | None = None,
) -> Job:
    """Crea el `Job` con su `payload` y encola el mensaje (`payload` + `job_id`)."""

    job = job_service.create_job(
        session, tipo, assessment_id=assessment_id, org_id=org_id, payload=payload
    )
    enqueue(redis_client, QUEUE_BY_TIPO[tipo], {"job_id": job.id, **payload})
    return job


def _missing_inputs(payload: dict[str, Any]) -> list[str]:
    return [
        str(payload[key])
        for key in _INPUT_PATH_KEYS
        if payload.get(key) and not Path(payload[key]).exists()
    ]


def _reset_failed_assessment(session: Session, assessment: Assessment) -> None:
    """Deja la evaluacion como recien creada. Una corrida que fallo despues de guardar resultados
    (p. ej. al generar los planes) los dejaria duplicados al volver a correr."""

    for model in (PlanRow, CriterionResultRow, EvidenceRow, Source):
        session.query(model).filter_by(assessment_id=assessment.id).delete()
    assessment.estado = "pendiente"
    assessment.error = None
    session.commit()


def retry_job(session: Session, redis_client: redis.Redis, job: Job) -> Job:
    """Reencola un job `fallido` con las mismas entradas y devuelve el job nuevo. La evaluacion
    ligada se reutiliza (vuelve a `pendiente`) en vez de crear otra: asi el historial no se llena
    de intentos y la evaluacion anterior de la que hereda sigue siendo la misma."""

    if job.estado != "fallido":
        raise JobRetryError(f"Solo se puede reintentar un job fallido (este esta {job.estado!r}).")
    if job.payload is None:
        raise JobRetryError(
            "Este job es anterior al guardado de entradas: no hay de donde reencolarlo. "
            "Vuelve a crear la evaluacion o la ingesta."
        )
    missing = _missing_inputs(job.payload)
    if missing:
        raise JobRetryError(
            "Ya no existen los archivos del job: " + ", ".join(missing) + ". Vuelve a subirlos."
        )

    if job.assessment_id is not None:
        assessment = session.get(Assessment, job.assessment_id)
        if assessment is None or assessment.estado != "fallida":
            raise JobRetryError("La evaluacion de este job ya no esta fallida (ya se reintento).")
        _reset_failed_assessment(session, assessment)

    return dispatch_job(
        session,
        redis_client,
        job.tipo,
        job.payload,
        assessment_id=job.assessment_id,
        org_id=job.org_id,
    )
