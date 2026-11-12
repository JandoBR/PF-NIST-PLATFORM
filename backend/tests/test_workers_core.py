"""`app.workers.core.process_message` es la logica real que corre `worker-core` -- probada
directamente (sesion + mensaje), sin Redis ni loop, para que sea rapida y no dependa de un
proceso en segundo plano. El round-trip completo incluyendo Redis esta en test_queue.py y en
los tests de la API (conftest.py: `FakeRedis` + drenar la cola)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.evaluation.schemas import Estado
from app.workers import core as worker_core

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"


def test_process_message_runs_the_pipeline_and_completes_the_job(db_session, methodology):
    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker", scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)

    worker_core.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": str(FIXTURES / "good"),
            "ansible_path": None,
            "documents_path": None,
            "ai_requested": False,
            "apply_ai_adjustment": False,
            "context": {},
        },
    )

    db_session.refresh(assessment)
    db_session.refresh(job)
    assert assessment.estado == "completada"
    assert job.estado == "completado"
    assert job.tomado_en is not None

    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}
    assert results["CRI-PR-01"].estado == Estado.EVALUADO
    assert results["CRI-PR-01"].final_score == 100


def test_process_message_marks_job_and_assessment_failed_on_bad_path(db_session, methodology):
    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker Falla", scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)

    worker_core.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": "/no/existe/esta/ruta",
            "ansible_path": None,
            "documents_path": None,
            "ai_requested": False,
            "apply_ai_adjustment": False,
            "context": {},
        },
    )

    db_session.refresh(assessment)
    db_session.refresh(job)
    assert assessment.estado == "fallida"
    assert job.estado == "fallido"
    assert job.error


def test_process_message_does_not_die_when_marking_the_job_failed(
    db_session, methodology, monkeypatch
):
    """Un fallo de BD al marcar el job fallido tampoco puede tumbar el loop del worker: el job
    queda para el reaper en vez de matar el proceso (docs/09 §114)."""

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker Marca Rota", scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)

    def rompe(*args, **kwargs):
        raise RuntimeError("BD caida al marcar")

    monkeypatch.setattr(job_service, "mark_failed", rompe)

    worker_core.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": "/no/existe/esta/ruta",
            "ai_requested": False,
        },
    )


def test_process_message_runs_a_job_reaped_as_lost_in_queue(db_session, methodology):
    """El reaper lo fallo justo antes de que el worker sacara el mensaje: se ejecuta igual (y la
    evaluacion ligada vuelve de `fallida` a completarse), en vez de perder el trabajo."""

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker Rescate", scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job_service.mark_failed(db_session, job, job_service.LOST_IN_QUEUE_ERROR)
    job_service.fail_linked_assessment(db_session, job)

    worker_core.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": str(FIXTURES / "good"),
            "ansible_path": None,
            "documents_path": None,
            "ai_requested": False,
            "apply_ai_adjustment": False,
            "context": {},
        },
    )

    db_session.refresh(assessment)
    db_session.refresh(job)
    assert job.estado == "completado"
    assert assessment.estado == "completada"


def test_process_message_discards_a_lost_job_that_was_already_retried(db_session, methodology):
    """Un reintento crea un job nuevo (`dispatch.retry_job`): el mensaje viejo no debe correr la
    evaluacion una segunda vez."""

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker Reintento", scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job_service.mark_failed(db_session, job, job_service.LOST_IN_QUEUE_ERROR)
    job_service.fail_linked_assessment(db_session, job)
    # Asi deja el estado `dispatch.retry_job`: la evaluacion vuelve a `pendiente` y el job nuevo
    # espera en la cola.
    assessment.estado = "pendiente"
    assessment.error = None
    db_session.commit()
    job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)

    worker_core.process_message(
        db_session,
        methodology,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": str(FIXTURES / "good"),
            "ai_requested": False,
        },
    )

    db_session.refresh(assessment)
    db_session.refresh(job)
    assert job.estado == "fallido"
    assert assessment.estado == "pendiente"
    assert svc.load_criterion_results(db_session, assessment.id) == []


def test_process_message_discards_unknown_job_id(db_session, methodology):
    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker Sin Job", scope="entorno:produccion"
    )

    # No debe lanzar ni crear nada si el job ya no existe (p.ej. se limpio la tabla).
    worker_core.process_message(
        db_session,
        methodology,
        {
            "job_id": "no-existe",
            "assessment_id": assessment.id,
            "terraform_path": str(FIXTURES / "good"),
            "ansible_path": None,
            "documents_path": None,
            "ai_requested": False,
            "apply_ai_adjustment": False,
            "context": {},
        },
    )

    db_session.refresh(assessment)
    assert assessment.estado == "pendiente"


def test_reap_stale_jobs_also_fails_the_linked_assessment(db_session, methodology):
    """Si el worker que tomo el job murio antes de llegar a `mark_done`/`mark_failed`, el job
    se queda `en_progreso` para siempre sin esto -- y la `Assessment` ligada tambien, porque
    nadie mas la toca."""

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker Reaper", scope="entorno:produccion"
    )
    assessment.estado = "en_progreso"
    db_session.commit()
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job_service.mark_taken(db_session, job)
    job.tomado_en = datetime.now(UTC) - timedelta(seconds=700)
    db_session.commit()

    worker_core.reap_stale_jobs(db_session, timeout_seconds=600)

    db_session.refresh(job)
    db_session.refresh(assessment)
    assert job.estado == "fallido"
    assert assessment.estado == "fallida"
    assert assessment.error == job.error


def test_reap_stale_jobs_leaves_a_completed_assessment_alone(db_session, methodology):
    """Si el job ya habia terminado bien antes de quedar viejo, reap_stale_jobs no deberia
    tocarlo (no esta `en_progreso`) ni tocar la Assessment ya completada."""

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Worker Reaper OK", scope="entorno:produccion"
    )
    assessment.estado = "completada"
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job_service.mark_taken(db_session, job)
    job_service.mark_done(db_session, job)
    db_session.commit()

    worker_core.reap_stale_jobs(db_session, timeout_seconds=0)

    db_session.refresh(assessment)
    assert assessment.estado == "completada"


def test_worker_fails_a_job_whose_message_version_it_does_not_understand(db_session, methodology):
    """OP-13: api y workers pueden desplegarse por separado; no se interpreta a medias."""

    assessment = svc.create_pending_assessment(
        db_session, methodology, org_name="Empresa Version", scope="entorno:produccion"
    )
    job = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)

    worker_core.process_message(
        db_session,
        methodology,
        {
            "schema_version": 99,
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": str(FIXTURES / "good"),
        },
    )

    db_session.refresh(assessment)
    db_session.refresh(job)
    assert job.estado == "fallido" and "schema_version=99" in job.error
    assert job.tomado_en is None  # no se llego a tomar ni a ejecutar
    assert assessment.estado == "fallida" and assessment.error == job.error
    assert svc.load_criterion_results(db_session, assessment.id) == []


def test_dispatched_messages_carry_the_current_schema_version(db_session, fake_redis):

    from app.core.dispatch import dispatch_job
    from app.core.queue import MESSAGE_SCHEMA_VERSION, QUEUE_LOGS

    job = dispatch_job(
        db_session, fake_redis, "event_ingest", {"org_nombre": "x", "jsonl_path": "x"}, org_id=None
    )

    (message,) = fake_redis.drain(QUEUE_LOGS)
    assert message["schema_version"] == MESSAGE_SCHEMA_VERSION and message["job_id"] == job.id
    assert "schema_version" not in job.payload  # el payload guardado no la lleva (reintento)
