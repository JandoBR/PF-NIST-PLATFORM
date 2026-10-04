from pathlib import Path

import pytest

from app.methodology.loader import load_methodology
from app.ops.triggers import evaluate_triggers
from app.surveillance.events import load_events_jsonl
from app.surveillance.patterns import detect_patterns

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scenarios"
METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
SCOPE = "entorno:produccion"


@pytest.fixture(scope="module")
def vigilancia_settings():
    return load_methodology(METHODOLOGY_DIR).settings.vigilancia


def _triggers(scenario, vigilancia_settings):
    events = load_events_jsonl(FIXTURES / scenario)
    matches = detect_patterns(events, vigilancia_settings)
    return evaluate_triggers(matches, vigilancia_settings, SCOPE)


# Tabla de aceptacion de docs/08 §9, exactamente.


def test_e1_flujo_correcto_crea_ningun_incidente(vigilancia_settings):
    assert _triggers("e1_flujo_correcto.jsonl", vigilancia_settings) == []


def test_e1b_dispara_d1(vigilancia_settings):
    triggers = _triggers("e1b_fallos_sin_alerta.jsonl", vigilancia_settings)
    assert [t.disparador for t in triggers] == ["D1"]
    assert triggers[0].severidad == "media"
    assert triggers[0].criterios == ["CRI-DE-02", "CRI-DE-03"]


def test_e2_flujo_correcto_crea_ningun_incidente(vigilancia_settings):
    assert _triggers("e2_flujo_correcto.jsonl", vigilancia_settings) == []


def test_e2b_dispara_d3(vigilancia_settings):
    triggers = _triggers("e2b_declarado_sin_escalar.jsonl", vigilancia_settings)
    assert [t.disparador for t in triggers] == ["D3"]
    assert triggers[0].severidad == "alta"


def test_e3_flujo_correcto_crea_ningun_incidente(vigilancia_settings):
    assert _triggers("e3_flujo_correcto.jsonl", vigilancia_settings) == []


def test_e3b_dispara_d4(vigilancia_settings):
    triggers = _triggers("e3b_restauracion_fallida.jsonl", vigilancia_settings)
    assert [t.disparador for t in triggers] == ["D4"]
    assert triggers[0].severidad == "alta"
    assert triggers[0].criterios == ["CRI-RC-02", "CRI-RC-03"]


def test_d5_fires_when_e3_is_missing_its_communication_step(vigilancia_settings):
    """docs/08 §9: E3 "si falta comunicacion, D5" — no es un fixture separado, se simula aqui."""

    events = load_events_jsonl(FIXTURES / "e3_flujo_correcto.jsonl")
    sin_comunicacion = [e for e in events if e.tipo != "recovery_communicated"]
    matches = detect_patterns(sin_comunicacion, vigilancia_settings)

    triggers = evaluate_triggers(matches, vigilancia_settings, SCOPE)

    assert [t.disparador for t in triggers] == ["D5"]
    assert triggers[0].severidad == "baja"


def test_d3_does_not_fire_when_escalation_is_within_deadline(vigilancia_settings):
    # E2 ya prueba esto end-to-end; aqui se aisla la logica del plazo en si.
    events = load_events_jsonl(FIXTURES / "e2_flujo_correcto.jsonl")
    matches = detect_patterns(events, vigilancia_settings)
    assert evaluate_triggers(matches, vigilancia_settings, SCOPE) == []


# D2: alert_raised sin incident_triaged a tiempo (docs/08 §5, docs/11 OP-05).


def test_e1c_alerta_sin_triaje_dispara_d2(vigilancia_settings):
    triggers = _triggers("e1c_alerta_sin_triaje.jsonl", vigilancia_settings)

    assert [t.disparador for t in triggers] == ["D2"]  # hay alerta, asi que no es D1
    assert triggers[0].severidad == "media"
    assert triggers[0].criterios == ["CRI-RS-01"]
    assert triggers[0].correlation_key.startswith("alert-sin-triaje:srv-app-01:")


def _d2(vigilancia_settings, *, triaje_despues_de_segundos):
    from datetime import UTC, datetime, timedelta

    from app.surveillance.patterns import PatternMatch

    alerta = datetime(2026, 9, 21, 3, 12, tzinfo=UTC)

    def patron(nombre, momento, event_id):
        return PatternMatch(nombre, "ok", momento, momento, 1, [event_id], "srv-app-01")

    matches = [patron("alert_raised", alerta, "a")]
    if triaje_despues_de_segundos is not None:
        triaje = alerta + timedelta(seconds=triaje_despues_de_segundos)
        matches.append(patron("incident_triaged", triaje, "t"))
    return evaluate_triggers(matches, vigilancia_settings, SCOPE)


def test_d2_triage_within_the_deadline_does_not_trigger(vigilancia_settings):
    plazo = vigilancia_settings.plazo_triaje_minutos * 60
    assert _d2(vigilancia_settings, triaje_despues_de_segundos=60) == []
    assert _d2(vigilancia_settings, triaje_despues_de_segundos=plazo) == []  # justo en el plazo


def test_d2_late_or_missing_triage_triggers(vigilancia_settings):
    plazo = vigilancia_settings.plazo_triaje_minutos * 60

    tarde = _d2(vigilancia_settings, triaje_despues_de_segundos=plazo + 1)
    sin_triaje = _d2(vigilancia_settings, triaje_despues_de_segundos=None)

    assert [t.disparador for t in tarde] == ["D2"]
    assert [t.disparador for t in sin_triaje] == ["D2"]
    assert set(tarde[0].event_ids) == {"a", "t"}  # cita ambos hechos
    assert sin_triaje[0].event_ids == ["a"]


def test_d2_a_triage_before_the_alert_does_not_count(vigilancia_settings):
    """Un `incident_triaged` anterior a la alerta no es el triaje de esa alerta."""

    triggers = _d2(vigilancia_settings, triaje_despues_de_segundos=-60)
    assert [t.disparador for t in triggers] == ["D2"]


def test_d2_needs_an_alert(vigilancia_settings):
    assert evaluate_triggers([], vigilancia_settings, SCOPE) == []


def test_d3_an_escalation_before_the_declaration_does_not_count(vigilancia_settings):
    """Como en D2: un `escalation_done` anterior al `incident_declared` no es su escalamiento.
    Antes un delta negativo contaba como "a tiempo" y D3 no se disparaba."""

    from datetime import UTC, datetime, timedelta

    from app.surveillance.patterns import PatternMatch

    declarado = datetime(2026, 9, 21, 3, 14, tzinfo=UTC)
    antes = declarado - timedelta(minutes=5)
    matches = [
        PatternMatch("incident_declared", "ok", declarado, declarado, 1, ["d"], "srv-app-01"),
        PatternMatch("escalation_done", "ok", antes, antes, 1, ["e"], "srv-app-01"),
    ]
    triggers = evaluate_triggers(matches, vigilancia_settings, SCOPE)
    assert [t.disparador for t in triggers] == ["D3"]
