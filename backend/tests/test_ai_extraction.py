from pathlib import Path

import pytest

from app.ai.client import FakeAIClient
from app.ai.extraction import (
    _CONTENT_FIELDS,
    _SYSTEM_PROMPT,
    PROMPT_VERSION,
    _build_user_prompt,
    _sanitize_content,
    extract_claims,
)
from app.schemas.evidence import Locator, Segmento

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
    assert claim.type_version == 3
    assert claim.limitations is None
    assert claim.value["estado_declarado"] == "vigente"  # sin campo explicito: v6 lo exige igual


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


# -- Chunks agrupados: el locator vuelve a la seccion/pagina de la cita ------------------------


def _grouped_claim(fragmento: str):
    texto = "# Gobierno\nCISO designado.\n\n# Respaldos\nLos respaldos son diarios."
    inicio_respaldos = texto.index("# Respaldos")
    segmentos = (
        Segmento(
            inicio=0,
            fin=inicio_respaldos,
            locator=Locator(file="doc.md", section="Gobierno"),
        ),
        Segmento(
            inicio=inicio_respaldos,
            fin=len(texto),
            locator=Locator(file="doc.md", section="Respaldos"),
        ),
    )
    client = FakeAIClient(
        {
            "Respaldos": {
                "afirmaciones": [
                    {
                        "tipo": "backup_policy",
                        "encontrado": True,
                        "contenido": {"respaldo": True},
                        "cita": {"fragmento": fragmento},
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )
    (claim,) = extract_claims(
        client,
        chunk_text=texto,
        chunk_locator=segmentos[0].locator,
        segmentos=segmentos,
        tipos_solicitados=["backup_policy"],
        doc_id="doc",
        source_id="s",
        scope="e",
        confianza_minima=0.6,
    )
    return claim


def test_a_grouped_chunk_keeps_the_section_of_the_citation():
    claim = _grouped_claim("Los respaldos son diarios")

    assert claim.locator.section == "Respaldos"


def test_an_unlocatable_fragment_falls_back_to_the_first_section():
    claim = _grouped_claim("texto que no esta en ningun tramo")

    assert claim.locator.section == "Gobierno"
    assert claim.limitations is not None  # E8 sigue marcandola


def test_a_grouped_pdf_chunk_keeps_the_page_of_the_citation():
    texto = "pagina uno\n\npagina dos"
    segmentos = (
        Segmento(inicio=0, fin=10, locator=Locator(file="doc.pdf", page=3)),
        Segmento(inicio=12, fin=25, locator=Locator(file="doc.pdf", page=4)),
    )
    client = FakeAIClient(
        {
            "pagina dos": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {"nombre": "Politica"},
                        "cita": {"fragmento": "pagina dos"},
                        "confianza": 0.9,
                    }
                ]
            }
        }
    )
    (claim,) = extract_claims(
        client,
        chunk_text=texto,
        chunk_locator=segmentos[0].locator,
        segmentos=segmentos,
        tipos_solicitados=["policy_exists"],
        doc_id="doc",
        source_id="s",
        scope="e",
        confianza_minima=0.6,
    )

    assert claim.locator.page == 4


def test_prompt_v8_asks_for_each_type_independently_and_the_declared_state():
    """Un chunk agrupado trae varias secciones: la extraccion de un tipo no depende de los demas
    (docs/09 §103), y una negacion o un plan no se confunde con la practica vigente (§106).
    `process_defined` es la excepcion: una afirmacion por proceso, sin fusionarlos (§111), y
    `policy_review` solo cubre la revision de la politica (§115)."""

    assert PROMPT_VERSION == "extract_v8"
    assert "cada tipo solicitado de forma independiente" in _SYSTEM_PROMPT
    assert "varias secciones" in _SYSTEM_PROMPT
    assert "estado_declarado" in _SYSTEM_PROMPT
    assert "inexistente" in _SYSTEM_PROMPT and "planificado" in _SYSTEM_PROMPT
    assert "noventa dias" in _SYSTEM_PROMPT and "90 dias" in _SYSTEM_PROMPT
    assert "afirmacion por cada proceso distinto" in _SYSTEM_PROMPT
    assert 'proceso "analisis incidentes"' in _SYSTEM_PROMPT
    assert '"mejora"' in _SYSTEM_PROMPT
    assert "policy_review es solo la revision periodica del documento de politica" in _SYSTEM_PROMPT
    assert 'proceso "revision"' in _SYSTEM_PROMPT


def test_data_inventory_fields_include_technology_assets():
    """El inventario de activos tecnologicos alimenta `data_inventory.activos`, que es lo que mira
    CRI-ID-01; sin los tipos de recurso no hay cobertura verificable."""

    campos = _CONTENT_FIELDS["data_inventory"]
    assert "recursos tecnologicos" in campos
    assert "aws_db_instance" in campos


def test_user_prompt_declares_the_fields_of_every_requested_type():
    prompt = _build_user_prompt("texto", ["data_inventory", "policy_exists"], "doc")

    assert (
        "Tipos de afirmacion a buscar en este fragmento: data_inventory, policy_exists." in prompt
    )
    assert "- data_inventory: activos (lista de recursos tecnologicos" in prompt
    assert "- policy_exists: nombre (string), aprobada_por (string|null)" in prompt


# -- v6: estado declarado de la practica (docs/09 §106) ---------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _extract_one(
    afirmacion: dict,
    *,
    chunk_text: str,
    tipos: list[str],
    doc_id: str = "doc",
):
    client = FakeAIClient({"afirmacion": {"afirmaciones": [afirmacion]}})
    evidence = extract_claims(
        client,
        chunk_text=f"afirmacion {chunk_text}",
        chunk_locator=LOCATOR,
        tipos_solicitados=tipos,
        doc_id=doc_id,
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )
    return evidence[0] if evidence else None


