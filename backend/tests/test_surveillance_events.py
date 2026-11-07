from pathlib import Path

import pytest

from app.surveillance.events import SurveillanceError, load_events_jsonl

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scenarios"


def test_loads_and_sorts_events_by_event_time():
    events = load_events_jsonl(FIXTURES / "e1_flujo_correcto.jsonl")

    assert len(events) == 7
    assert events == sorted(events, key=lambda e: e.event_time)
    assert events[0].tipo == "auth_failure"
    assert events[-1].tipo == "incident_triaged"


def test_blank_lines_are_skipped(tmp_path):
    path = tmp_path / "with_blanks.jsonl"
    path.write_text(
        '{"event_id": "x1", "event_time": "2026-01-01T00:00:00Z", "tipo": "auth_failure",'
        ' "recurso": "r", "scope": "s"}\n\n\n'
    )
    events = load_events_jsonl(path)
    assert len(events) == 1


def test_invalid_json_raises_with_line_number(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("{not valid json\n")
    with pytest.raises(SurveillanceError, match="bad.jsonl:1"):
        load_events_jsonl(path)


def test_missing_required_field_raises(tmp_path):
    path = tmp_path / "missing_field.jsonl"
    payload = '{"event_time": "2026-01-01T00:00:00Z", "tipo": "x", "recurso": "r", "scope": "s"}\n'
    path.write_text(payload)
    with pytest.raises(SurveillanceError, match="missing_field.jsonl:1"):
        load_events_jsonl(path)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_event_details_are_rejected(tmp_path, value):
    path = tmp_path / "non_finite.jsonl"
    path.write_text(
        '{"event_id": "x", "event_time": "2026-01-01T00:00:00Z", "tipo": "x",'
        f' "recurso": "r", "scope": "s", "detalle": {{"value": {value}}}}}\n'
    )

    with pytest.raises(SurveillanceError, match="non_finite.jsonl:1"):
        load_events_jsonl(path)
