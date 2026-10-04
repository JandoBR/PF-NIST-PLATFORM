"""Reglas de los 7 criterios MVP agregados en CR-01 (docs/11 §C, docs/03)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.evaluation.rules import (
    de01_monitoring,
    gv02_roles,
    gv03_risk_tolerance,
    id01_asset_inventory,
    id02_asset_criticality,
    id03_risk_assessment,
    rc01_recovery_procedure,
)
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(tipo: str, contenido: dict | None = None, encontrado: bool = True, **kw):
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope="s",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido or {},
            "encontrado": encontrado,
            "confianza": kw.get("confianza", 0.9),
        },
        source_id="src",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        limitations=kw.get("limitations"),
        created_by="ai:extraction",
    )


def _tf_logging(habilitado=True, multi_region=None, destino=None):
    return EvidenceInstance(
        type_id="tf.logging.config",
        type_version=1,
        subject_type="resource",
        subject_ref="aws_cloudtrail.main",
        scope="s",
        value={"habilitado": habilitado, "multi_region": multi_region, "destino": destino},
        source_id="src",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _tf_resource(tipo):
    return EvidenceInstance(
        type_id="tf.resource.present",
        type_version=1,
        subject_type="resource",
        subject_ref=f"{tipo}.x",
        scope="s",
        value={"tipo": tipo, "nombre": "x", "entorno": None},
        source_id="src",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _syslog(estado="habilitado"):
    return EvidenceInstance(
        type_id="an.service.state",
        type_version=1,
        subject_type="host",
        subject_ref="all",
        scope="s",
        value={"servicio": "rsyslog", "estado": estado},
        source_id="src",
        locator=Locator(file="hardening.yml"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="ansible",
    )


# --- CRI-GV-02 ---


def test_gv02_sin_claims_es_insuficiente():
    assert gv02_roles.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


def test_gv02_roles_con_autoridad_es_100():
    evidence = [_claim("role_assigned", {"roles": [{"rol": "CISO", "autoridad": "aprobar"}]})]
    result = gv02_roles.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVALUADO, 100)


def test_gv02_roles_sin_autoridad_es_75():
    evidence = [_claim("role_assigned", {"roles": [{"rol": "CISO"}]})]
    assert gv02_roles.evaluate(evidence).final_score == 75


def test_gv02_no_declarado_es_insuficiente_no_0():
    """Conservador (docs/09 §60): que los documentos callen no prueba que no haya roles."""

    evidence = [_claim("role_assigned", {}, encontrado=False)]
    result = gv02_roles.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVIDENCIA_INSUFICIENTE, None)
    assert "no equivale a 0" in result.explanation


# --- CRI-GV-03 ---


def test_gv03_con_tolerancia_es_100():
    evidence = [_claim("risk_tolerance", {"objetivos_riesgo": "x", "tolerancia": "baja"})]
    assert gv03_risk_tolerance.evaluate(evidence).final_score == 100


def test_gv03_sin_tolerancia_es_75():
    evidence = [_claim("risk_tolerance", {"objetivos_riesgo": "x"})]
    assert gv03_risk_tolerance.evaluate(evidence).final_score == 75


def test_gv03_generico_es_50():
    evidence = [_claim("risk_tolerance", {})]
    assert gv03_risk_tolerance.evaluate(evidence).final_score == 50


# --- CRI-ID-03 ---


def test_id03_proceso_con_registro_es_100():
    evidence = [
        _claim("process_defined", {"proceso": "riesgos", "pasos": "x", "registro_riesgos": True})
    ]
    assert id03_risk_assessment.evaluate(evidence).final_score == 100


def test_id03_proceso_sin_registro_es_75():
    evidence = [_claim("process_defined", {"proceso": "riesgos", "pasos": "x"})]
    assert id03_risk_assessment.evaluate(evidence).final_score == 75


def test_id03_no_toma_otro_proceso_por_traer_las_claves_en_null():
    """El prompt pide `registro_riesgos`/`priorizacion` en todo `process_defined`: un proceso de
    recuperacion los trae en null y antes contaba como proceso de riesgos (ID-03 = 75)."""

    evidence = [
        _claim(
            "process_defined",
            {
                "proceso": "recuperacion",
                "pasos": "x",
                "registro_riesgos": None,
                "priorizacion": False,
            },
        )
    ]
    result = id03_risk_assessment.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVIDENCIA_INSUFICIENTE, None)


def test_id03_solo_proceso_de_recuperacion_es_insuficiente():
    evidence = [_claim("process_defined", {"proceso": "recuperacion", "pasos": "x"})]
    result = id03_risk_assessment.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVIDENCIA_INSUFICIENTE, None)


# --- CRI-ID-02 ---


def test_id02_criticidad_por_activo_es_100():
    evidence = [_claim("data_inventory", {"criticidad": [{"activo": "db", "nivel": "alta"}]})]
    assert id02_asset_criticality.evaluate(evidence).final_score == 100


def test_id02_criticidad_generica_es_50():
    evidence = [_claim("data_inventory", {"clasificacion": "alta"})]
    assert id02_asset_criticality.evaluate(evidence).final_score == 50


# --- CRI-ID-01 ---


def test_id01_cobertura_total_es_100():
    evidence = [
        _claim("data_inventory", {"activos": ["aws_db_instance", "aws_s3_bucket"]}),
        _tf_resource("aws_db_instance"),
        _tf_resource("aws_s3_bucket"),
    ]
    assert id01_asset_inventory.evaluate(evidence).final_score == 100


def test_id01_sin_tf_es_mencion_sin_cobertura():
    evidence = [_claim("data_inventory", {"activos": ["aws_db_instance"]})]
    assert id01_asset_inventory.evaluate(evidence).final_score == 25


# --- CRI-RC-01 ---


def test_rc01_procedimiento_completo_es_100():
    evidence = [
        _claim(
            "process_defined",
            {
                "proceso": "recuperacion",
                "pasos": "x",
                "criterios_activacion": "y",
                "responsables": "equipo",
            },
        )
    ]
    assert rc01_recovery_procedure.evaluate(evidence).final_score == 100


def test_rc01_solo_backup_policy_es_50():
    evidence = [_claim("backup_policy", {"respaldo": True, "verificacion_integridad": True})]
    assert rc01_recovery_procedure.evaluate(evidence).final_score == 50


def test_rc01_sin_procedimiento_ni_backup_es_insuficiente():
    assert rc01_recovery_procedure.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


# --- CRI-DE-01 ---


def test_de01_centralizado_y_sistema_es_100():
    evidence = [_tf_logging(habilitado=True, multi_region=True), _syslog()]
    assert de01_monitoring.evaluate(evidence).final_score == 100


def test_de01_habilitado_sin_centralizar_es_75():
    evidence = [_tf_logging(habilitado=True)]
    assert de01_monitoring.evaluate(evidence).final_score == 75


def test_de01_sin_configuracion_es_insuficiente():
    assert de01_monitoring.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE
