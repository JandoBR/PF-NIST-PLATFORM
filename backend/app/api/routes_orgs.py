"""POST/GET /orgs, POST /orgs/{org_id}/events, GET /orgs/{org_id}/incidents (docs/04 §6).

`org_id` es el UUID real (doc 04 modela eventos/incidentes por organizacion, no por nombre);
`POST /orgs` es get-or-create por nombre, igual que la CLI, pero devuelve el id para direccionar
el resto de las rutas.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.client import build_default_client
from app.ai.guard import check_live_ai_guard
from app.api.deps import get_methodology, get_session
from app.api.schemas import IncidentOut, IngestEventsResponse, OrganizationOut
from app.core import assessment_service as svc
from app.methodology.loader import Methodology

router = APIRouter(tags=["orgs"])


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


@router.post("/orgs/{org_id}/events", response_model=IngestEventsResponse)
async def ingest_events(
    org_id: str,
    file: UploadFile,
    use_ai: bool = False,
    confirm_live_ai: bool = False,
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> IngestEventsResponse:
    org = _require_org(session, org_id)

    guard_error = check_live_ai_guard(use_ai, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai)
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)
    client = build_default_client() if use_ai else None

    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        result = svc.ingest_events(session, methodology, org.nombre, tmp_path, ai_client=client)
    finally:
        tmp_path.unlink(missing_ok=True)

    return IngestEventsResponse(
        org_id=result.org_id,
        eventos_ingeridos=result.eventos_ingeridos,
        nuevos_incidentes=[IncidentOut.model_validate(i) for i in result.nuevos_incidentes],
        incidentes_actualizados=[
            IncidentOut.model_validate(i) for i in result.incidentes_actualizados
        ],
    )


@router.get("/orgs/{org_id}/incidents", response_model=list[IncidentOut])
def list_org_incidents(
    org_id: str, session: Session = Depends(get_session)
) -> list[IncidentOut]:
    org = _require_org(session, org_id)
    incidents = svc.list_incidents(session, org.nombre)
    return [IncidentOut.model_validate(i) for i in incidents]
