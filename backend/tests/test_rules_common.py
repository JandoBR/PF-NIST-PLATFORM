"""Helpers de reglas: seleccion determinista de la mejor afirmacion (docs/00 §7)."""

from datetime import UTC, datetime

from app.evaluation.rules._common import (
    best_found,
    contradicciones_booleanas,
    latest_pattern,
    merged_content,
)
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(ref: str, contenido: dict) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=2,
        subject_type="document",
        subject_ref=ref,
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": "policy_exists",
            "encontrado": True,
            "contenido": contenido,
            "confianza": 0.9,
        },
        source_id="test:common",
        locator=Locator(file=ref),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="ai:extraction",
    )


def test_best_found_breaks_ties_deterministically_not_by_list_order():
    a = _claim("doc-b", {"nombre": "Politica B"})
    b = _claim("doc-a", {"nombre": "Politica A"})

    assert best_found([a, b]).subject_ref == "doc-a"
    assert best_found([b, a]).subject_ref == "doc-a"


def test_best_found_still_prefers_higher_confidence():
    a = _claim("doc-a", {"nombre": "Politica A"})
    b = _claim("doc-b", {"nombre": "Politica B"})
    b.value["confianza"] = 0.95

    assert best_found([a, b]).subject_ref == "doc-b"


def _pattern(patron: str, hasta: str, resultado: str = "ok") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="log.pattern",
        type_version=2,
        subject_type="scope",
        subject_ref="entorno:produccion",
        scope="entorno:produccion",
        value={
            "patron": patron,
            "resultado": resultado,
            "desde": "2026-01-01T00:00:00Z",
            "hasta": hasta,
            "conteo": 1,
        },
        source_id="test:common",
        locator=Locator(event_id="e1..e2"),
        observed_at=datetime.now(UTC),
        modality=Modality.OPERATIVA,
        created_by="surveillance",
    )


def test_merged_content_joins_fields_from_several_fragments():
    """Un documento partido en fragmentos declara cada faceta en su propio `doc.claim`: el
    contenido se arma con el mejor valor de cada campo, no con el de un solo fragmento."""

    completo = _claim("doc-a", {"mision": "pagos", "dependencias": ["nube"]})
    corto = _claim("doc-b", {"requisitos_legales": ["PCI DSS"]})
    corto.value["confianza"] = 0.7

    contenido, aportantes = merged_content([corto, completo])

    assert contenido == {
        "mision": "pagos",
        "dependencias": ["nube"],
        "requisitos_legales": ["PCI DSS"],
    }
    assert [c.subject_ref for c in aportantes] == ["doc-a", "doc-b"]


def test_merged_content_does_not_let_a_silent_claim_hide_a_field():
    callada = _claim("doc-a", {"mision": None})
    callada.value["confianza"] = 0.99
    declara = _claim("doc-b", {"mision": "pagos"})

    contenido, aportantes = merged_content([callada, declara])

    assert contenido["mision"] == "pagos"
    assert [c.subject_ref for c in aportantes] == ["doc-b"]


def test_merged_content_sums_booleans_across_documents():
    """Booleanos entre documentos distintos: el `or` se mantiene. Que un documento de la
    organizacion declare la practica alcanza, aunque otro no la mencione."""

    a = _claim("doc-a", {"programa": True, "terminacion": False})
    b = _claim("doc-b", {"programa": False, "terminacion": True})

    contenido, aportantes = merged_content([a, b])

    assert contenido == {"programa": True, "terminacion": True}
    assert {c.subject_ref for c in aportantes} == {"doc-a", "doc-b"}


def test_merged_content_a_document_that_contradicts_itself_uses_the_most_confident():
    """Un `false` puede ser una negacion explicita ("no se realiza X"): dentro del mismo documento
    no se suma con `or`, vale la afirmacion mas confiable (docs/09 §101)."""

    niega = _claim("doc:a", {"programa": True, "debida_diligencia": False})
    niega.value["confianza"] = 0.95
    declara = _claim("doc:a", {"programa": True, "debida_diligencia": True})
    declara.value["confianza"] = 0.7

    contenido, aportantes = merged_content([declara, niega])

    assert contenido["debida_diligencia"] is False
    assert contenido["programa"] is True
    assert [c.id for c in aportantes] == [niega.id]

    (conflicto,) = contradicciones_booleanas([declara, niega])
    assert (conflicto.documento, conflicto.campo, conflicto.valor) == (
        "doc:a",
        "debida_diligencia",
        False,
    )
    assert conflicto.archivo == "doc:a"
    assert set(conflicto.claim_ids) == {declara.id, niega.id}


def test_a_negation_of_a_fragment_does_not_hide_another_document_declaration():
    """La contradiccion es por documento: el fragmento que niega en `doc:a` no borra el `true`
    de `doc:b`."""

    niega = _claim("doc:a", {"terminacion": False})
    niega.value["confianza"] = 0.99
    declara = _claim("doc:b", {"terminacion": True})
    declara.value["confianza"] = 0.6

    contenido, _ = merged_content([declara, niega])

    assert contenido["terminacion"] is True
    assert contradicciones_booleanas([declara, niega]) == []


def test_contradicciones_booleanas_ignores_non_boolean_fields():
    a = _claim("doc:a", {"mision": "pagos"})
    b = _claim("doc:a", {"mision": "logistica"})

    assert contradicciones_booleanas([a, b]) == []


def test_latest_pattern_picks_the_latest_hasta_not_the_list_order():
    viejo = _pattern("restore_verified", "2026-01-01T00:05:00Z")
    nuevo = _pattern("restore_verified", "2026-01-01T00:20:00Z")

    assert latest_pattern([viejo, nuevo], "restore_verified") is nuevo
    assert latest_pattern([nuevo, viejo], "restore_verified") is nuevo
