from datetime import UTC, datetime, timedelta

from app.core import jobs as job_service
from app.core.queue import QUEUE_CORE, heartbeat_key, job_heartbeat_key
from tests.conftest import FakeRedis


def _live_worker(queue: str = QUEUE_CORE) -> FakeRedis:
    """FakeRedis con un worker latiendo en esa cola (lo unico que mira el reaper)."""

    redis = FakeRedis()
    redis.set(heartbeat_key(queue, "worker-test"), "ahora")
    return redis


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

    reaped = job_service.reap_stale_jobs(
        db_session, "assessment_run", timeout_seconds=600, redis_client=FakeRedis()
    )

    assert [j.id for j in reaped] == [job.id]
    assert job.estado == "fallido"
    assert job.error


def test_reap_stale_jobs_leaves_recent_en_progreso_alone(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="a4")
    job_service.mark_taken(db_session, job)

    reaped = job_service.reap_stale_jobs(
        db_session, "assessment_run", timeout_seconds=600, redis_client=FakeRedis()
    )

    assert reaped == []
    assert job.estado == "en_progreso"


def test_reap_stale_jobs_leaves_a_long_en_progreso_job_whose_worker_is_alive(db_session):
    """Un pipeline de IA puede durar mas que `JOB_STALE_TIMEOUT_SECONDS`; mientras el worker
    refresque el heartbeat del job, el reaper no lo toca (el `tomado_en` viejo no alcanza)."""

    job = job_service.create_job(db_session, "assessment_run", assessment_id="a6")
    job_service.mark_taken(db_session, job)
    job.tomado_en = datetime.now(UTC) - timedelta(seconds=700)
    db_session.commit()
    redis = _live_worker()
    redis.set(job_heartbeat_key(job.id), "ahora")

    reaped = job_service.reap_stale_jobs(
        db_session, "assessment_run", timeout_seconds=600, redis_client=redis
    )

    assert reaped == []
    assert job.estado == "en_progreso"


def test_reap_stale_jobs_marks_old_pendiente_as_fallido(db_session):
    """Sin ningun worker con heartbeat vivo en la cola, un pendiente viejo no se procesaria nunca:
    se falla pasado el timeout de pendientes (docs/09 §20)."""

    job = job_service.create_job(db_session, "assessment_run", assessment_id="p1")
    job.creado_en = datetime.now(UTC) - timedelta(seconds=300)
    db_session.commit()

    reaped = job_service.reap_stale_jobs(
        db_session,
        "assessment_run",
        timeout_seconds=600,
        pending_timeout_seconds=120,
        redis_client=FakeRedis(),
    )

    assert [j.id for j in reaped] == [job.id]
    assert job.estado == "fallido"
    assert "no fue tomado" in job.error


def test_reap_stale_jobs_leaves_an_old_pendiente_queued_behind_a_long_job_alone(db_session):
    """Estar en la cola no es un fallo: con el worker de la cola latiendo, un pendiente viejo
    espera a que lo tome (bug real: ingesta 2 detras de una reevaluacion larga con IA)."""

    job = job_service.create_job(db_session, "assessment_run", assessment_id="p5")
    job.creado_en = datetime.now(UTC) - timedelta(seconds=300)
    db_session.commit()

    reaped = job_service.reap_stale_jobs(
        db_session,
        "assessment_run",
        timeout_seconds=600,
        pending_timeout_seconds=120,
        redis_client=_live_worker(),
    )

    assert reaped == []
    assert job.estado == "pendiente"


def test_reap_stale_jobs_leaves_recent_pendiente_alone(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="p2")

    reaped = job_service.reap_stale_jobs(
        db_session,
        "assessment_run",
        timeout_seconds=600,
        pending_timeout_seconds=120,
        redis_client=_live_worker(),
    )

    assert reaped == []
    assert job.estado == "pendiente"


def test_fail_if_stale_marks_a_single_stale_pending_job(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="p3")
    job.creado_en = datetime.now(UTC) - timedelta(seconds=300)
    db_session.commit()

    changed = job_service.fail_if_stale(
        db_session, job, pending_timeout_seconds=120, redis_client=FakeRedis()
    )

    assert changed is True
    assert job.estado == "fallido"


