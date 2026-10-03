from datetime import UTC, datetime

import pytest

from app.evaluation.rules import (
    de02_event_analysis,
    de03_alert_notification,
    rc02_backup_verification,
    rc03_recovery_communication,
    rs01_response_plan,
)
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality

LOCATOR = Locator(event_id="e1..e2")


def _window(completo: bool = True) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="log.window",
        type_version=1,
        subject_type="scope",
        subject_ref="entorno:produccion",
        scope="entorno:produccion",
        value={
            "desde": "2026-01-01T00:00:00Z",
            "hasta": "2026-01-01T01:00:00Z",
            "completo": completo,
        },
        source_id="test:surveillance",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.OPERATIVA,
        created_by="surveillance",
    )


def _pattern(patron: str, resultado: str = "ok") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="log.pattern",
        type_version=1,
        subject_type="scope",
        subject_ref="entorno:produccion",
        scope="entorno:produccion",
        value={
            "patron": patron,
            "resultado": resultado,
            "desde": "2026-01-01T00:00:00Z",
            "hasta": "2026-01-01T00:05:00Z",
            "conteo": 1,
        },
        source_id="test:surveillance",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.OPERATIVA,
        created_by="surveillance",
    )


def _claim(tipo: str, contenido: dict | None = None, confianza: float = 0.9) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido or {},
            "encontrado": True,
            "confianza": confianza,
        },
        source_id="src",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


# -- CRI-DE-02 ----------------------------------------------------------------------


def test_de02_no_window_is_insufficient():
    result = de02_event_analysis.evaluate([])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


def test_de02_doc_criteria_and_evidence_scores_100():
    evidence = [
        _window(),
        _pattern("alert_raised"),
        _claim("process_defined", {"proceso": "incidentes", "criterios_declaracion": True}),
    ]
    assert de02_event_analysis.evaluate(evidence).final_score == 100


def test_de02_alert_present_scores_75():
    result = de02_event_analysis.evaluate([_window(), _pattern("alert_raised")])
    assert result.final_score == 75


def test_de02_burst_without_alert_scores_0():
    result = de02_event_analysis.evaluate([_window(), _pattern("auth_failures_burst")])
    assert result.final_score == 0


def test_de02_nothing_relevant_is_insufficient_not_zero():
    result = de02_event_analysis.evaluate([_window()])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


# -- CRI-DE-03 ----------------------------------------------------------------------


def test_de03_destinatarios_y_alerta_scores_100():
    evidence = [
        _claim("notification_list", {"destinatarios": ["soc"], "plazos": "1h"}),
        _pattern("alert_raised"),
    ]
    assert de03_alert_notification.evaluate(evidence).final_score == 100


def test_de03_destinatarios_sin_alerta_scores_75():
    evidence = [_claim("notification_list", {"destinatarios": ["soc"]})]
    assert de03_alert_notification.evaluate(evidence).final_score == 75


def test_de03_una_afirmacion_callada_no_tapa_a_la_que_declara_destinatarios():
    callada = _claim("notification_list", {"destinatarios": []}, confianza=0.95)
    util = _claim("notification_list", {"destinatarios": ["soc"]}, confianza=0.7)

    result = de03_alert_notification.evaluate([callada, util, _pattern("alert_raised")])

    assert result.final_score == 100 and util.id in result.evidence_ids


def test_de03_nada_es_insuficiente():
    assert de03_alert_notification.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


# -- CRI-RS-01 ----------------------------------------------------------------------


def test_rs01_escalation_present_scores_75():
    result = rs01_response_plan.evaluate([_window(), _pattern("escalation_done")])
    assert result.final_score == 75


def test_rs01_declared_without_escalation_scores_0():
    result = rs01_response_plan.evaluate([_window(), _pattern("incident_declared")])
    assert result.final_score == 0


def test_rs01_incomplete_window_is_insufficient():
    result = rs01_response_plan.evaluate([_window(completo=False), _pattern("incident_declared")])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


# -- CRI-RC-02 ----------------------------------------------------------------------


def test_rc02_failed_exercise_scores_0():
    result = rc02_backup_verification.evaluate(
        [_window(), _pattern("restore_exercise_run", resultado="fail")]
    )
    assert result.final_score == 0


def test_rc02_verified_scores_75():
    result = rc02_backup_verification.evaluate([_window(), _pattern("restore_verified")])
    assert result.final_score == 75


def test_rc02_ok_exercise_without_verification_scores_50():
    result = rc02_backup_verification.evaluate(
        [_window(), _pattern("restore_exercise_run", resultado="ok")]
    )
    assert result.final_score == 50


# -- CRI-RC-03 ----------------------------------------------------------------------


def test_rc03_verified_and_communicated_scores_100():
    result = rc03_recovery_communication.evaluate(
        [_window(), _pattern("restore_verified"), _pattern("recovery_communicated")]
    )
    assert result.final_score == 100


def test_rc03_verified_without_communication_scores_75():
    result = rc03_recovery_communication.evaluate([_window(), _pattern("restore_verified")])
    assert result.final_score == 75


def test_rc03_ok_exercise_without_verification_scores_50():
    result = rc03_recovery_communication.evaluate(
        [_window(), _pattern("restore_exercise_run", resultado="ok")]
    )
    assert result.final_score == 50


_SURVEILLANCE_RULES = [
    de02_event_analysis,
    rs01_response_plan,
    rc02_backup_verification,
    rc03_recovery_communication,
]


@pytest.mark.parametrize("rule", _SURVEILLANCE_RULES)
def test_all_surveillance_rules_require_a_window(rule):
    assert rule.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE
