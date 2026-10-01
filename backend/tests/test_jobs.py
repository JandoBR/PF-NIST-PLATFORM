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
