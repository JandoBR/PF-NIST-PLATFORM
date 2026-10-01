from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ai.client import FakeAIClient
from app.methodology.loader import load_methodology
from app.ops.plans import generate_incident_plan
from app.ops.triggers import TriggerMatch

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


def _trigger(disparador="D1", criterios=None) -> TriggerMatch:
    now = datetime.now(UTC)
    return TriggerMatch(
        disparador=disparador,
        correlation_key=f"test:{disparador}",
        severidad="media",
        criterios=criterios or ["CRI-DE-02", "CRI-DE-03"],
        titulo="Titulo de prueba",
        recurso="srv-app-01",
        first_event_time=now,
        last_event_time=now,
        event_ids=["e1", "e2"],
    )


def test_falls_back_to_template_without_ai(methodology):
    plan = generate_incident_plan(methodology, _trigger())

    assert plan.generado_por == "plantilla"
    assert plan.origen == "evento"
    assert plan.prioridad == "media"
    assert "srv-app-01" in plan.diagnostico_observable
    assert plan.hipotesis
    assert plan.comprobaciones_seguras
    assert "no se ejecuta" in plan.advertencia.lower()


def test_skips_unimplemented_criterion_and_uses_the_next_one(methodology):
    # CRI-DE-03 no esta implementado en el catalogo; debe usar CRI-DE-02.
    plan = generate_incident_plan(methodology, _trigger(criterios=["CRI-DE-03", "CRI-DE-02"]))
    assert plan.criterion_id == "CRI-DE-02"


def test_uses_ai_content_when_available(methodology):
    client = FakeAIClient(
        {
            "CRI-DE-02": {
                "titulo": "Plan generado por IA",
                "objetivo": "objetivo ia",
                "pasos": ["paso ia"],
                "verificacion": "verificar ia",
                "dependencias": [],
            }
        }
    )
    plan = generate_incident_plan(methodology, _trigger(), client=client)

    assert plan.generado_por == "ai:plan_v1"
    assert plan.titulo == "Plan generado por IA"
    # el diagnostico siempre es deterministico, incluso con IA activa
    assert "srv-app-01" in plan.diagnostico_observable


@pytest.mark.parametrize("disparador", ["D1", "D3", "D4", "D5"])
def test_each_trigger_has_a_template(methodology, disparador):
    criterios_por_disparador = {
        "D1": ["CRI-DE-02"],
        "D3": ["CRI-RS-01"],
        "D4": ["CRI-RC-02"],
        "D5": ["CRI-RC-03"],
    }
    plan = generate_incident_plan(
        methodology, _trigger(disparador=disparador, criterios=criterios_por_disparador[disparador])
    )
    assert plan.diagnostico_observable
    assert plan.hipotesis
    assert plan.comprobaciones_seguras
