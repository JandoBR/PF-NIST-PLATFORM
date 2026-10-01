"""API HTTP (docs/04 §6). Entrypoint separado de `app/main.py` (la CLI): `app/main.py` ya es
un nombre ocupado por la CLI en este proyecto, asi que la app de FastAPI vive aqui en vez de
seguir literalmente el bosquejo de carpetas de doc 04. Arrancar con:

    uv run uvicorn app.api.app:app --reload
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app.api import routes_assessments, routes_incidents, routes_methodology, routes_orgs
from app.api.errors import register_exception_handlers

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

app = FastAPI(
    title="Plataforma de Evaluacion de Madurez de Ciberseguridad",
    version="0.1.0",
)

register_exception_handlers(app)

app.include_router(routes_methodology.router)
app.include_router(routes_orgs.router)
app.include_router(routes_incidents.router)
app.include_router(routes_assessments.router)
