from app.ai.client import FakeAIClient
from app.ai.extraction import extract_claims
from app.schemas.evidence import Locator

LOCATOR = Locator(file="politica-seguridad.md", section="Politica de Seguridad de la Informacion")


def test_extracts_claim_with_valid_citation():
    client = FakeAIClient(
        {
            "Direccion General": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {
                            "nombre": "Politica de Seguridad de la Informacion",
                            "aprobada_por": "Direccion General",
                            "fecha": "2025-03-01",
                        },
                        "cita": {
                            "pagina": None,
                            "seccion": None,
                            "fragmento": "aprobada por la Direccion General el 1 de marzo de 2025",
                        },
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )

    evidence = extract_claims(
        client,
        chunk_text="... aprobada por la Direccion General ...",
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists", "policy_review"],
        doc_id="politica-seguridad",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )

    assert len(evidence) == 1
    claim = evidence[0]
    assert claim.type_id == "doc.claim"
    assert claim.subject_ref == "doc:politica-seguridad"
    assert claim.value["tipo_afirmacion"] == "policy_exists"
    assert claim.value["contenido"]["aprobada_por"] == "Direccion General"
    assert claim.limitations is None


def test_found_claim_without_citation_is_discarded():
    client = FakeAIClient(
        {
            "SIN_CITA": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {"nombre": "Politica X"},
                        "cita": None,
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )

    evidence = extract_claims(
        client,
        chunk_text="texto con SIN_CITA en alguna parte",
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists"],
        doc_id="doc",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )

    assert evidence == []


def test_low_confidence_is_kept_but_flagged_as_limitation():
    client = FakeAIClient(
        {
            "BAJA_CONFIANZA": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {"nombre": "Politica X"},
                        "cita": {"fragmento": "algo ambiguo"},
                        "confianza": 0.3,
                    }
                ]
            }
        }
    )

    evidence = extract_claims(
        client,
        chunk_text="texto BAJA_CONFIANZA",
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists"],
        doc_id="doc",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )

    assert len(evidence) == 1
    assert evidence[0].limitations is not None


def test_not_found_claim_needs_no_citation():
    client = FakeAIClient(
        {
            "NO_DECLARA": {
                "afirmaciones": [
                    {"tipo": "policy_exists", "encontrado": False, "confianza": 0.0},
                ]
            }
        }
    )

    evidence = extract_claims(
        client,
        chunk_text="texto NO_DECLARA nada relevante",
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists"],
        doc_id="doc",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )

    assert len(evidence) == 1
    assert evidence[0].value["encontrado"] is False


def test_degrades_to_empty_list_when_ai_unavailable():
    client = FakeAIClient({})  # ninguna palabra clave coincide -> siempre None

    evidence = extract_claims(
        client,
        chunk_text="cualquier texto",
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists"],
        doc_id="doc",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )

    assert evidence == []