def test_fail_if_stale_leaves_terminal_states_alone(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="p4")
    job_service.mark_taken(db_session, job)
    job_service.mark_done(db_session, job)

    assert job_service.fail_if_stale(db_session, job, pending_timeout_seconds=0) is False
    assert job.estado == "completado"


def test_reap_stale_jobs_ignores_other_tipos_and_terminal_states(db_session):
    other_tipo = job_service.create_job(db_session, "event_ingest", org_id="o2")
    job_service.mark_taken(db_session, other_tipo)
    other_tipo.tomado_en = datetime.now(UTC) - timedelta(seconds=700)

    already_done = job_service.create_job(db_session, "assessment_run", assessment_id="a5")
    job_service.mark_taken(db_session, already_done)
    already_done.tomado_en = datetime.now(UTC) - timedelta(seconds=700)
    job_service.mark_done(db_session, already_done)
    db_session.commit()

    reaped = job_service.reap_stale_jobs(
        db_session, "assessment_run", timeout_seconds=600, redis_client=FakeRedis()
    )

    assert reaped == []
    assert other_tipo.estado == "en_progreso"  # otro tipo: no lo tocamos desde aca
    assert already_done.estado == "completado"  # ya terminado: no se reabre


def test_adopt_lost_in_queue_puts_the_job_back_in_pendiente(db_session):
    """El reaper lo fallo justo antes de que el worker sacara el mensaje: se ejecuta igual."""

    job = job_service.create_job(db_session, "assessment_run", assessment_id="a7")
    job_service.mark_failed(db_session, job, job_service.LOST_IN_QUEUE_ERROR)

    assert job_service.adopt_lost_in_queue(db_session, job) is True
    assert job.estado == "pendiente"
    assert job.error is None
    assert job.tomado_en is None


def test_adopt_lost_in_queue_skips_a_job_that_was_already_retried(db_session):
    """Un reintento crea un job nuevo; el mensaje viejo no debe volver a correr la evaluacion."""

    job = job_service.create_job(db_session, "assessment_run", assessment_id="a8")
    job_service.mark_failed(db_session, job, job_service.LOST_IN_QUEUE_ERROR)
    job_service.create_job(db_session, "assessment_run", assessment_id="a8")

    assert job_service.adopt_lost_in_queue(db_session, job) is False
    assert job.estado == "fallido"


def test_adopt_lost_in_queue_skips_a_retry_that_already_completed(db_session):
    """Si el reintento ya termino, re-ejecutar el mensaje viejo duplicaria el trabajo."""

    job = job_service.create_job(db_session, "assessment_run", assessment_id="a12")
    job_service.mark_failed(db_session, job, job_service.LOST_IN_QUEUE_ERROR)
    retry = job_service.create_job(db_session, "assessment_run", assessment_id="a12")
    job_service.mark_taken(db_session, retry)
    job_service.mark_done(db_session, retry)

    assert job_service.adopt_lost_in_queue(db_session, job) is False
    assert job.estado == "fallido"


def test_adopt_lost_in_queue_skips_real_failures_and_finished_jobs(db_session):
    failed = job_service.create_job(db_session, "assessment_run", assessment_id="a9")
    job_service.mark_taken(db_session, failed)
    job_service.mark_failed(db_session, failed, "boom")

    done = job_service.create_job(db_session, "assessment_run", assessment_id="a10")
    job_service.mark_taken(db_session, done)
    job_service.mark_done(db_session, done)

    assert job_service.adopt_lost_in_queue(db_session, failed) is False
    assert job_service.adopt_lost_in_queue(db_session, done) is False


def test_adopt_lost_in_queue_leaves_a_pendiente_job_alone(db_session):
    job = job_service.create_job(db_session, "assessment_run", assessment_id="a11")

    assert job_service.adopt_lost_in_queue(db_session, job) is True
    assert job.estado == "pendiente"
