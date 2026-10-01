"""API HTTP (docs/04 §6). Entrypoint separado de `app/main.py` (la CLI): `app/main.py` ya es
un nombre ocupado por la CLI en este proyecto, asi que la app de FastAPI vive aqui en vez de
seguir literalmente el bosquejo de carpetas de doc 04. Arrancar con:

    uv run uvicorn app.api.app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_assessments, routes_incidents, routes_methodology, routes_orgs
from app.api.errors import register_exception_handlers

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

app = FastAPI(
    title="Plataforma de Evaluacion de Madurez de Ciberseguridad",
    version="0.1.0",
)

#: Origenes permitidos para el frontend (dev server de Vite por defecto). `CORS_ORIGINS` es una
#: lista separada por comas -- pensado para cuando haya un dominio real detras de nginx (el
#: front pasa a ser same-origin casi siempre, pero esto deja la puerta abierta a un subdominio
#: separado sin tocar codigo).
_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", _default_origins).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(routes_methodology.router)
app.include_router(routes_orgs.router)
app.include_router(routes_incidents.router)
app.include_router(routes_assessments.router)
