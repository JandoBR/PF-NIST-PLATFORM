"""Oleada A (2/2): los tres criterios documentales que cierran las categorias vacias del CSF.

`CRI-GV-05` (GV.OC), `CRI-GV-06` (GV.SC) y `CRI-PR-07` (PR.AT). Cada uno estrena un tipo de
afirmacion, asi que lo que se fija aqui es el mapeo campo -> tramo: que cada subcategoria declarada
dependa de que su dato venga, y que el silencio documental siga siendo `evidencia_insuficiente` y
nunca 0 (docs/09 60).
"""

from datetime import UTC, datetime

import pytest

from app.evaluation import engine
from app.evaluation.rules import gv05_org_context, gv06_supply_chain, pr07_awareness
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(
    tipo: str,
    contenido: dict | None = None,
    encontrado: bool = True,
    confianza: float = 0.9,
) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:gobierno",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido or {},
            "encontrado": encontrado,
            "confianza": confianza,
        },
        source_id="src",
        locator=Locator(file="gobierno.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


# -- CRI-GV-05 (contexto organizacional) --------------------------------------------

_CONTEXTO_COMPLETO = {
    "mision": "Procesar pagos para comercios de la region",
    "partes_interesadas": ["clientes", "reguladores", "accionistas"],
    "requisitos_legales": ["Ley 1581 de proteccion de datos", "PCI DSS"],
    "servicios_criticos": ["plataforma de pagos", "portal de clientes"],
    "dependencias": ["proveedor de nube", "pasarela bancaria"],
}


def test_gv05_without_documents_is_insufficient():
    assert gv05_org_context.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


def test_gv05_all_five_outcomes_score_100():
    result = gv05_org_context.evaluate([_claim("org_context", _CONTEXTO_COMPLETO)])
    assert result.final_score == 100
    assert "Falta declarar" not in result.explanation


def test_gv05_three_of_five_score_75_and_name_what_is_missing():
    contenido = {k: _CONTEXTO_COMPLETO[k] for k in ("mision", "partes_interesadas", "dependencias")}
    result = gv05_org_context.evaluate([_claim("org_context", contenido)])
    assert result.final_score == 75
    assert "GV.OC-03" in result.explanation and "GV.OC-04" in result.explanation


def test_gv05_one_outcome_scores_50():
    result = gv05_org_context.evaluate([_claim("org_context", {"mision": "Procesar pagos"})])
    assert result.final_score == 50


def test_gv05_the_five_outcomes_are_merged_across_chunks_of_the_same_document():
    """El documento se parte en fragmentos y cada uno declara parte de GV.OC: puntuar solo el
    fragmento mas confiable mediria uno de los cuatro, no el documento (daba 50, no 100)."""

    fragmentos = [
        _claim("org_context", {"mision": "Procesar pagos", "partes_interesadas": ["clientes"]}),
        _claim("org_context", {"requisitos_legales": ["PCI DSS"]}, confianza=0.8),
        _claim("org_context", {"servicios_criticos": ["plataforma"]}, confianza=0.7),
        _claim("org_context", {"dependencias": ["nube"]}, confianza=0.6),
    ]

    result = gv05_org_context.evaluate(fragmentos)

    assert result.final_score == 100
    assert "Falta declarar" not in result.explanation
    assert set(result.evidence_ids) == {c.id for c in fragmentos}


def test_gv05_an_empty_context_claim_is_silence_not_zero():
    result = gv05_org_context.evaluate([_claim("org_context", {"mision": None})])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert "no equivale a 0" in result.explanation


def test_gv05_a_claim_marked_not_found_is_silence():
    result = gv05_org_context.evaluate(
        [_claim("org_context", _CONTEXTO_COMPLETO, encontrado=False)]
    )
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


# -- CRI-GV-06 (cadena de suministro) ----------------------------------------------


def test_gv06_without_documents_is_insufficient():
    assert gv06_supply_chain.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


#: Las nueve facetas de GV.SC que `gv06_supply_chain._CAMPOS` lee, en orden de declaracion.
_FACETAS_SC = (
    "roles",
    "integracion_riesgo",
    "proveedores_priorizados",
    "requisitos_contractuales",
    "debida_diligencia",
    "riesgos_monitoreados",
    "en_respuesta_incidentes",
    "monitoreo_ciclo_vida",
    "terminacion",
)


def _programa(n_facetas: int) -> dict:
    return {"programa": True, **{campo: True for campo in _FACETAS_SC[:n_facetas]}}


@pytest.mark.parametrize(
    ("facetas", "esperado"),
    [(9, 100), (7, 100), (6, 75), (4, 75), (3, 50), (1, 50), (0, 25)],
)
def test_gv06_scores_by_how_many_practices_the_program_declares(facetas, esperado):
    """GV.SC es una lista de practicas, no un interruptor: si el 100 dependiera solo de que exista
    un programa, las diez subcategorias se sostendrian en una sola frase."""

    result = gv06_supply_chain.evaluate([_claim("supplier_program", _programa(facetas))])

    assert result.final_score == esperado
    assert f"{facetas} de 9 practicas" in result.explanation


def test_gv06_names_the_practices_that_are_missing():
    result = gv06_supply_chain.evaluate([_claim("supplier_program", _programa(4))])

    assert "GV.SC-06" in result.explanation and "GV.SC-10" in result.explanation


def test_gv06_suppliers_mentioned_without_a_program_is_silence():
    """Mencionar proveedores no es tener un programa: insuficiente, no 0."""

    result = gv06_supply_chain.evaluate(
        [_claim("supplier_program", {"programa": False, "roles": True})]
    )
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert "no equivale a 0" in result.explanation


def test_gv06_the_practices_are_merged_across_chunks_of_the_same_document():
    """El programa y las nueve practicas pueden caer en fragmentos distintos; antes solo contaba
    el fragmento mas confiable y las practicas de los demas se perdian."""

    programa = _claim("supplier_program", {"programa": True})
    practicas = _claim(
        "supplier_program",
        {campo: True for campo in _FACETAS_SC[:7]},
        confianza=0.7,
    )

    result = gv06_supply_chain.evaluate([practicas, programa])

    assert result.final_score == 100
    assert set(result.evidence_ids) == {programa.id, practicas.id}


# -- CRI-PR-07 (concienciacion y formacion) ----------------------------------------


def test_pr07_without_documents_is_insufficient():
    assert pr07_awareness.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


def test_pr07_program_with_frequency_and_specialized_roles_scores_100():
    contenido = {"programa": True, "frecuencia": "anual", "roles_especializados": True}
    assert pr07_awareness.evaluate([_claim("training_program", contenido)]).final_score == 100


def test_pr07_program_without_specialized_roles_caps_at_75():
    contenido = {"programa": True, "frecuencia": "anual", "roles_especializados": False}
    result = pr07_awareness.evaluate([_claim("training_program", contenido)])
    assert result.final_score == 75
    assert "PR.AT-02" in result.explanation


def test_pr07_specialized_roles_without_frequency_also_caps_at_75():
    contenido = {"programa": True, "roles_especializados": True}
    assert pr07_awareness.evaluate([_claim("training_program", contenido)]).final_score == 75


def test_pr07_frequency_and_specialized_roles_can_come_from_different_chunks():
    programa = _claim("training_program", {"programa": True, "frecuencia": "anual"}, confianza=0.95)
    roles = _claim("training_program", {"roles_especializados": True}, confianza=0.7)

    result = pr07_awareness.evaluate([roles, programa])

    assert result.final_score == 100
    assert set(result.evidence_ids) == {programa.id, roles.id}


def test_pr07_bare_program_scores_50():
    result = pr07_awareness.evaluate([_claim("training_program", {"programa": True})])
    assert result.final_score == 50


def test_pr07_training_mentioned_without_a_program_is_silence():
    result = pr07_awareness.evaluate([_claim("training_program", {"programa": False})])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert "no equivale a 0" in result.explanation


def test_pr07_a_low_confidence_claim_does_not_count():
    """`doc_claims` excluye las afirmaciones con limitacion/confianza baja (E3)."""

    claim = _claim("training_program", {"programa": True, "frecuencia": "anual"})
    claim = claim.model_copy(update={"limitations": "confianza por debajo del umbral"})
    assert pr07_awareness.evaluate([claim]).estado == Estado.EVIDENCIA_INSUFICIENTE


# -- Contradicciones dentro de un documento (docs/09 §101) ---------------------------


def test_gv06_a_document_that_denies_due_diligence_does_not_get_the_facet(methodology):
    programa = _claim(
        "supplier_program",
        {
            "programa": True,
            "roles": True,
            "integracion_riesgo": True,
            "proveedores_priorizados": True,
            "debida_diligencia": False,
        },
        confianza=0.95,
    )
    niega = _claim("supplier_program", {"programa": True, "debida_diligencia": True}, confianza=0.6)

    (result,) = engine.evaluate_only(methodology, [niega, programa], ["CRI-GV-06"])

    assert result.final_score == 50
    assert "se contradice sobre debida_diligencia" in result.explanation


def test_gv06_due_diligence_declared_in_another_document_does_count(methodology):
    programa = _claim(
        "supplier_program",
        {
            "programa": True,
            "roles": True,
            "integracion_riesgo": True,
            "proveedores_priorizados": True,
            "debida_diligencia": False,
        },
        confianza=0.95,
    )
    otra = _claim(
        "supplier_program", {"programa": True, "debida_diligencia": True}, confianza=0.6
    ).model_copy(update={"subject_ref": "doc:otra-politica", "locator": Locator(file="otra.md")})

    (result,) = engine.evaluate_only(methodology, [programa, otra], ["CRI-GV-06"])

    assert result.final_score == 75
    assert "se contradice" not in result.explanation


def test_pr07_a_fragment_that_denies_specialized_training_caps_at_75(methodology):
    programa = _claim(
        "training_program",
        {"programa": True, "frecuencia": "anual", "roles_especializados": False},
        confianza=0.95,
    )
    niega = _claim(
        "training_program", {"programa": True, "roles_especializados": True}, confianza=0.6
    )

    (result,) = engine.evaluate_only(methodology, [niega, programa], ["CRI-PR-07"])

    assert result.final_score == 75
    assert "se contradice sobre roles_especializados" in result.explanation


def test_pr07_specialized_training_declared_in_another_document_does_count(methodology):
    programa = _claim(
        "training_program",
        {"programa": True, "frecuencia": "anual", "roles_especializados": False},
        confianza=0.95,
    )
    otra = _claim(
        "training_program", {"programa": True, "roles_especializados": True}, confianza=0.6
    ).model_copy(update={"subject_ref": "doc:otra-politica", "locator": Locator(file="otra.md")})

    (result,) = engine.evaluate_only(methodology, [programa, otra], ["CRI-PR-07"])

    assert result.final_score == 100
    assert "se contradice" not in result.explanation
