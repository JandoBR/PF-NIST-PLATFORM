from pathlib import Path

import pytest

from app.methodology.loader import load_methodology
from app.surveillance.events import load_events_jsonl
from app.surveillance.patterns import detect_patterns

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scenarios"
METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture(scope="module")
def vigilancia_settings():
    return load_methodology(METHODOLOGY_DIR).settings.vigilancia


def _patterns(scenario, vigilancia_settings):
    events = load_events_jsonl(FIXTURES / scenario)
    matches = detect_patterns(events, vigilancia_settings)
    return {m.patron: m for m in matches}


def test_e1_detects_burst_and_alert_and_no_escalation_pattern(vigilancia_settings):
    patterns = _patterns("e1_flujo_correcto.jsonl", vigilancia_settings)
    assert "auth_failures_burst" in patterns
    assert "alert_raised" in patterns
    assert "incident_declared" not in patterns


def test_e1b_detects_burst_without_alert(vigilancia_settings):
    patterns = _patterns("e1b_fallos_sin_alerta.jsonl", vigilancia_settings)
    assert "auth_failures_burst" in patterns
    assert "alert_raised" not in patterns
    assert patterns["auth_failures_burst"].conteo == 6


def test_e2_detects_declared_and_escalated(vigilancia_settings):
    patterns = _patterns("e2_flujo_correcto.jsonl", vigilancia_settings)
    assert "incident_declared" in patterns
    assert "escalation_done" in patterns


def test_e2b_detects_declared_without_escalation(vigilancia_settings):
    patterns = _patterns("e2b_declarado_sin_escalar.jsonl", vigilancia_settings)
    assert "incident_declared" in patterns
    assert "escalation_done" not in patterns


def test_e3_detects_restore_ok_verified_and_communicated(vigilancia_settings):
    patterns = _patterns("e3_flujo_correcto.jsonl", vigilancia_settings)
    assert patterns["restore_exercise_run"].resultado == "ok"
    assert "restore_verified" in patterns
    assert "recovery_communicated" in patterns


def test_e3b_detects_restore_failure_without_verification(vigilancia_settings):
    patterns = _patterns("e3b_restauracion_fallida.jsonl", vigilancia_settings)
    assert patterns["restore_exercise_run"].resultado == "fail"
    assert "restore_verified" not in patterns


def test_burst_below_threshold_n_is_not_detected(vigilancia_settings):
    from datetime import UTC, datetime

    from app.surveillance.events import RawEvent
    from app.surveillance.patterns import detect_patterns

    events = [
        RawEvent(
            event_id=f"ev-{i}",
            event_time=datetime(2026, 1, 1, 0, 0, i, tzinfo=UTC),
            tipo="auth_failure",
            recurso="r1",
            scope="s",
            actor="a1",
        )
        for i in range(3)  # n=5 por defecto: 3 fallos no alcanza el umbral
    ]
    matches = detect_patterns(events, vigilancia_settings)
    assert all(m.patron != "auth_failures_burst" for m in matches)


def test_burst_outside_time_window_is_not_detected(vigilancia_settings):
    from datetime import UTC, datetime, timedelta

    from app.surveillance.events import RawEvent

    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    events = [
        RawEvent(
            event_id=f"ev-{i}",
            event_time=base + timedelta(minutes=i * 10),  # muy espaciados: fuera de la ventana
            tipo="auth_failure",
            recurso="r1",
            scope="s",
            actor="a1",
        )
        for i in range(6)
    ]
    matches = detect_patterns(events, vigilancia_settings)
    assert all(m.patron != "auth_failures_burst" for m in matches)
