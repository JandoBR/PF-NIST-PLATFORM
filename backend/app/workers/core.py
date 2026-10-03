"""Worker `worker-core` (docs/04 §11): consume `pf:jobs:core`, un job `assessment_run` por
mensaje. Es lo que vuelve asincronico a `POST /assessments` y `POST /assessments/{id}/reevaluate`
-- la API solo crea el `Assessment` en estado `pendiente` y encola; esto corre el pipeline real.

Arrancar con: `uv run python -m app.workers.core` (o el servicio `worker-core` del compose).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.ai.client import build_default_client, describe_client
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core.db import build_engine, build_session_factory, ensure_schema
from app.core.queue import QUEUE_CORE, build_redis_client, dequeue_blocking, message_version_error
from app.methodology.loader import Methodology, load_methodology

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Sin esto, un worker corrido como proceso local (`uv run python -m app.workers.core`, fuera
#: de docker-compose) nunca ve la DEEPSEEK_API_KEY real de `backend/.env` -- `build_default_client`
#: solo mira `os.environ`, y nada mas en este modulo cargaba el `.env` (bug real: el job se
#: encolaba con `ai_requested=True`, pero el worker construia un `NullAIClient` en silencio,
#: cero llamadas de red, cero costo... y cero resultado real tambien). `app/api/app.py` y
#: `app/main.py` ya hacian esto; faltaba aqui. docker-compose no lo necesita (inyecta las env
#: vars directo al contenedor), pero `load_dotenv` no pisa una env var ya seteada, asi que es
#: inocuo ahi.
load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("worker.core")

#: Si un job se queda `en_progreso` mas de esto (el worker que lo tomo probablemente crasheo
#: antes de llamar a `mark_done`/`mark_failed` -- sin heartbeat real), se marca `fallido` para
#: que no quede colgado para siempre. Configurable por si un pipeline legitimo tarda mas.
JOB_STALE_TIMEOUT_SECONDS = int(os.environ.get("JOB_STALE_TIMEOUT_SECONDS", "600"))
#: Un job `pendiente` (nunca tomado) se falla antes: si este worker estuviera sano lo habria
#: tomado en segundos (docs/09 §20).
JOB_PENDING_TIMEOUT_SECONDS = int(os.environ.get("JOB_PENDING_TIMEOUT_SECONDS", "120"))


def process_message(session: Session, methodology: Methodology, message: dict[str, Any]) -> None:
    """Un mensaje `assessment_run`: corre el pipeline y deja el `Job` en `completado`/`fallido`.

    No relanza la excepcion -- un job que revienta no debe tumbar el loop del worker, que sigue
    atendiendo el resto de la cola (docs/04 regla C4: degradar sin tumbar lecturas, aplicado
    aqui al propio worker)."""

    job = job_service.get_job(session, message["job_id"])
    if job is None:
        logger.warning("Job %s no existe (perdido o ya limpiado); se descarta.", message["job_id"])
        return

    version_error = message_version_error(message)
    if version_error is not None:
        logger.error("Job %s: %s", job.id, version_error)
        job_service.mark_failed(session, job, version_error)
        assessment = svc.get_assessment(session, message.get("assessment_id", ""))
        if assessment is not None and assessment.estado in ("pendiente", "en_progreso"):
            assessment.estado = "fallida"
            assessment.error = version_error
            session.commit()
        return

    job_service.mark_taken(session, job)
    try:
        ai_requested = bool(message.get("ai_requested"))
        ai_client = build_default_client() if ai_requested else None
        if ai_requested:
            logger.info("Job %s: IA %s", job.id, describe_client(ai_client))
        if message.get("selective_refresh"):
            # Refresco selectivo (docs/06 §6, FN-06): reusa lo previo, recalcula solo lo operativo.
            svc.run_surveillance_refresh(
                session,
                methodology,
                message["assessment_id"],
                message["previous_assessment_id"],
            )
        else:
            svc.run_pending_assessment(
                session,
                methodology,
                message["assessment_id"],
                terraform_path=(
                    Path(message["terraform_path"]) if message.get("terraform_path") else None
                ),
                ansible_path=(
                    Path(message["ansible_path"]) if message.get("ansible_path") else None
                ),
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


def reap_stale_jobs(session: Session, timeout_seconds: int = JOB_STALE_TIMEOUT_SECONDS) -> None:
    """Ademas de marcar el `Job` fallido (`job_service.reap_stale_jobs`), si tenia un
    `Assessment` ligado que se quedo en `pendiente` o `en_progreso`, lo marca `fallida` tambien --
    sin esto, el job se veria fallido pero `GET /assessments/{id}` seguiria mostrando un estado no
    terminal para siempre (el worker que murio nunca llego a la rama `except` que lo marca)."""

    for job in job_service.reap_stale_jobs(
        session, "assessment_run", timeout_seconds, JOB_PENDING_TIMEOUT_SECONDS
    ):
        if not job.assessment_id:
            continue
        assessment = svc.get_assessment(session, job.assessment_id)
        if assessment is not None and assessment.estado in ("pendiente", "en_progreso"):
            assessment.estado = "fallida"
            assessment.error = job.error
            session.commit()


def main() -> None:
    engine = build_engine()
    ensure_schema(engine)
    session_factory = build_session_factory(engine)
    methodology = load_methodology(REPO_ROOT / "methodology")
    redis_client = build_redis_client()

    logger.info("worker-core escuchando %s", QUEUE_CORE)
    while True:
        message = dequeue_blocking(redis_client, QUEUE_CORE, timeout=5)
        session = session_factory()
        try:
            if message is not None:
                process_message(session, methodology, message)
            reap_stale_jobs(session)
        finally:
            session.close()


if __name__ == "__main__":
    main()