def test_a_missing_declared_state_reads_as_vigente_for_older_claims():
    claim = _extract_one(
        {
            "tipo": "policy_exists",
            "encontrado": True,
            "contenido": {"nombre": "Politica"},
            "cita": {"fragmento": "Politica aprobada"},
            "confianza": 0.9,
        },
        chunk_text="Politica aprobada",
        tipos=["policy_exists"],
    )

    assert claim is not None and claim.value["estado_declarado"] == "vigente"


def test_an_explicit_negation_keeps_its_literal_citation():
    texto = (FIXTURES / "documents" / "estudio" / "explicit-negations.md").read_text(
        encoding="utf-8"
    )
    negacion = "No hay un procedimiento documentado de respuesta a incidentes"

    claim = _extract_one(
        {
            "tipo": "process_defined",
            "encontrado": True,
            "estado_declarado": "inexistente",
            "contenido": {"proceso": "respuesta"},
            "cita": {"fragmento": negacion},
            "confianza": 0.9,
        },
        chunk_text=texto,
        tipos=["process_defined"],
    )

    assert claim is not None
    assert claim.value["estado_declarado"] == "inexistente"
    assert claim.value["cita"] == negacion
    assert claim.limitations is None  # E8: la negacion es literal del documento


def test_an_unrecognized_declared_state_discards_the_claim():
    claim = _extract_one(
        {
            "tipo": "policy_exists",
            "encontrado": True,
            "estado_declarado": "quizas despues",
            "contenido": {"nombre": "Politica"},
            "cita": {"fragmento": "Politica"},
            "confianza": 0.9,
        },
        chunk_text="Politica",
        tipos=["policy_exists"],
    )

    assert claim is None


def test_a_claim_not_found_has_no_declared_state():
    claim = _extract_one(
        {"tipo": "policy_exists", "encontrado": False, "confianza": 0.0},
        chunk_text="nada",
        tipos=["policy_exists"],
    )

    assert claim is not None and claim.value["estado_declarado"] is None


