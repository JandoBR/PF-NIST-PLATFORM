"""Reglas de los criterios agregados en CR-02/CR-03 (GV-04, ID-04, RS-02, RS-03)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.evaluation.rules import (
    gv04_strategy_review,
    id04_data_inventory,
    rs02_incident_analysis,
    rs03_notification,
)
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(
    tipo: str, contenido: dict | None = None, encontrado: bool = True, confianza: float = 0.9
):
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
            "confianza": confianza,
        },
        source_id="src",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


def _pattern(patron: str):
    return EvidenceInstance(
        type_id="log.pattern",
        type_version=1,
        subject_type="scope",
        subject_ref="s",
        scope="s",
        value={"patron": patron, "resultado": "ok", "desde": "a", "hasta": "b", "conteo": 1},
        source_id="surveillance:org",
        locator=Locator(event_id="e1"),
        observed_at=datetime.now(UTC),
        modality=Modality.OPERATIVA,
        created_by="surveillance",
    )


# --- CRI-GV-04 ---


def test_gv04_sin_claims_es_insuficiente():
    assert gv04_strategy_review.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


def test_gv04_proceso_con_metricas_es_100():
    evidence = [_claim("process_defined", {"proceso": "revision", "metricas": True})]
    assert gv04_strategy_review.evaluate(evidence).final_score == 100


def test_gv04_revision_sin_ajustes_es_75():
    evidence = [_claim("policy_review", {"frecuencia": "anual", "ultima_revision": "2026-01-01"})]
    assert gv04_strategy_review.evaluate(evidence).final_score == 75


def test_gv04_proceso_ajeno_es_0():
    evidence = [_claim("process_defined", {"proceso": "riesgos", "pasos": "x"})]
    result = gv04_strategy_review.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.NO_IMPLEMENTADO, 0)


# --- CRI-ID-04 ---


def test_id04_tipos_y_clasificacion_es_100():
    evidence = [_claim("data_inventory", {"tipos_datos": ["email"], "clasificacion": "pii"})]
    assert id04_data_inventory.evaluate(evidence).final_score == 100


def test_id04_solo_tipos_es_50():
    evidence = [_claim("data_inventory", {"tipos_datos": ["email"]})]
    assert id04_data_inventory.evaluate(evidence).final_score == 50


def test_id04_sin_datos_es_0():
    evidence = [_claim("data_inventory", {"activos": ["db"]})]
    assert id04_data_inventory.evaluate(evidence).final_score == 0


# --- CRI-RS-02 ---


def test_rs02_proceso_y_escenario_es_100():
    evidence = [
        _claim("process_defined", {"proceso": "analisis incidentes", "pasos": "x"}),
        _pattern("incident_declared"),
    ]
    assert rs02_incident_analysis.evaluate(evidence).final_score == 100


def test_rs02_documentado_sin_escenario_es_75():
    evidence = [_claim("process_defined", {"proceso": "analisis", "pasos": "x"})]
    assert rs02_incident_analysis.evaluate(evidence).final_score == 75


def test_rs02_sin_proceso_es_insuficiente():
    assert rs02_incident_analysis.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


# --- CRI-RS-03 ---


def test_rs03_con_plazos_es_100():
    evidence = [_claim("notification_list", {"destinatarios": ["externo"], "plazos": "24h"})]
    assert rs03_notification.evaluate(evidence).final_score == 100


def test_rs03_sin_plazos_es_75():
    evidence = [_claim("notification_list", {"destinatarios": ["externo"]})]
    assert rs03_notification.evaluate(evidence).final_score == 75


def test_rs03_sin_destinatarios_no_puntua_y_es_0():
    """Una afirmacion que no dice a quien se notifica no es una lista (docs/03: 100/75/0)."""

    for contenido in ({}, {"destinatarios": [], "criterios": "falla del servidor"}):
        resultado = rs03_notification.evaluate([_claim("notification_list", contenido)])
        assert resultado.estado == Estado.NO_IMPLEMENTADO and resultado.final_score == 0


def test_rs03_una_afirmacion_callada_no_tapa_a_la_que_declara_destinatarios():
    """Mas confianza no basta si la afirmacion no trae el dato (p. ej. un manual de operaciones)."""

    callada = _claim("notification_list", {"destinatarios": []}, confianza=0.95)
    util = _claim("notification_list", {"destinatarios": ["CISO"], "plazos": "72h"}, confianza=0.7)

    resultado = rs03_notification.evaluate([callada, util])

    assert resultado.final_score == 100 and resultado.evidence_ids == [util.id]