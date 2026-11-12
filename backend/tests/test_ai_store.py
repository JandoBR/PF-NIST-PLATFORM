"""Store persistente de resultados de IA (docs/05 §7, docs/09 §105)."""

from __future__ import annotations

import threading

from app.ai import extraction
from app.ai.calllog import call_context
from app.ai.store import AIResultStore, StoreAIClient
from app.core.db import build_engine, build_session_factory, create_all
from app.models.tables import AIResult, Organization
from app.schemas.evidence import Locator

LOCATOR = Locator(file="politica.md", section="Politica")
CHUNK = "La politica fue aprobada por la Direccion General el 1 de marzo de 2025."


class _CountingClient:
    """Cliente real simulado: cuenta llamadas y devuelve una respuesta fija."""

    def __init__(self, response: dict | None) -> None:
        self.response = response
        self.calls = 0

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        self.calls += 1
        return self.response


class _ScriptedClient:
    """Devuelve una respuesta distinta por llamada (para votar tres corridas)."""

    def __init__(self, responses: list[dict | None]) -> None:
        self._responses = list(responses)
        self._lock = threading.Lock()
        self.calls = 0

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        with self._lock:
            self.calls += 1
            return self._responses.pop(0)


def _engine(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path}/store.db")
    create_all(engine)
    return engine


def _org(engine, nombre: str) -> Organization:
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        org = Organization(nombre=nombre)
        session.add(org)
        session.commit()
        return org


def _store(engine, org: Organization, *, reextraer: bool = False, votes: int = 3):
    return AIResultStore(
        build_session_factory(engine),
        org.id,
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        params_hash="params",
        votes=votes,
        reextraer=reextraer,
    )


def _u2(client, sha: str = "insumo"):
    with call_context(paso="U2", prompt_version="adjust_v1", input_sha256=sha):
        return client.complete_json("system", "user")


def _claim(
    tipo: str = "policy_exists",
    contenido: dict | None = None,
    confianza: float = 0.9,
    cita: str = "La politica fue aprobada por la Direccion General el 1 de marzo de 2025.",
) -> dict:
    return {
        "tipo": tipo,
        "encontrado": True,
        "contenido": contenido if contenido is not None else {"nombre": "Politica"},
        "cita": {"fragmento": cita},
        "confianza": confianza,
    }


def _extraer(client):
    return extraction.extract_claims(
        client,
        chunk_text=CHUNK,
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists"],
        doc_id="politica",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )


# -- Store ------------------------------------------------------------------------------------


def test_same_input_in_two_containers_hits_the_same_row(tmp_path):
    engine = _engine(tmp_path)
    org = _org(engine, "Org")

    primero = _CountingClient({"puntaje_propuesto": 40})
    assert _u2(StoreAIClient(primero, _store(engine, org))) == {"puntaje_propuesto": 40}

    # Otro proceso/contenedor: otro cliente y otra sesion, la misma BD.
    segundo = _CountingClient({"puntaje_propuesto": 99})
    assert _u2(StoreAIClient(segundo, _store(engine, org))) == {"puntaje_propuesto": 40}
    assert segundo.calls == 0
    assert primero.calls == 1

    session_factory = build_session_factory(engine)
    with session_factory() as session:
        assert session.query(AIResult).count() == 1


def test_a_different_input_is_a_miss(tmp_path):
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    client = StoreAIClient(_CountingClient({"r": 1}), _store(engine, org))

    _u2(client, sha="a")
    _u2(client, sha="b")

    assert client.result_store.stats()["U2"] == {"hits": 0, "misses": 2}


def test_never_reuses_a_result_across_organizations(tmp_path):
    engine = _engine(tmp_path)
    org_a = _org(engine, "Org A")
    org_b = _org(engine, "Org B")

    _u2(StoreAIClient(_CountingClient({"r": "de A"}), _store(engine, org_a)))
    b = _CountingClient({"r": "de B"})
    assert _u2(StoreAIClient(b, _store(engine, org_b))) == {"r": "de B"}
    assert b.calls == 1

    # Y A sigue viendo lo suyo.
    assert _u2(StoreAIClient(_CountingClient({"r": "otra"}), _store(engine, org_a))) == {
        "r": "de A"
    }


def test_a_degraded_response_is_not_cached(tmp_path):
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    client = StoreAIClient(_CountingClient(None), _store(engine, org))

    assert _u2(client) is None
    assert _u2(client) is None
    assert client._inner.calls == 2


def test_reextraer_ignores_the_stored_result_and_replaces_it(tmp_path):
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    _u2(StoreAIClient(_CountingClient({"r": "viejo"}), _store(engine, org)))

    nuevo = _CountingClient({"r": "nuevo"})
    assert _u2(StoreAIClient(nuevo, _store(engine, org, reextraer=True))) == {"r": "nuevo"}
    assert nuevo.calls == 1

    # La respuesta fresca quedo guardada: la proxima lectura normal ya no llama al modelo.
    otro = _CountingClient({"r": "no se usa"})
    assert _u2(StoreAIClient(otro, _store(engine, org))) == {"r": "nuevo"}
    assert otro.calls == 0


def test_reextraer_counts_as_miss_in_the_stats(tmp_path):
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    _u2(StoreAIClient(_CountingClient({"r": 1}), _store(engine, org)))

    store = _store(engine, org, reextraer=True)
    _u2(StoreAIClient(_CountingClient({"r": 2}), store))
    assert store.stats()["U2"] == {"hits": 0, "misses": 1}


