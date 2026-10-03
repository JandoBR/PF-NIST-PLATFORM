"""GET /incidents/{id}, GET /incidents/{id}/plans, PATCH /incidents/{id} (docs/04 §6, docs/11
UI-06). Exigen sesion (doc 10): un incidente de otra organizacion responde 404."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_session
from app.api.schemas import IncidentOut, IncidentUpdate
from app.core import assessment_service as svc
from app.models.tables import User
from app.ops.incidents import INCIDENT_ESTADOS, InvalidTransition
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


@router.patch("/incidents/{incident_id}", response_model=IncidentOut)
def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> IncidentOut:
    _require_incident(session, incident_id, user)
    if payload.estado not in INCIDENT_ESTADOS:
        raise HTTPException(
            status_code=422,
            detail=f"Estado {payload.estado!r} invalido. Validos: {', '.join(INCIDENT_ESTADOS)}.",
        )
    try:
        incident = svc.update_incident_estado(
            session, incident_id, payload.estado, payload.motivo
        )
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    assert incident is not None  # ya validado por _require_incident
    return IncidentOut.model_validate(incident)


@router.get("/incidents/{incident_id}/plans", response_model=list[Plan])
def get_incident_plans(
    incident_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[Plan]:
    _require_incident(session, incident_id, user)
    return svc.load_incident_plans(session, incident_id)
