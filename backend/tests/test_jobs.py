from datetime import UTC, datetime, timedelta

from app.core import jobs as job_service


def test_create_job_starts_pendiente(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="a1")

    assert job.estado == "pendiente"
    assert job.progreso == 0
    assert job.tomado_en is None
    assert job_service.get_job(db_session, job.id).id == job.id


def test_mark_taken_then_done(db_session):
    job = job_service.create_job(db_session, "event_ingest", org_id="o1")

    job_service.mark_taken(db_session, job)
    assert job.estado == "en_progreso"
    assert job.tomado_en is not None

    job_service.mark_done(db_session, job)
    assert job.estado == "completado"
    assert job.progreso == 100


def test_mark_failed_records_error(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="a2")

    job_service.mark_taken(db_session, job)
    job_service.mark_failed(db_session, job, "boom")

    assert job.estado == "fallido"
    assert job.error == "boom"


def test_get_unknown_job_is_none(db_session):
    assert job_service.get_job(db_session, "no-existe") is None


def test_reap_stale_jobs_marks_old_en_progreso_as_fallido(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="a3")
    job_service.mark_taken(db_session, job)
    job.tomado_en = datetime.now(UTC) - timedelta(seconds=700)
    db_session.commit()

    reaped = job_service.reap_stale_jobs(db_session, "assessment_run", timeout_seconds=600)

    assert [j.id for j in reaped] == [job.id]
    assert job.estado == "fallido"
    assert job.error


def test_reap_stale_jobs_leaves_recent_en_progreso_alone(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="a4")
    job_service.mark_taken(db_session, job)

    reaped = job_service.reap_stale_jobs(db_session, "assessment_run", timeout_seconds=600)

    assert reaped == []
    assert job.estado == "en_progreso"


def test_reap_stale_jobs_ignores_other_tipos_and_terminal_states(db_session):
    other_tipo = job_service.create_job(db_session, "event_ingest", org_id="o2")
    job_service.mark_taken(db_session, other_tipo)
    other_tipo.tomado_en = datetime.now(UTC) - timedelta(seconds=700)

    already_done = job_service.create_job(db_session, "assessment_run", assessment_id="a5")
    job_service.mark_taken(db_session, already_done)
    already_done.tomado_en = datetime.now(UTC) - timedelta(seconds=700)
    job_service.mark_done(db_session, already_done)
    db_session.commit()

    reaped = job_service.reap_stale_jobs(db_session, "assessment_run", timeout_seconds=600)

    assert reaped == []
    assert other_tipo.estado == "en_progreso"  # otro tipo: no lo tocamos desde aca
    assert already_done.estado == "completado"  # ya terminado: no se reabre
