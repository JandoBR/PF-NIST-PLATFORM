from pathlib import Path

from app.adapters.documents.adapter import DocumentAdapter
from app.ai.client import FakeAIClient
from app.methodology.loader import load_methodology

METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "documents"

_FAKE_RESPONSES = {
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
    "revisa con una frecuencia anual": {
        "afirmaciones": [
            {
                "tipo": "policy_review",
                "encontrado": True,
                "contenido": {"frecuencia": "anual", "ultima_revision": "2026-02-01"},
                "cita": {"fragmento": "La ultima revision se realizo el 2026-02-01"},
                "confianza": 0.85,
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

    assert len(evidence) == 2
    tipos = {e.value["tipo_afirmacion"] for e in evidence}
    assert tipos == {"policy_exists", "policy_review"}
    for claim in evidence:
        assert claim.locator.section is not None


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
    )

    adapter.parse_path(doc, tipos_solicitados=["policy_exists"])

    assert adapter.chunks_omitidos == 3  # 5 secciones - tope de 2
