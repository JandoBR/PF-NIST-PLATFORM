"""Errores como `application/problem+json` (docs/04 §6: "type, title, detail, instance")."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.assessment_service import AssessmentNotFoundError
from app.surveillance.events import SurveillanceError


def _problem(status: int, title: str, detail: str, instance: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://pf.local/problems/{title.lower().replace(' ', '-')}",
            "title": title,
            "detail": detail,
            "instance": instance,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AssessmentNotFoundError)
    async def _not_found(request: Request, exc: AssessmentNotFoundError) -> JSONResponse:
        return _problem(404, "Not Found", f"No existe el recurso: {exc}", str(request.url))

    @app.exception_handler(SurveillanceError)
    async def _bad_events(request: Request, exc: SurveillanceError) -> JSONResponse:
        return _problem(400, "Invalid Events File", str(exc), str(request.url))
