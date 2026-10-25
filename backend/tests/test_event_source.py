"""FN-07: el origen (`fuente`) de cada evento llega a `events.source_id` y a la evidencia."""

import json

from app.core import assessment_service as svc
from app.core import operations
from app.models.tables import Event, LogPatternRow

SCOPE = "entorno:produccion"


def _fallos(tmp_path, nombre, fuente, n=6, desde=0):
    lineas = []
    for i in range(n):
        evento = {
            "event_id": f"{nombre}-{i}",
            "event_time": f"2026-09-20T03:{10 + (desde + i) // 60:02d}:{(desde + i) % 60:02d}Z",
            "tipo": "auth_failure",
            "recurso": "srv-app-01",
            "scope": SCOPE,
            "actor": "admin",
        }
        if fuente:
            evento["fuente"] = fuente
        lineas.append(json.dumps(evento))
    archivo = tmp_path / f"{nombre}.jsonl"
    archivo.write_text("\n".join(lineas))
    return archivo


def _ingest(db_session, methodology, archivo):
    return operations.ingest_events(db_session, methodology, "Empresa Origen", archivo)


def test_event_source_id_is_the_declared_fuente(db_session, methodology, tmp_path):
    _ingest(db_session, methodology, _fallos(tmp_path, "a", "log:sshd"))

    assert {e.source_id for e in db_session.query(Event).all()} == {"log:sshd"}


def test_event_without_fuente_falls_back_to_the_file_name_not_the_server_path(
    db_session, methodology, tmp_path
):
    _ingest(db_session, methodology, _fallos(tmp_path, "b", None))

    (source_id,) = {e.source_id for e in db_session.query(Event).all()}
    assert source_id == "events:b.jsonl" and str(tmp_path) not in source_id


def test_patterns_and_window_evidence_carry_the_origin(db_session, methodology, tmp_path):
    _ingest(db_session, methodology, _fallos(tmp_path, "c", "log:sshd"))
    org_id = db_session.query(Event).first().org_id

    filas = db_session.query(LogPatternRow).all()
    assert filas and all(p.fuentes == ["log:sshd"] for p in filas)
    evidence = svc.collect_surveillance_evidence(db_session, org_id, SCOPE)
    assert {e.type_id for e in evidence} == {"log.window", "log.pattern"}
    assert {e.source_id for e in evidence} == {"log:sshd"}
    # log.pattern@2: la lista de origenes llega al valor, no solo al `source_id`. Sin esto,
    # CRI-DE-02 no podria distinguir correlacion de deteccion (DE.AE-03).
    patrones = [e for e in evidence if e.type_id == "log.pattern"]
    assert all(e.type_version == 2 and e.value["fuentes"] == ["log:sshd"] for e in patrones)


def test_pattern_evidence_lists_every_origin_that_formed_it(db_session, methodology, tmp_path):
    """Dos sistemas que registran los mismos fallos: el patron sale con los dos origenes, que es
    lo que CRI-DE-02 lee para afirmar correlacion."""

    _ingest(db_session, methodology, _fallos(tmp_path, "g", "log:sshd"))
    _ingest(db_session, methodology, _fallos(tmp_path, "h", "cloudtrail", desde=5))
    org_id = db_session.query(Event).first().org_id

    patron = next(
        e
        for e in svc.collect_surveillance_evidence(db_session, org_id, SCOPE)
        if e.type_id == "log.pattern" and e.value["patron"] == "auth_failures_burst"
    )

    assert patron.value["fuentes"] == ["cloudtrail", "log:sshd"]


def test_window_lists_every_origin_in_the_scope(db_session, methodology, tmp_path):
    _ingest(db_session, methodology, _fallos(tmp_path, "d", "log:sshd"))
    _ingest(db_session, methodology, _fallos(tmp_path, "e", "cloudtrail", desde=30))
    org_id = db_session.query(Event).first().org_id

    window = next(
        e
        for e in svc.collect_surveillance_evidence(db_session, org_id, SCOPE)
        if e.type_id == "log.window"
    )

    assert window.source_id == "cloudtrail+log:sshd"


def test_patterns_before_fn07_keep_the_legacy_source_id(db_session, methodology, tmp_path):
    _ingest(db_session, methodology, _fallos(tmp_path, "f", "log:sshd"))
    org_id = db_session.query(Event).first().org_id
    for fila in db_session.query(LogPatternRow).all():
        fila.fuentes = None
    db_session.commit()

    patterns = [
        e
        for e in svc.collect_surveillance_evidence(db_session, org_id, SCOPE)
        if e.type_id == "log.pattern"
    ]

    assert patterns and {e.source_id for e in patterns} == {"surveillance:org"}
