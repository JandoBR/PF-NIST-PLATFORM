from datetime import UTC, datetime

from app.evaluation.rules import (
    pr02_backup,
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
        source_id="test:cr05",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.OPERATIVA,
        created_by="surveillance",
    )


def _pattern(
    patron: str,
    resultado: str = "ok",
    *,
    desde: str = "2026-01-01T00:00:00Z",
    hasta: str = "2026-01-01T00:05:00Z",
) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="log.pattern",
        type_version=1,
        subject_type="scope",
        subject_ref="entorno:produccion",
        scope="entorno:produccion",
        value={
            "patron": patron,
            "resultado": resultado,
            "desde": desde,
            "hasta": hasta,
            "conteo": 1,
        },
        source_id="test:cr05",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.OPERATIVA,
        created_by="surveillance",
    )


def _backup(retencion: int) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.backup.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref="db-principal",
        scope="entorno:produccion",
        value={"retencion_dias": retencion},
        source_id="test:cr05",
        locator=Locator(file="rds.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _rds_encryption(estado: str = "enabled") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.encryption.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref="db-principal",
        scope="entorno:produccion",
        value={"estado": estado, "mecanismo": None, "llave": None},
        source_id="test:cr05",
        locator=Locator(file="rds.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _claim(tipo: str, contenido: dict) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido,
            "encontrado": True,
            "confianza": 0.9,
        },
        source_id="test:cr05",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


# -- CRI-PR-02 ----------------------------------------------------------------------


def test_pr02_retencion_cumple_politica_scores_100():
    evidence = [
        _backup(7),
        _rds_encryption("enabled"),
        _claim("backup_policy", {"respaldo": True, "retencion": "7 dias"}),
    ]
    assert pr02_backup.evaluate(evidence).final_score == 100


def test_pr02_cumple_politica_sin_cifrado_confirmado_topa_en_75():
    for estado in ("disabled", "unknown"):
        evidence = [
            _backup(7),
            _rds_encryption(estado),
            _claim("backup_policy", {"respaldo": True, "retencion": "7 dias"}),
        ]
        resultado = pr02_backup.evaluate(evidence)
        assert resultado.final_score == 75
        assert "cifrado" in resultado.explanation


def test_pr02_retencion_bajo_politica_scores_50():
    evidence = [
        _backup(7),
        _claim("backup_policy", {"respaldo": True, "retencion": "30 dias"}),
    ]
    assert pr02_backup.evaluate(evidence).final_score == 50


def test_pr02_sin_politica_tope_75():
    assert pr02_backup.evaluate([_backup(7)]).final_score == 75


# -- CRI-RS-01 ----------------------------------------------------------------------


def _plan_completo() -> EvidenceInstance:
    return _claim(
        "process_defined",
        {"proceso": "respuesta", "pasos": "1. 2.", "responsables": "CISO"},
    )


def test_rs01_plan_completo_con_escalamiento_posterior_scores_100():
    evidence = [
        _window(),
        _pattern(
            "incident_declared",
            desde="2026-01-01T00:00:00Z",
            hasta="2026-01-01T00:01:00Z",
        ),
        _pattern(
            "escalation_done",
            desde="2026-01-01T00:02:00Z",
            hasta="2026-01-01T00:03:00Z",
        ),
        _plan_completo(),
    ]
    assert rs01_response_plan.evaluate(evidence).final_score == 100


def test_rs01_escalamiento_anterior_a_la_declaracion_scores_0():
    """Un escalamiento previo no es respuesta a este incidente (docs/08 §5, D3)."""

    evidence = [
        _window(),
        _pattern(
            "incident_declared",
            desde="2026-01-01T00:02:00Z",
            hasta="2026-01-01T00:03:00Z",
        ),
        _pattern(
            "escalation_done",
            desde="2026-01-01T00:00:00Z",
            hasta="2026-01-01T00:01:00Z",
        ),
        _plan_completo(),
    ]
    assert rs01_response_plan.evaluate(evidence).final_score == 0


def test_rs01_plan_completo_con_escalamiento_sin_declaracion_tope_75():
    evidence = [_window(), _pattern("escalation_done"), _plan_completo()]
    assert rs01_response_plan.evaluate(evidence).final_score == 75


def test_rs01_plan_completo_sin_ventana_tope_75():
    assert rs01_response_plan.evaluate([_plan_completo()]).final_score == 75


def test_rs01_plan_parcial_sin_ventana_scores_50():
    evidence = [_claim("process_defined", {"proceso": "respuesta", "pasos": "1. 2."})]
    assert rs01_response_plan.evaluate(evidence).final_score == 50


# -- CRI-RC-02 ----------------------------------------------------------------------


def test_rc02_politica_y_restauracion_verificada_scores_100():
    evidence = [
        _window(),
        _pattern("restore_verified"),
        _claim("backup_policy", {"respaldo": True, "verificacion_integridad": True}),
    ]
    assert rc02_backup_verification.evaluate(evidence).final_score == 100


def test_rc02_politica_sin_ventana_tope_75():
    evidence = [_claim("backup_policy", {"respaldo": True, "verificacion_integridad": True})]
    assert rc02_backup_verification.evaluate(evidence).final_score == 75


def test_rc02_fallo_prevalece_sobre_politica_scores_0():
    evidence = [
        _window(),
        _pattern("restore_exercise_run", resultado="fail"),
        _claim("backup_policy", {"respaldo": True, "verificacion_integridad": True}),
    ]
    assert rc02_backup_verification.evaluate(evidence).final_score == 0


# -- CRI-RC-03 ----------------------------------------------------------------------


def test_rc03_lista_documentada_sin_comunicacion_observada_scores_75():
    """Saber a quien avisar no prueba que se aviso: antes esto daba 100 mientras D5 abria un
    incidente por la comunicacion faltante (docs/09 §64)."""

    evidence = [
        _window(),
        _pattern("restore_verified"),
        _claim("notification_list", {"destinatarios": ["soc", "direccion"]}),
    ]
    result = rc03_recovery_communication.evaluate(evidence)
    assert result.final_score == 75 and "lista de notificacion" in result.explanation

    comunicado = rc03_recovery_communication.evaluate(
        [*evidence, _pattern("recovery_communicated")]
    )
    assert comunicado.final_score == 100


def test_rc03_restauracion_sin_comunicacion_scores_75():
    evidence = [_window(), _pattern("restore_verified")]
    assert rc03_recovery_communication.evaluate(evidence).final_score == 75


def test_rc05_rules_all_insufficient_without_evidence():
    assert rs01_response_plan.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE
    assert rc02_backup_verification.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE
    assert rc03_recovery_communication.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE
