"""GET /orgs, POST /orgs/{org_id}/events, GET /orgs/{org_id}/incidents (docs/04 §6).

Todas exigen sesion (doc 10): el cliente ve solo su organizacion, y no puede crear organizaciones
(eso lo hace el proveedor por seed/CLI). Un `org_id` ajeno responde 404.

`POST /orgs/{org_id}/events` encola el pipeline de eventos en `worker-logs` en vez de correrlo
en el request (docs/09 §16), guardando el `.jsonl` subido en un directorio persistente (el worker
lo lee despues, en otro proceso)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import redis
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai.guard import check_live_ai_guard
from app.api.deps import get_current_user, get_methodology, get_redis, get_session, require_same_org
from app.api.schemas import EventsAccepted, IncidentOut, OrganizationOut
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core.queue import QUEUE_LOGS, enqueue
from app.core.uploads import safe_filename
from app.methodology.loader import Methodology
from app.models.tables import User

router = APIRouter(tags=["orgs"])

#: Mismo patron que `UPLOADS_DIR` en `routes_assessments.py`: persistente, no un tempfile que se
#: borra al terminar el request -- `worker-logs` lo lee despues, en otro proceso.
EVENTS_UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / ".data" / "events"


@router.get("/orgs", response_model=list[OrganizationOut])
def list_organizations(user: User = Depends(get_current_user)) -> list[OrganizationOut]:
    """El usuario solo ve su propia organizacion (doc 10 §4)."""

    return [OrganizationOut.model_validate(user.organization)]


def _require_org(session: Session, org_id: str, user: User):
    require_same_org(user, org_id)
    org = svc.get_organization(session, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail=f"No existe la organizacion {org_id!r}.")
    return org


@router.post("/orgs/{org_id}/events", response_model=EventsAccepted, status_code=202)
async def ingest_events(
    org_id: str,
    file: UploadFile,
    use_ai: bool = False,
    confirm_live_ai: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
    redis_client: redis.Redis = Depends(get_redis),
) -> EventsAccepted:
    org = _require_org(session, org_id, user)

    guard_error = check_live_ai_guard(use_ai, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai)
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)

    upload_dir = EVENTS_UPLOADS_DIR / str(uuid4())
    upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        name = safe_filename(file.filename, tipo="events")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    jsonl_path = upload_dir / name
    jsonl_path.write_bytes(await file.read())

    job = job_service.create_job(session, "event_ingest", org_id=org.id)
    enqueue(
        redis_client,
        QUEUE_LOGS,
        {
            "job_id": job.id,
            "org_id": org.id,
            "org_nombre": org.nombre,
            "jsonl_path": str(jsonl_path),
            "ai_requested": use_ai,
        },
    )

    return EventsAccepted(org_id=org.id, job_id=job.id)


@router.get("/orgs/{org_id}/incidents", response_model=list[IncidentOut])
def list_org_incidents(
    org_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[IncidentOut]:
    org = _require_org(session, org_id, user)
    incidents = svc.list_incidents(session, org.nombre)
    return [IncidentOut.model_validate(i) for i in incidents]
