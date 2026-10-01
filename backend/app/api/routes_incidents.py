"""GET /incidents/{id}, GET /incidents/{id}/plans (docs/04 §6). Exigen sesion (doc 10): un
incidente de otra organizacion responde 404."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_session
from app.api.schemas import IncidentOut
from app.core import assessment_service as svc
from app.models.tables import User
from app.recommendations.plans import Plan

router = APIRouter(tags=["incidents"])


def _require_incident(session: Session, incident_id: str, user: User):
    incident = svc.get_incident(session, incident_id)
    if incident is None or incident.org_id != user.org_id:
        raise HTTPException(status_code=404, detail=f"No existe el incidente {incident_id!r}.")
    return incident


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> IncidentOut:
    incident = _require_incident(session, incident_id, user)
    return IncidentOut.model_validate(incident)


@router.get("/incidents/{incident_id}/plans", response_model=list[Plan])
def get_incident_plans(
    incident_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[Plan]:
    _require_incident(session, incident_id, user)
    return svc.load_incident_plans(session, incident_id)
