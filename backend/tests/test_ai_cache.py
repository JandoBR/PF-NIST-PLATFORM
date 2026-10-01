from app.ai.cache import CachingAIClient


class _CountingClient:
    """Cuenta llamadas reales para probar que el cache evita repetirlas."""

    def __init__(self, response: dict | None) -> None:
        self.response = response
        self.calls = 0

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        self.calls += 1
        return self.response


def test_identical_prompt_hits_cache_not_the_real_client(tmp_path):
    inner = _CountingClient({"afirmaciones": []})
    client = CachingAIClient(inner, cache_dir=tmp_path)

    first = client.complete_json("system", "user A")
    second = client.complete_json("system", "user A")

    assert first == second == {"afirmaciones": []}
    assert inner.calls == 1  # la segunda llamada no debio tocar el cliente real


def test_different_prompts_are_not_confused(tmp_path):
    inner = _CountingClient({"afirmaciones": []})
    client = CachingAIClient(inner, cache_dir=tmp_path)

    client.complete_json("system", "user A")
    client.complete_json("system", "user B")

    assert inner.calls == 2


def test_degraded_none_result_is_never_cached(tmp_path):
    inner = _CountingClient(None)
    client = CachingAIClient(inner, cache_dir=tmp_path)

    client.complete_json("system", "user A")
    client.complete_json("system", "user A")

    assert inner.calls == 2  # sin cache: un resultado vacio no debe quedar pegado


def test_cache_persists_across_client_instances(tmp_path):
    inner = _CountingClient({"afirmaciones": ["x"]})
    CachingAIClient(inner, cache_dir=tmp_path).complete_json("system", "user A")

    other_inner = _CountingClient({"afirmaciones": ["deberia no usarse"]})
    result = CachingAIClient(other_inner, cache_dir=tmp_path).complete_json("system", "user A")

    assert result == {"afirmaciones": ["x"]}
    assert other_inner.calls == 0
