from datetime import UTC, datetime

from app.evaluation.rules import pr06_logging
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality

LOCATOR = Locator(file="main.tf")


def _cloudtrail(habilitado: bool, multi_region: bool | None) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.logging.config",
        type_version=1,
        subject_type="aws_cloudtrail",
        subject_ref="aws_cloudtrail.main",
        scope="entorno:produccion",
        value={"habilitado": habilitado, "multi_region": multi_region, "destino": None},
        source_id="test:tf",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:terraform",
    )


def _rsyslog_service(estado: str = "habilitado") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="an.service.state",
        type_version=1,
        subject_type="service",
        subject_ref="rsyslog",
        scope="entorno:produccion",
        value={"servicio": "rsyslog", "estado": estado},
        source_id="test:ansible",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:ansible",
    )


def test_no_evidence_at_all_is_insufficient():
    result = pr06_logging.evaluate([])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


def test_system_logs_alone_without_cloudtrail_scores_75():
    result = pr06_logging.evaluate([_rsyslog_service()])
    assert result.final_score == 75


def test_multiregion_and_system_logs_scores_100():
    result = pr06_logging.evaluate([_cloudtrail(True, True), _rsyslog_service()])
    assert result.final_score == 100


def test_multiregion_alone_without_system_logs_scores_75():
    result = pr06_logging.evaluate([_cloudtrail(True, True)])
    assert result.final_score == 75


def test_single_region_with_system_logs_scores_75():
    result = pr06_logging.evaluate([_cloudtrail(True, False), _rsyslog_service()])
    assert result.final_score == 75


def test_cloudtrail_disabled_with_system_logs_scores_50():
    result = pr06_logging.evaluate([_cloudtrail(False, None), _rsyslog_service()])
    assert result.final_score == 50


def test_cloudtrail_disabled_without_system_logs_scores_0():
    result = pr06_logging.evaluate([_cloudtrail(False, None)])
    assert result.final_score == 0


def test_disabled_syslog_service_does_not_count_as_declared():
    result = pr06_logging.evaluate([_rsyslog_service(estado="deshabilitado")])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
