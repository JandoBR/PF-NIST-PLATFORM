"""GET /jobs/{id} (docs/04 §6): estado de un trabajo encolado por `POST /assessments`,
`POST /assessments/{id}/reevaluate` o `POST /orgs/{id}/events`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import JobOut
from app.core import jobs as job_service

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(get_session)) -> JobOut:
    job = job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No existe el job {job_id!r}.")
    return JobOut.model_validate(job)