def test_two_threads_with_the_same_key_keep_a_single_row(tmp_path):
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    resultados = ["primero", "segundo"]
    threads = [
        threading.Thread(
            target=lambda r=r: _u2(StoreAIClient(_CountingClient({"r": r}), _store(engine, org)))
        )
        for r in resultados
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    session_factory = build_session_factory(engine)
    with session_factory() as session:
        filas = session.query(AIResult).all()
    assert len(filas) == 1
    assert filas[0].output["r"] in resultados


# -- U1: votacion y store ---------------------------------------------------------------------


def test_u1_default_votes_three_runs_and_stores_the_voted_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("U1_VOTES", "3")
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    cliente = _ScriptedClient(
        [
            {"afirmaciones": [_claim(contenido={"nombre": "Politica de Seguridad"})]},
            {"afirmaciones": [_claim(contenido={"nombre": "POLITICA DE SEGURIDAD "})]},
            {"afirmaciones": [_claim(contenido={"nombre": "Otra cosa"})]},
        ]
    )
    store = _store(engine, org)
    claims = _extraer(StoreAIClient(cliente, store))

    assert cliente.calls == 3
    (claim,) = claims
    assert claim.value["contenido"] == {"nombre": "Politica de Seguridad"}

    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.query(AIResult).one()
    assert row.kind == "U1"
    assert row.meta["votos"] == 3
    assert len(row.output["afirmaciones"]) == 1


def test_u1_second_extraction_reads_the_store_instead_of_calling_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("U1_VOTES", "3")
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    _extraer(
        StoreAIClient(
            _ScriptedClient([{"afirmaciones": [_claim()]} for _ in range(3)]), _store(engine, org)
        )
    )

    otro = _CountingClient({"afirmaciones": [_claim(contenido={"nombre": "no se usa"})]})
    claims = _extraer(StoreAIClient(otro, _store(engine, org)))
    assert otro.calls == 0
    assert claims[0].value["contenido"] == {"nombre": "Politica"}


def test_u1_votes_1_is_a_single_call_and_uses_the_wrapper_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("U1_VOTES", "1")
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    cliente = _ScriptedClient([{"afirmaciones": [_claim()]}])
    claims = _extraer(StoreAIClient(cliente, _store(engine, org)))

    assert cliente.calls == 1
    assert len(claims) == 1

    otro = _CountingClient({"afirmaciones": [_claim(contenido={"nombre": "no se usa"})]})
    assert _extraer(StoreAIClient(otro, _store(engine, org)))[0].value["contenido"] == {
        "nombre": "Politica"
    }
    assert otro.calls == 0


def test_u1_does_not_store_a_result_when_most_runs_degraded(tmp_path, monkeypatch):
    """Si solo una de tres corridas respondio no hay mayoria: la proxima vez se reintenta."""

    monkeypatch.setenv("U1_VOTES", "3")
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    cliente = _ScriptedClient([{"afirmaciones": [_claim()]}, None, None])
    _extraer(StoreAIClient(cliente, _store(engine, org)))

    session_factory = build_session_factory(engine)
    with session_factory() as session:
        assert session.query(AIResult).count() == 0


def test_u1_input_key_ignores_the_prompt_but_not_the_chunk_or_document():
    a = extraction._u1_input_sha256("texto", ["policy_exists", "policy_review"], "doc-a")
    b = extraction._u1_input_sha256("texto", ["policy_review", "policy_exists"], "doc-a")
    c = extraction._u1_input_sha256("texto", ["policy_exists"], "doc-a")
    d = extraction._u1_input_sha256("texto", ["policy_exists"], "doc-b")

    assert a == b  # orden de tipos: el mismo insumo
    assert a != c and a != d


def test_store_is_reachable_through_wrappers(tmp_path):
    from app.ai.store import store_for

    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    store = _store(engine, org)
    inner = StoreAIClient(_CountingClient({}), store)

    assert store_for(inner) is store
    assert store_for(object()) is None


def test_reproducibility_records_hits_votes_and_params(tmp_path):
    from app.core import reproducibility

    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    client = StoreAIClient(_CountingClient({"r": 1}), _store(engine, org))
    _u2(client)
    _u2(client)

    info = reproducibility.with_ai_cache({"adapters": {}}, client)

    assert info["ai"]["cache"] == {
        "U1": {"hits": 0, "misses": 0},
        "U2": {"hits": 1, "misses": 1},
        "U3": {"hits": 0, "misses": 0},
    }
    assert info["ai"]["votos"] == 3
    assert info["ai"]["params_hash"] == "params"
    assert info["ai"]["modelo"] == "deepseek-flash"


def test_build_default_client_uses_the_db_store_with_a_session(tmp_path, monkeypatch):
    """Camino de produccion (api/workers): con sesion y organizacion, la cache es la tabla."""

    from app.ai.client import NullAIClient, build_default_client

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    engine = _engine(tmp_path)
    org = _org(engine, "Org")
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        client = build_default_client(session=session, org_id=org.id)
        assert isinstance(client, StoreAIClient)
        assert client.result_store.org_id == org.id

    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with session_factory() as session:
        assert isinstance(build_default_client(session=session, org_id=org.id), NullAIClient)
