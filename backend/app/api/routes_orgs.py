"""POST/GET /orgs, POST /orgs/{org_id}/events, GET /orgs/{org_id}/incidents (docs/04 §6).

`org_id` es el UUID real (doc 04 modela eventos/incidentes por organizacion, no por nombre);
`POST /orgs` es get-or-create por nombre, igual que la CLI, pero devuelve el id para direccionar
el resto de las rutas.

`POST /orgs/{org_id}/events` encola el pipeline de eventos en `worker-logs` en vez de correrlo
en el request (docs/09 §16, mismo cambio que `routes_assessments.py` para `assessment_run`):
guarda el `.jsonl` subido en un directorio persistente (no un tempfile autolimpiado -- el worker
lo lee despues de que termine este request, misma leccion que `UPLOADS_DIR` en
`routes_assessments.py`), encola un job `event_ingest` y devuelve 202 con `job_id`.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import redis
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.guard import check_live_ai_guard
from app.api.deps import get_methodology, get_redis, get_session
from app.api.schemas import EventsAccepted, IncidentOut, OrganizationOut
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core.queue import QUEUE_LOGS, enqueue
from app.methodology.loader import Methodology

router = APIRouter(tags=["orgs"])

#: Mismo patron que `UPLOADS_DIR` en `routes_assessments.py`: persistente, no un tempfile que se
#: borra al terminar el request -- `worker-logs` lo lee despues, en otro proceso.
EVENTS_UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / ".data" / "events"


class CreateOrganizationRequest(BaseModel):
    nombre: str


@router.post("/orgs", response_model=OrganizationOut)
def create_organization(
    body: CreateOrganizationRequest, session: Session = Depends(get_session)
) -> OrganizationOut:
    org = svc.get_or_create_organization(session, body.nombre)
    session.commit()
    return OrganizationOut.model_validate(org)


@router.get("/orgs", response_model=list[OrganizationOut])
def list_organizations(session: Session = Depends(get_session)) -> list[OrganizationOut]:
    return [OrganizationOut.model_validate(o) for o in svc.list_organizations(session)]


def _require_org(session: Session, org_id: str):
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
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
    redis_client: redis.Redis = Depends(get_redis),
) -> EventsAccepted:
    org = _require_org(session, org_id)

    guard_error = check_live_ai_guard(use_ai, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai)
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)

    upload_dir = EVENTS_UPLOADS_DIR / str(uuid4())
    upload_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = upload_dir / (file.filename or "events.jsonl")
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
    org_id: str, session: Session = Depends(get_session)
) -> list[IncidentOut]:
    org = _require_org(session, org_id)
    incidents = svc.list_incidents(session, org.nombre)
    return [IncidentOut.model_validate(i) for i in incidents]
