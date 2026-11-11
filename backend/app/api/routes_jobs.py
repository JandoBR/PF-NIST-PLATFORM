"""GET /jobs y GET /jobs/{id} (docs/04 §6): estado de los trabajos encolados por
`POST /assessments`, `POST /assessments/{id}/reevaluate` o `POST /orgs/{id}/events`.

Exige sesion (doc 10): un job de otra organizacion responde 404.

`GET /jobs/{id}` reaprea perezosamente: si el job se quedo `pendiente` sin ningun worker vivo en
su cola (heartbeat, docs/04 §5) o `en_progreso` y el worker que lo tomo dejo de latir, mas alla del
timeout, se marca `fallido` antes de responder. Asi el cliente que sondea siempre termina viendo un
estado terminal aunque no haya ningun worker haciendo el barrido (docs/09 §20). `GET /jobs` hace lo
mismo con los jobs activos de la organizacion antes de listarlos: el historial nunca muestra como
"pendiente" un job que ya esta perdido (docs/09 §45)."""

from __future__ import annotations

import os
from typing import Literal

import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai.guard import check_live_ai_guard
from app.api.deps import get_current_user, get_redis, get_session
from app.api.schemas import JobOut
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core.dispatch import JobRetryError, retry_job
from app.models.tables import Assessment, Job, User

router = APIRouter(tags=["jobs"])

#: Mismos defaults que `app/core/jobs.py`; aqui solo se permite ajustarlos por entorno.
_STALE_TIMEOUT = int(os.environ.get("JOB_STALE_TIMEOUT_SECONDS", "600"))
_PENDING_TIMEOUT = int(os.environ.get("JOB_PENDING_TIMEOUT_SECONDS", "120"))


def _require_job_owned(session: Session, job: Job, user: User) -> None:
    if job.org_id is not None:
        if job.org_id == user.org_id:
            return
    elif job.assessment_id is not None:
        assessment = svc.get_assessment(session, job.assessment_id)
        if assessment is not None and assessment.org_id == user.org_id:
            return
    raise HTTPException(status_code=404, detail=f"No existe el job {job.id!r}.")


def _reap_if_stale(session: Session, job: Job, redis_client: redis.Redis) -> None:
    if job_service.fail_if_stale(
        session,
        job,
        stale_timeout_seconds=_STALE_TIMEOUT,
        pending_timeout_seconds=_PENDING_TIMEOUT,
        redis_client=redis_client,
    ):
        # El reaper de los workers tambien marca la `Assessment` ligada; aqui se hace lo mismo
        # para que `GET /assessments/{id}` no se quede en `pendiente`/`en_progreso` para siempre
        # cuando no hay worker que lo haga.
        job_service.fail_linked_assessment(session, job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    estado: Literal["pendiente", "en_progreso", "completado", "fallido"] | None = None,
    tipo: Literal["assessment_run", "event_ingest"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    redis_client: redis.Redis = Depends(get_redis),
) -> list[JobOut]:
    """Historial de jobs de la organizacion del usuario, del mas reciente al mas antiguo."""

    for job in (
        job_service.org_jobs_query(session, user.org_id)
        .filter(Job.estado.in_(["pendiente", "en_progreso"]))
        .all()
    ):
        _reap_if_stale(session, job, redis_client)
    jobs = job_service.list_jobs(session, user.org_id, estado=estado, tipo=tipo, limit=limit)
    assessment_ids = {job.assessment_id for job in jobs if job.assessment_id}
    estados = (
        dict(
            session.query(Assessment.id, Assessment.estado)
            .filter(Assessment.id.in_(assessment_ids))
            .all()
        )
        if assessment_ids
        else {}
    )
    return [JobOut.from_job(job, assessment_estado=estados.get(job.assessment_id)) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    redis_client: redis.Redis = Depends(get_redis),
) -> JobOut:
    job = job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No existe el job {job_id!r}.")
    _require_job_owned(session, job, user)

    _reap_if_stale(session, job, redis_client)
    assessment = session.get(Assessment, job.assessment_id) if job.assessment_id else None
    return JobOut.from_job(job, assessment_estado=assessment.estado if assessment else None)


@router.post("/jobs/{job_id}/retry", response_model=JobOut, status_code=202)
def retry_failed_job(
    job_id: str,
    confirm_live_ai: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    redis_client: redis.Redis = Depends(get_redis),
) -> JobOut:
    """Reencola un job fallido con las mismas entradas (docs/11 FN-09). Devuelve el job nuevo.

    Si el job usaba la IA real, pasa por el mismo guard de costo que la creacion: el permiso para
    gastar no se hereda del intento anterior."""

    job = job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No existe el job {job_id!r}.")
    _require_job_owned(session, job, user)

    guard_error = check_live_ai_guard(
        bool((job.payload or {}).get("ai_requested")),
        os.environ.get("DEEPSEEK_API_KEY"),
        confirm_live_ai,
    )
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)
    try:
        return JobOut.from_job(retry_job(session, redis_client, job))
    except JobRetryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
