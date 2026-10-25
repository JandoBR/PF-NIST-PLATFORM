"""OP-12 (backoff, log por llamada, validacion E5, tope de ajustes) y OP-14 (reproducibilidad)."""

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai import calllog
from app.ai import client as client_module
from app.ai.cache import CachingAIClient
from app.ai.client import DeepSeekClient, FakeAIClient, NullAIClient
from app.ai.extraction import extract_claims
from app.core import assessment_service as svc
from app.core import refresh, reproducibility
from app.evaluation import engine
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import load_methodology
from app.schemas.evidence import Locator

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
TF_GOOD = Path(__file__).resolve().parent / "fixtures" / "terraform" / "good"
POLICY_DOC = Path(__file__).resolve().parent / "fixtures" / "documents" / "politica-seguridad.md"


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


# -- backoff y log por llamada --------------------------------------------------------------


class _Completions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def create(self, **_):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _client(outcomes):
    sleeps: list[float] = []
    deepseek = DeepSeekClient(api_key="k", sleep=sleeps.append)
    completions = _Completions(outcomes)
    deepseek._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return deepseek, completions, sleeps


def test_retries_wait_with_exponential_backoff_then_succeed():
    deepseek, completions, sleeps = _client([RuntimeError("x"), RuntimeError("y"), _response("{}")])
    assert deepseek.complete_json("s", "u") == {}
    assert completions.calls == 3
    assert sleeps == [1.0, 2.0]


def test_degrades_after_retries_without_extra_waiting():
    deepseek, completions, sleeps = _client([RuntimeError("x")] * 3)
    assert deepseek.complete_json("s", "u") is None
    assert completions.calls == client_module.MAX_RETRIES + 1
    assert sleeps == [1.0, 2.0]


def test_first_attempt_success_never_sleeps():
    deepseek, _, sleeps = _client([_response('{"a": 1}')])
    assert deepseek.complete_json("s", "u") == {"a": 1}
    assert sleeps == []


def test_each_call_logs_context_outcome_and_tokens(caplog):
    deepseek, _, _ = _client([_response('{"a": 1}')])
    with caplog.at_level(logging.INFO, logger="app.ai.calls"):
        with calllog.call_context(paso="U2", prompt_version="adjust_v1", criterion_id="CRI-PR-01"):
            deepseek.complete_json("s", "u")
    registro = next(r for r in caplog.records if r.name == "app.ai.calls").getMessage()
    esperado = ('"paso": "U2"', '"criterion_id": "CRI-PR-01"', '"resultado": "ok"', '"total": 15')
    for fragmento in esperado:
        assert fragmento in registro


def test_degraded_call_is_logged_with_reason(caplog):
    deepseek, _, _ = _client([_response("no es json")] * 3)
    with caplog.at_level(logging.INFO, logger="app.ai.calls"):
        assert deepseek.complete_json("s", "u") is None
    registro = next(r for r in caplog.records if r.name == "app.ai.calls").getMessage()
    assert '"resultado": "degradado"' in registro and "json_invalido" in registro


def test_cache_hit_is_logged(tmp_path, caplog):
    inner = FakeAIClient({"u": {"ok": True}})
    cached = CachingAIClient(inner, cache_dir=tmp_path)
    cached.complete_json("s", "u")
    with caplog.at_level(logging.INFO, logger="app.ai.calls"):
        cached.complete_json("s", "u")
    assert '"resultado": "cache"' in caplog.records[-1].getMessage()


# -- E5: formatos esperados -------------------------------------------------------------------


