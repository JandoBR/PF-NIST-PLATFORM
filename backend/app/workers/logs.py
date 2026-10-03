"""Worker `worker-logs` (docs/04 §11): consume `pf:jobs:logs`, un job `event_ingest` por
mensaje -- eventos -> patrones -> disparadores -> incidentes -> planes (flujo B, docs/08 §1).
Es lo que vuelve asincronico `POST /orgs/{org_id}/events`.

Arrancar con: `uv run python -m app.workers.logs` (o el servicio `worker-logs` del compose).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.ai.client import build_default_client, describe_client
from app.core import jobs as job_service
from app.core import operations, refresh
from app.core.db import build_engine, build_session_factory, ensure_schema
from app.core.queue import QUEUE_LOGS, build_redis_client, dequeue_blocking, message_version_error
from app.methodology.loader import Methodology, load_methodology

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Ver el mismo comentario en app/workers/core.py: sin esto, un worker corrido como proceso
#: local nunca ve la DEEPSEEK_API_KEY real de backend/.env y degrada en silencio a NullAIClient.
load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("worker.logs")

JOB_STALE_TIMEOUT_SECONDS = int(os.environ.get("JOB_STALE_TIMEOUT_SECONDS", "600"))


def _maybe_refresh_maturity(
    session: Session, methodology: Methodology, redis_client, result
) -> None:
    """Refresco automatico de madurez tras una ingesta (docs/06 §6, docs/08 §8). Best-effort: si
    falla, la ingesta ya fue exitosa y no se debe marcar su job como fallido por esto."""

    for scope, nuevos in result.patrones_nuevos_por_scope.items():
        try:
            refreshed = refresh.maybe_enqueue_maturity_refresh(
                session,
                methodology,
                redis_client,
                org_id=result.org_id,
                scope=scope,
                nuevos_patrones=nuevos,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Refresco de madurez fallo (org %s, scope %s)", result.org_id, scope)
            continue
        if refreshed is not None:
            logger.info(
                "Refresco de madurez encolado (org %s, scope %s, assessment %s)",
                result.org_id,
                scope,
                refreshed.id,
            )


def process_message(
    session: Session,
    methodology: Methodology,
    message: dict[str, Any],
    redis_client=None,
) -> None:
    job = job_service.get_job(session, message["job_id"])
    if job is None:
        logger.warning("Job %s no existe (perdido o ya limpiado); se descarta.", message["job_id"])
        return

    version_error = message_version_error(message)
    if version_error is not None:
        logger.error("Job %s: %s", job.id, version_error)
        job_service.mark_failed(session, job, version_error)
        return

    job_service.mark_taken(session, job)
    try:
        ai_requested = bool(message.get("ai_requested"))
        ai_client = build_default_client() if ai_requested else None
        if ai_requested:
            logger.info("Job %s: IA %s", job.id, describe_client(ai_client))
        result = operations.ingest_events(
            session,
            methodology,
            message["org_nombre"],
            Path(message["jsonl_path"]),
            ai_client=ai_client,
        )
        # Antes de marcar el job como completado: que la evaluacion refrescada ya exista cuando el
        # cliente que sondea vea "completado" (asi aparece en el historial enseguida).
        _maybe_refresh_maturity(session, methodology, redis_client, result)
        job_service.mark_done(session, job, result.summary())
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s (org %s) fallo", job.id, message.get("org_id"))
        job_service.mark_failed(session, job, str(exc))


def main() -> None:
    engine = build_engine()
    ensure_schema(engine)
    session_factory = build_session_factory(engine)
    methodology = load_methodology(REPO_ROOT / "methodology")
    redis_client = build_redis_client()

    logger.info("worker-logs escuchando %s", QUEUE_LOGS)
    while True:
        message = dequeue_blocking(redis_client, QUEUE_LOGS, timeout=5)
        session = session_factory()
        try:
            if message is not None:
                process_message(session, methodology, message, redis_client)
            job_service.reap_stale_jobs(session, "event_ingest", JOB_STALE_TIMEOUT_SECONDS)
        finally:
            session.close()


if __name__ == "__main__":
    main()
