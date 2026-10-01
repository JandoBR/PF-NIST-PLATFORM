"""`app.workers.core.process_message` es la logica real que corre `worker-core` -- probada
directamente (sesion + mensaje), sin Redis ni loop, para que sea rapida y no dependa de un
proceso en segundo plano. El round-trip completo incluyendo Redis esta en test_queue.py y en
los tests de la API (conftest.py: `FakeRedis` + drenar la cola)."""

from __future__ import annotations

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
