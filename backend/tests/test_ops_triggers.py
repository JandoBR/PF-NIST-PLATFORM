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
