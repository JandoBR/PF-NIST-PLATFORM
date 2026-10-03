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


def test_every_process_rule_can_be_reached_from_the_extraction_vocabulary():
    """Cada regla que filtra `process_defined` por `contenido.proceso` debe poder recibir un valor
    que el prompt ofrece. Antes no se ofrecia `respuesta` y CRI-RS-01 no encontraba nunca un plan."""

    import re
    from datetime import UTC, datetime

    from app.ai.extraction import _CONTENT_FIELDS
    from app.evaluation.rules import (
        de02_event_analysis,
        gv04_strategy_review,
        id03_risk_assessment,
        rc01_recovery_procedure,
        rs01_response_plan,
        rs02_incident_analysis,
    )
    from app.schemas.evidence import EvidenceInstance, Locator, Modality

    vocabulario = re.search(r"proceso \(([^)]*)\)", _CONTENT_FIELDS["process_defined"]).group(1)
    opciones = vocabulario.split("|")

    def claim(proceso):
        return EvidenceInstance(
            type_id="doc.claim",
            type_version=1,
            subject_type="document",
            subject_ref="doc:x",
            scope="s",
            value={
                "tipo_afirmacion": "process_defined",
                "contenido": {"proceso": proceso},
                "encontrado": True,
                "confianza": 0.9,
            },
            source_id="s",
            locator=Locator(file="x.md"),
            observed_at=datetime.now(UTC),
            modality=Modality.DOCUMENTAL,
            created_by="ai:extraction",
        )

    filtros = {
        "CRI-RS-01": rs01_response_plan._es_de_respuesta,
        "CRI-RC-01": rc01_recovery_procedure._es_de_recuperacion,
        "CRI-GV-04": gv04_strategy_review._es_de_revision,
        "CRI-ID-03": id03_risk_assessment._es_de_riesgos,
        "CRI-RS-02": rs02_incident_analysis._es_de_analisis,
        "CRI-DE-02": de02_event_analysis._es_de_declaracion,
    }
    inalcanzables = [cid for cid, f in filtros.items() if not any(f(claim(o)) for o in opciones)]
    assert inalcanzables == []