@pytest.mark.parametrize(
    ("tipo", "contenido", "campo", "esperado"),
    [
        ("backup_policy", {"retencion": "noventa días"}, "retencion", "90 días"),
        ("risk_tolerance", {"tolerancia": "cuatro horas al mes"}, "tolerancia", "4 horas al mes"),
        (
            "notification_list",
            {"plazos": "setenta y dos horas"},
            "plazos",
            "72 horas",
        ),
        (
            "process_defined",
            {"criterios_activacion": "cada tres meses"},
            "criterios_activacion",
            "cada 3 meses",
        ),
    ],
)
def test_number_words_in_quantity_fields_become_digits(tipo, contenido, campo, esperado):
    assert _sanitize_content(tipo, contenido)[campo] == esperado


def test_a_review_frequency_written_with_words_is_understood():
    limpio = _sanitize_content("policy_review", {"frecuencia": "cada tres meses"})

    assert limpio["frecuencia"] == "trimestral"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("cada 12 meses", "anual"),
        ("cada 1 año", "anual"),
        ("cada 6 meses", "semestral"),
        ("cada 1 mes", "mensual"),
        ("cada tres meses", "trimestral"),
    ],
)
def test_review_frequency_quantities(texto, esperado):
    assert _sanitize_content("policy_review", {"frecuencia": texto})["frecuencia"] == esperado


@pytest.mark.parametrize("estado", ["inexistente", "planificado"])
def test_a_claim_about_the_process_otro_does_not_identify_a_practice(estado):
    """Negar "otro" no dice que practica falta: antes hacia que RS-01, ID-03 y RC-01 se
    contradijeran entre si y perdieran sus afirmaciones vigentes (docs/09 §108)."""

    claim = _extract_one(
        {
            "tipo": "process_defined",
            "encontrado": True,
            "estado_declarado": estado,
            "contenido": {"proceso": "otro"},
            "cita": {"fragmento": "Todavia no hay un procedimiento escrito"},
            "confianza": 0.9,
        },
        chunk_text="Todavia no hay un procedimiento escrito",
        tipos=["process_defined"],
    )

    assert claim is None


def test_a_denial_without_content_is_discarded_unless_the_type_names_the_practice():
    """Un `data_inventory` vacio no distingue "no hay datos" de "no se nombro ningun dato"; una
    `policy_exists` vacia si identifica la politica. El primero no puede contradecir el inventario
    que otro documento declara (docs/09 §108)."""

    client = FakeAIClient(
        {
            "afirmacion": {
                "afirmaciones": [
                    {
                        "tipo": "data_inventory",
                        "encontrado": True,
                        "estado_declarado": "inexistente",
                        "contenido": {},
                        "cita": {"fragmento": "No hay inventario de los servicios criticos"},
                        "confianza": 0.9,
                    },
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "estado_declarado": "inexistente",
                        "contenido": {},
                        "cita": {"fragmento": "La politica no esta aprobada"},
                        "confianza": 0.9,
                    },
                    {
                        "tipo": "supplier_program",
                        "encontrado": True,
                        "estado_declarado": "inexistente",
                        "contenido": {"programa": False, "requisitos_contractuales": False},
                        "cita": {"fragmento": "No existe un programa de proveedores"},
                        "confianza": 0.9,
                    },
                ]
            }
        }
    )

    evidence = extract_claims(
        client,
        chunk_text=(
            "afirmacion No hay inventario de los servicios criticos. La politica no esta aprobada."
            " No existe un programa de proveedores."
        ),
        chunk_locator=LOCATOR,
        tipos_solicitados=["data_inventory", "policy_exists", "supplier_program"],
        doc_id="doc",
        source_id="test:doc",
        scope="entorno:produccion",
        confianza_minima=0.6,
    )

    assert {e.value["tipo_afirmacion"] for e in evidence} == {"policy_exists", "supplier_program"}


def test_an_empty_plan_for_a_program_is_kept_because_the_type_identifies_it():
    claim = _extract_one(
        {
            "tipo": "training_program",
            "encontrado": True,
            "estado_declarado": "planificado",
            "contenido": {},
            "cita": {"fragmento": "La formacion se implementara en 2027"},
            "confianza": 0.9,
        },
        chunk_text="La formacion se implementara en 2027",
        tipos=["training_program"],
    )

    assert claim is not None and claim.value["estado_declarado"] == "planificado"
