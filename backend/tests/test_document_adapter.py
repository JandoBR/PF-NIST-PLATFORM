from pathlib import Path

from app.adapters.documents.adapter import DocumentAdapter
from app.ai.client import FakeAIClient, NullAIClient
from app.methodology.loader import load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "documents"

_FAKE_RESPONSES = {
    "Politica de Seguridad de la Informacion": {
        "afirmaciones": [
            {
                "tipo": "policy_exists",
                "encontrado": True,
                "contenido": {
                    "nombre": "Politica de Seguridad de la Informacion",
                    "aprobada_por": "Direccion General",
                },
                "cita": {"fragmento": "aprobada por la Direccion General el 1 de marzo de 2025"},
                "confianza": 0.9,
            },
            {
                "tipo": "policy_review",
                "encontrado": True,
                "contenido": {"frecuencia": "anual", "ultima_revision": "2026-02-01"},
                "cita": {"fragmento": "La ultima revision se realizo el 2026-02-01"},
                "confianza": 0.85,
            },
        ]
    },
    "aprobada por la Direccion General": {
        "afirmaciones": [
            {
                "tipo": "policy_exists",
                "encontrado": True,
                "contenido": {
                    "nombre": "Politica de Seguridad de la Informacion",
                    "aprobada_por": "Direccion General",
                },
                "cita": {"fragmento": "aprobada por la Direccion General el 1 de marzo de 2025"},
                "confianza": 0.9,
            }
        ]
    },
}


def test_document_adapter_produces_doc_claim_evidence_with_citations():
    methodology = load_methodology(METHODOLOGY_DIR)
    client = FakeAIClient(_FAKE_RESPONSES)
    adapter = DocumentAdapter(
        client, methodology, source_id="test:politica", scope="entorno:produccion"
    )

    evidence = adapter.parse_path(
        FIXTURES / "politica-seguridad.md", tipos_solicitados=["policy_exists", "policy_review"]
    )

    claims = [e for e in evidence if e.type_id == "doc.claim"]
    assert len(claims) == 2
    tipos = {e.value["tipo_afirmacion"] for e in claims}
    assert tipos == {"policy_exists", "policy_review"}
    # Las dos secciones van en un solo chunk, pero cada cita conserva la seccion de donde sale.
    assert {claim.locator.section for claim in claims} == {
        "Politica de Seguridad de la Informacion",
        "Revision",
    }


def test_document_without_matching_keywords_produces_no_evidence():
    methodology = load_methodology(METHODOLOGY_DIR)
    client = FakeAIClient(_FAKE_RESPONSES)
    adapter = DocumentAdapter(
        client, methodology, source_id="test:manual", scope="entorno:produccion"
    )

    evidence = adapter.parse_path(
        FIXTURES / "manual-operaciones.md", tipos_solicitados=["policy_exists", "policy_review"]
    )

    assert evidence == []


def test_chunks_beyond_the_cap_are_skipped_not_sent(tmp_path):
    doc = tmp_path / "largo.md"
    doc.write_text("\n".join(f"# Seccion {i}\ncontenido {i}" for i in range(5)))

    methodology = load_methodology(METHODOLOGY_DIR)
    client = FakeAIClient(_FAKE_RESPONSES)  # ninguna palabra clave coincide: siempre None
    adapter = DocumentAdapter(
        client,
        methodology,
        source_id="test:largo",
        scope="entorno:produccion",
        max_chunks_per_document=2,
        max_chars_per_chunk=10,  # cada seccion, sola, ya supera este presupuesto
    )

    adapter.parse_path(doc, tipos_solicitados=["policy_exists"])

    assert adapter.chunks_omitidos == 3  # 5 secciones - tope de 2


# -- doc.source.info: documento analizado (docs/05 §2.3 E6, docs/11 CR-07) -----------------------


def _adapter(client, **kwargs):
    return DocumentAdapter(
        client,
        load_methodology(METHODOLOGY_DIR),
        source_id="test:info",
        scope="entorno:produccion",
        **kwargs,
    )


def _info(evidence):
    return [e for e in evidence if e.type_id == "doc.source.info"]


def test_an_analyzed_document_is_marked_even_when_a_section_has_no_claims():
    """E6: el documento se marca como analizado aunque una seccion no de afirmaciones."""

    evidence = _adapter(FakeAIClient(_FAKE_RESPONSES)).parse_path(
        FIXTURES / "politica-seguridad.md", tipos_solicitados=["policy_exists", "policy_review"]
    )

    (info,) = _info(evidence)
    assert info.subject_ref == "doc:politica-seguridad" and info.modality.value == "documental"
    assert info.value == {
        "titulo": "politica-seguridad",
        "archivo": "politica-seguridad.md",
        "secciones": 2,
        "analizadas": 2,
        "omitidas": 0,
        "sin_respuesta": 0,
    }


def test_a_document_the_ai_never_answered_is_not_marked_as_analyzed():
    """Degradar sin inventar: no se dice "se leyo" de lo que no se leyo."""

    evidence = _adapter(NullAIClient()).parse_path(
        FIXTURES / "politica-seguridad.md", tipos_solicitados=["policy_exists"]
    )

    assert evidence == []


def test_partial_answers_are_counted(tmp_path):
    doc = tmp_path / "mixto.md"
    doc.write_text("# A\nmanual de operaciones\n# B\naprobada por la Direccion General\n")

    (info,) = _info(
        _adapter(FakeAIClient(_FAKE_RESPONSES), max_chars_per_chunk=10).parse_path(
            doc, tipos_solicitados=["policy_exists"]
        )
    )

    assert (info.value["secciones"], info.value["analizadas"], info.value["sin_respuesta"]) == (
        2,
        1,
        1,
    )


def test_the_section_cap_is_recorded_as_omitted(tmp_path):
    doc = tmp_path / "largo.md"
    secciones = (f"# Seccion {i}\naprobada por la Direccion General {i}" for i in range(5))
    doc.write_text("\n".join(secciones))

    (info,) = _info(
        _adapter(
            FakeAIClient(_FAKE_RESPONSES),
            max_chunks_per_document=2,
            max_chars_per_chunk=10,
        ).parse_path(doc, tipos_solicitados=["policy_exists"])
    )

    assert (info.value["secciones"], info.value["analizadas"], info.value["omitidas"]) == (5, 2, 3)


def test_a_document_without_text_is_marked_with_zero_sections(tmp_path):
    vacio = tmp_path / "vacio.txt"
    vacio.write_text("")

    adapter = _adapter(FakeAIClient(_FAKE_RESPONSES))
    (info,) = _info(adapter.parse_path(vacio, tipos_solicitados=["policy_exists"]))

    assert info.value["secciones"] == 0  # registrado, pero no habia nada que analizar
