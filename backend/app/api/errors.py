"""Errores como `application/problem+json` (RFC 9457; docs/04 §6: "type, title, detail, instance").

Todos los errores de la API salen con la misma forma, no solo los de evaluaciones (docs/11 API-04):
`HTTPException`, validacion de la peticion (422) y errores no previstos (500). `detail` es siempre
un texto, asi el cliente puede mostrarlo tal cual; la validacion agrega ademas `errors` con el
detalle por campo.
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.assessment_service import AssessmentNotFoundError
from app.surveillance.events import SurveillanceError

logger = logging.getLogger("app.api.errors")


def _title(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def _problem(
    status: int,
    title: str,
    detail: str,
    instance: str,
    *,
    headers: dict[str, str] | None = None,
    **extra: object,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
        content={
            "type": f"https://pf.local/problems/{title.lower().replace(' ', '-')}",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": instance,
            **extra,
        },
    )


def _describe_validation(errors: list[dict]) -> str:
    partes = []
    for error in errors:
        campo = ".".join(str(parte) for parte in error.get("loc", ()) if parte != "body")
        partes.append(f"{campo}: {error.get('msg', 'valor invalido')}" if campo else error["msg"])
    return "; ".join(partes) or "Peticion invalida."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AssessmentNotFoundError)
    async def _not_found(request: Request, exc: AssessmentNotFoundError) -> JSONResponse:
        return _problem(404, "Not Found", f"No existe el recurso: {exc}", str(request.url))

    @app.exception_handler(SurveillanceError)
    async def _bad_events(request: Request, exc: SurveillanceError) -> JSONResponse:
        return _problem(400, "Invalid Events File", str(exc), str(request.url))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _problem(
            exc.status_code,
            _title(exc.status_code),
            detail,
            str(request.url),
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        errores = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return _problem(
            422,
            _title(422),
            _describe_validation(errores),
            str(request.url),
            errors=errores,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # El detalle va al log, no al cliente: un traceback o un mensaje interno es informacion.
        logger.exception("Error no controlado en %s", request.url)
        return _problem(
            500, _title(500), "Error interno del servidor.", str(request.url)
        )