def _extract(contenido, tipo="policy_review"):
    client = FakeAIClient(
        {
            "DOC": {
                "afirmaciones": [
                    {
                        "tipo": tipo,
                        "encontrado": True,
                        "contenido": contenido,
                        "cita": {"fragmento": "texto"},
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )
    return extract_claims(
        client,
        chunk_text="DOC",
        chunk_locator=Locator(file="p.md"),
        tipos_solicitados=[tipo],
        doc_id="p",
        source_id="t",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )[0].value["contenido"]


@pytest.mark.parametrize("fecha", ["31-02-2024", "ayer", "1850-01-01", "2999-01-01"])
def test_absurd_review_dates_are_dropped_but_claim_is_kept(fecha):
    contenido = _extract({"frecuencia": "anual", "ultima_revision": fecha})
    assert contenido["ultima_revision"] is None
    assert contenido["frecuencia"] == "anual"
    assert any("ultima_revision" in d for d in contenido["_descartados"])


def test_valid_review_fields_are_untouched():
    contenido = _extract({"frecuencia": "Anual", "ultima_revision": "2026-01-15"})
    assert contenido == {"frecuencia": "Anual", "ultima_revision": "2026-01-15"}


def test_unknown_frequency_is_dropped():
    contenido = _extract({"frecuencia": "de vez en cuando", "ultima_revision": None})
    assert contenido["frecuencia"] is None


def test_invalid_roles_are_filtered():
    contenido = _extract(
        {
            "roles": [
                {"rol": "CISO", "responsable": "Ana"},
                {"rol": ""},
                {"x": 1},
                "texto",
                {"rol": "r" * 500},
            ]
        },
        tipo="role_assigned",
    )
    assert contenido["roles"] == [{"rol": "CISO", "responsable": "Ana"}]
    assert "4 entrada(s)" in contenido["_descartados"][0]


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("true", True), ("false", False), ("Si", True), ("NO", False), (1, True), (0, False)],
)
def test_booleans_written_as_text_are_normalized(valor, esperado):
    """Las reglas preguntan por verdad simple, y en Python `"false"` es verdadero: un modelo que
    responde texto donde se pide bool daria un falso positivo en un campo que decide puntaje."""

    contenido = _extract({"proceso": "riesgos", "impactos": valor}, tipo="process_defined")

    assert contenido["impactos"] is esperado
    assert "_descartados" not in contenido


def test_a_boolean_that_cannot_be_interpreted_is_dropped_not_guessed():
    contenido = _extract(
        {"proceso": "riesgos", "registro_riesgos": "parcialmente, ver anexo"},
        tipo="process_defined",
    )

    assert "registro_riesgos" not in contenido
    assert any("registro_riesgos" in d for d in contenido["_descartados"])


# -- tope de ajustes por evaluacion -------------------------------------------------------------


class _CountingClient:
    def __init__(self):
        self.prompts: list[str] = []

    def complete_json(self, system_prompt, user_prompt):
        self.prompts.append(user_prompt)
        return None


def _scored(criterion_id: str) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=Estado.EVALUADO,
        base_score=50,
        final_score=50,
        explanation="base",
    )


def _adjustable_ids(methodology) -> list[str]:
    return [cid for cid, c in methodology.criterios.items() if c.ai_adjustable]


def test_cap_limits_adjustments_to_the_heaviest_criteria(methodology):
    ids = _adjustable_ids(methodology)
    results = [_scored(cid) for cid in ids]
    ia = methodology.settings.ia.model_copy(update={"max_criterios_ajustados_por_evaluacion": 2})
    capped = replace(methodology, settings=methodology.settings.model_copy(update={"ia": ia}))

    client = _CountingClient()
    ajustados = engine.apply_ai_adjustments(capped, results, [], client, {})

    assert len(client.prompts) == 2
    esperados = sorted(ids, key=lambda cid: (-methodology.criterios[cid].peso, cid))[:2]
    degradados = {r.criterion_id for r in ajustados if r.degradado}
    assert degradados == set(esperados)  # los demas no se intentaron: no se marcan degradados


def test_no_cap_attempts_every_adjustable_criterion(methodology):
    ids = _adjustable_ids(methodology)
    client = _CountingClient()
    engine.apply_ai_adjustments(methodology, [_scored(cid) for cid in ids], [], client, {})
    assert len(client.prompts) == len(ids)


# -- OP-14: reproducibilidad ---------------------------------------------------------------------


def test_assessment_records_adapter_versions_without_ai(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Repro",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
        ai_client=NullAIClient(),
    )
    info = assessment.reproducibility
    assert set(info["adapters"]) == {"terraform"}
    assert info["adapters"]["terraform"]["parser"].startswith("python-hcl2 ")
    assert info["ai"] is None


class _ModelClient(FakeAIClient):
    model = "deepseek-test"


def test_assessment_records_model_and_prompt_versions_when_ai_participates(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Repro IA",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
        documents_path=POLICY_DOC,
        ai_client=_ModelClient({}),
        apply_ai_adjustment=True,
    )
    ai = assessment.reproducibility["ai"]
    assert ai == {
        "modelo": "deepseek-test",
        "extraccion": "extract_v3",
        "ajuste": "adjust_v1",
    }
    assert set(assessment.reproducibility["adapters"]) == {"terraform", "documents"}


def test_model_is_found_through_the_cache_wrapper(tmp_path):
    assert reproducibility.model_name(CachingAIClient(_ModelClient({}), cache_dir=tmp_path)) == (
        "deepseek-test"
    )
    assert reproducibility.model_name(NullAIClient()) is None
    assert reproducibility.model_name(None) is None


def test_ai_plans_are_recorded_after_regeneration(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Repro Planes",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
    )
    assert assessment.reproducibility["ai"] is None
    svc.generate_plans(db_session, methodology, assessment.id, ai_client=_ModelClient({}))
    db_session.refresh(assessment)
    assert assessment.reproducibility["ai"] == {"modelo": "deepseek-test", "planes": "plan_v1"}


def test_surveillance_refresh_inherits_reproducibility(db_session, methodology):
    previous = svc.run_assessment(
        db_session,
        methodology,
        org_name="Repro Refresh",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
        documents_path=POLICY_DOC,
        ai_client=_ModelClient({}),
    )
    nuevo = svc.create_pending_assessment(
        db_session,
        methodology,
        org_name="Repro Refresh",
        scope="entorno:produccion",
        previous_assessment_id=previous.id,
    )
    refresh.run_surveillance_refresh(db_session, methodology, nuevo.id, previous.id)
    db_session.refresh(nuevo)
    assert nuevo.reproducibility == previous.reproducibility
