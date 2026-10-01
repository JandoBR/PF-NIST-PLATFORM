"""Worker `worker-core` (docs/04 §11): consume `pf:jobs:core`, un job `assessment_run` por
mensaje. Es lo que vuelve asincronico a `POST /assessments` y `POST /assessments/{id}/reevaluate`
-- la API solo crea el `Assessment` en estado `pendiente` y encola; esto corre el pipeline real.

Arrancar con: `uv run python -m app.workers.core` (o el servicio `worker-core` del compose).
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
from app.core.queue import QUEUE_CORE, build_redis_client, dequeue_blocking
from app.methodology.loader import Methodology, load_methodology

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("worker.core")


def process_message(session: Session, methodology: Methodology, message: dict[str, Any]) -> None:
    """Un mensaje `assessment_run`: corre el pipeline y deja el `Job` en `completado`/`fallido`.

    No relanza la excepcion -- un job que revienta no debe tumbar el loop del worker, que sigue
    atendiendo el resto de la cola (docs/04 regla C4: degradar sin tumbar lecturas, aplicado
    aqui al propio worker)."""

    job = job_service.get_job(session, message["job_id"])
    if job is None:
        logger.warning("Job %s no existe (perdido o ya limpiado); se descarta.", message["job_id"])
        return

    job_service.mark_taken(session, job)
    try:
        ai_client = build_default_client() if message.get("ai_requested") else None
        svc.run_pending_assessment(
            session,
            methodology,
            message["assessment_id"],
            terraform_path=(
                Path(message["terraform_path"]) if message.get("terraform_path") else None
            ),
            ansible_path=Path(message["ansible_path"]) if message.get("ansible_path") else None,
            documents_path=(
                Path(message["documents_path"]) if message.get("documents_path") else None
            ),
            ai_client=ai_client,
            apply_ai_adjustment=message.get("apply_ai_adjustment", False),
            context=message.get("context") or {},
        )
        job_service.mark_done(session, job)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s (assessment %s) fallo", job.id, message.get("assessment_id"))
        job_service.mark_failed(session, job, str(exc))


def main() -> None:
    engine = build_engine()
    create_all(engine)
    session_factory = build_session_factory(engine)
    methodology = load_methodology(REPO_ROOT / "methodology")
    redis_client = build_redis_client()

    logger.info("worker-core escuchando %s", QUEUE_CORE)
    while True:
        message = dequeue_blocking(redis_client, QUEUE_CORE, timeout=5)
        if message is None:
            continue
        session = session_factory()
        try:
            process_message(session, methodology, message)
        finally:
            session.close()


if __name__ == "__main__":
    main()
