"""docs/09 §100: el contenido vacio de DeepSeek era el presupuesto de tokens agotado.

`deepseek-flash` razona antes de escribir el JSON y esos tokens salen del mismo `max_tokens`; con
2000 el JSON no llegaba a empezar (`finish_reason="length"`, contenido vacio). Estos tests fijan dos
cosas: el cliente distingue ese caso en el log y el reintento sube el techo en vez de repetir la
misma peticion.
"""

import logging
from types import SimpleNamespace

from app.ai import client as client_module
from app.ai.client import DeepSeekClient


class _Completions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(content: str | None, finish_reason: str, completion_tokens: int = 2000):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, reasoning_content="pensando..."),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=1480,
            completion_tokens=completion_tokens,
            total_tokens=1480 + completion_tokens,
        ),
    )


def _client(outcomes, **kwargs):
    deepseek = DeepSeekClient(api_key="k", sleep=lambda _: None, **kwargs)
    completions = _Completions(outcomes)
    deepseek._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return deepseek, completions


def test_an_empty_answer_cut_by_max_tokens_retries_with_a_bigger_budget(caplog):
    """El caso real: completion=2000 (el techo), finish=length, contenido vacio.

    Repetir la misma peticion con el mismo techo da lo mismo; el reintento pide el doble.
    """

    deepseek, completions = _client(
        [_response(None, "length"), _response('{"afirmaciones": []}', "stop")]
    )
    with caplog.at_level(logging.INFO):
        assert deepseek.complete_json("s", "u") == {"afirmaciones": []}

    assert len(completions.calls) == 2
    assert completions.calls[0]["max_tokens"] == client_module.DEFAULT_MAX_TOKENS
    assert completions.calls[1]["max_tokens"] == client_module.DEFAULT_MAX_TOKENS * 2
    assert any(
        "finish=length" in r.getMessage() and "razonamiento=True" in r.getMessage()
        for r in caplog.records
    )


def test_the_degraded_reason_says_which_finish_reason_left_it_empty(caplog):
    deepseek, completions = _client([_response(None, "length")] * 3)

    with caplog.at_level(logging.INFO, logger="app.ai.calls"):
        assert deepseek.complete_json("s", "u") is None

    assert len(completions.calls) == 3
    motivo = next(r for r in caplog.records if r.name == "app.ai.calls").getMessage()
    assert "respuesta_vacia:length" in motivo


def test_the_budget_stops_growing_at_the_ceiling_and_does_not_retry_forever():
    deepseek, completions = _client([_response(None, "length")] * 5, max_tokens=1000)

    assert deepseek.complete_json("s", "u") is None
    # 1000 -> 2000 -> 4000 ... hasta el techo; despues no hay nada nuevo que probar.
    assert [c["max_tokens"] for c in completions.calls] == [1000, 2000, 4000]


def test_a_blank_content_with_stop_is_also_empty(caplog):
    """El modo JSON de DeepSeek reemplaza por espacios la salida que no es JSON."""

    deepseek, completions = _client([_response("   ", "stop"), _response('{"a": 1}', "stop")])

    assert deepseek.complete_json("s", "u") == {"a": 1}
    assert len(completions.calls) == 2


def test_a_content_filtered_answer_is_not_retried(caplog):
    deepseek, completions = _client([_response(None, "content_filter")])

    with caplog.at_level(logging.INFO, logger="app.ai.calls"):
        assert deepseek.complete_json("s", "u") is None

    assert len(completions.calls) == 1
    assert "respuesta_vacia:content_filter" in caplog.records[-1].getMessage()


def test_the_budget_is_configurable_by_environment(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "4000")
    assert DeepSeekClient(api_key="k").max_tokens == 4000


def test_an_invalid_budget_falls_back_instead_of_raising(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "muchos")
    assert DeepSeekClient(api_key="k").max_tokens == client_module.DEFAULT_MAX_TOKENS
