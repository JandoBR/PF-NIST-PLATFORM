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
        chunk_text="... fue aprobada por la Direccion General el 1 de marzo de 2025 ...",
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
    assert claim.value["cita"] == "aprobada por la Direccion General el 1 de marzo de 2025"
    assert claim.type_version == 2
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
    que el prompt ofrece. Antes no se ofrecia `respuesta` y CRI-RS-01 no encontraba un plan."""

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


# -- E8: la cita tiene que estar en el texto enviado -------------------------------------------


def _one_claim(fragmento: str, chunk_text: str):
    client = FakeAIClient(
        {
            "Direccion": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {"nombre": "Politica", "aprobada_por": "Direccion General"},
                        "cita": {"fragmento": fragmento},
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )
    (claim,) = extract_claims(
        client,
        chunk_text=chunk_text,
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists"],
        doc_id="politica",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )
    return claim


def test_a_quote_that_is_not_in_the_text_is_kept_but_does_not_score():
    from app.ai.extraction import CITA_NO_LOCALIZABLE
    from app.evaluation.rules import gv01_policy

    claim = _one_claim(
        "aprobada por el Directorio en 2024",  # inventada: el texto dice otra cosa
        "La politica fue aprobada por la Direccion General el 1 de marzo de 2025.",
    )

    assert claim.limitations == CITA_NO_LOCALIZABLE
    assert claim.value["cita"] == "aprobada por el Directorio en 2024"  # queda a la vista
    resultado = gv01_policy.evaluate([claim])
    assert resultado.final_score is None  # no cuenta: GV-01 no tiene evidencia utilizable


def test_quote_matching_ignores_case_accents_and_spacing():
    claim = _one_claim(
        "APROBADA por la   Dirección General",
        "La politica fue aprobada por la Direccion\nGeneral el 1 de marzo.",
    )

    assert claim.limitations is None


def test_low_confidence_and_unlocatable_quote_are_both_recorded():
    from app.ai.extraction import CITA_NO_LOCALIZABLE

    client = FakeAIClient(
        {
            "Direccion": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {},
                        "cita": {"fragmento": "texto que no esta"},
                        "confianza": 0.3,
                    }
                ]
            }
        }
    )
    (claim,) = extract_claims(
        client,
        chunk_text="Direccion General",
        chunk_locator=LOCATOR,
        tipos_solicitados=["policy_exists"],
        doc_id="d",
        source_id="s",
        scope="e",
        confianza_minima=0.6,
    )

    assert "confianza baja" in claim.limitations and CITA_NO_LOCALIZABLE in claim.limitations
