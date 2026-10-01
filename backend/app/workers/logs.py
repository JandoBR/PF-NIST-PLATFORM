"""Worker `worker-logs` (docs/04 §11): consume `pf:jobs:logs`, un job `event_ingest` por
mensaje -- eventos -> patrones -> disparadores -> incidentes -> planes (flujo B, docs/08 §1).
Es lo que vuelve asincronico `POST /orgs/{org_id}/events`.

Arrancar con: `uv run python -m app.workers.logs` (o el servicio `worker-logs` del compose).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.client import build_default_client
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core.db import build_engine, build_session_factory, create_all
from app.core.queue import QUEUE_LOGS, build_redis_client, dequeue_blocking
from app.methodology.loader import Methodology, load_methodology

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("worker.logs")


def process_message(session: Session, methodology: Methodology, message: dict[str, Any]) -> None:
    job = job_service.get_job(session, message["job_id"])
    if job is None:
        logger.warning("Job %s no existe (perdido o ya limpiado); se descarta.", message["job_id"])
        return

    job_service.mark_taken(session, job)
    try:
        ai_client = build_default_client() if message.get("ai_requested") else None
        svc.ingest_events(
            session,
            methodology,
            message["org_nombre"],
            Path(message["jsonl_path"]),
            ai_client=ai_client,
        )
        job_service.mark_done(session, job)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s (org %s) fallo", job.id, message.get("org_id"))
        job_service.mark_failed(session, job, str(exc))


def main() -> None:
    engine = build_engine()
    create_all(engine)
    session_factory = build_session_factory(engine)
    methodology = load_methodology(REPO_ROOT / "methodology")
    redis_client = build_redis_client()

    logger.info("worker-logs escuchando %s", QUEUE_LOGS)
    while True:
        message = dequeue_blocking(redis_client, QUEUE_LOGS, timeout=5)
        if message is None:
            continue
        session = session_factory()
        try:
            process_message(session, methodology, message)
        finally:
            session.close()


if __name__ == "__main__":
    main()
