"""docs/09 §60: silencio documental = evidencia insuficiente (no 0) + hallazgo; citas verificadas;
DE-02 sin eventos evalua lo documental como RC-02."""

from datetime import UTC, datetime

from app.ai.client import FakeAIClient
from app.ai.extraction import CITA_NO_LOCALIZABLE
from app.core import assessment_service as svc
from app.evaluation import engine
from app.evaluation.rules import de02_event_analysis
from app.evaluation.schemas import Estado
from app.recommendations.findings import derive_findings
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(tipo, contenido=None, encontrado=True, limitations=None, cita="x"):
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=2,
        subject_type="document",
        subject_ref="doc:politica",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido or {},
            "encontrado": encontrado,
            "confianza": 0.9,
            "cita": cita,
        },
        source_id="s",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        limitations=limitations,
        created_by="ai:extraction",
    )


def _source_info(archivo="politica.md"):
    return EvidenceInstance(
        type_id="doc.source.info",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope="entorno:produccion",
        value={
            "titulo": "politica",
            "archivo": archivo,
            "secciones": 2,
            "analizadas": 2,
            "omitidas": 0,
            "sin_respuesta": 0,
        },
        source_id="s",
        locator=Locator(file=archivo),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="adapter:documents",
    )


# -- DE-02 como RC-02 ----------------------------------------------------------------------------


def test_de02_without_events_scores_documented_declaration_criteria():
    con_criterios = _claim(
        "process_defined", {"proceso": "analisis incidentes", "criterios_declaracion": True}
    )
    sin_criterios = _claim("process_defined", {"proceso": "analisis incidentes"})

    assert de02_event_analysis.evaluate([con_criterios]).final_score == 75
    assert de02_event_analysis.evaluate([sin_criterios]).final_score == 50
    vacio = de02_event_analysis.evaluate([])
    assert vacio.estado == Estado.EVIDENCIA_INSUFICIENTE


# -- silencio documental -------------------------------------------------------------------------


def test_documents_that_say_nothing_give_insufficient_plus_a_limitation(methodology):
    evidence = [_source_info(), _claim("role_assigned", encontrado=False)]
    results = engine.evaluate_all(methodology, evidence)

    gv02 = next(r for r in results if r.criterion_id == "CRI-GV-02")
    assert gv02.estado == Estado.EVIDENCIA_INSUFICIENTE and gv02.final_score is None
    silencios = [
        f
        for f in derive_findings(methodology, results, evidence)
        if f.titulo == "Ningun documento analizado lo declara"
    ]
    por_criterio = {f.criterion_id: f for f in silencios}
    assert "CRI-GV-02" in por_criterio
    assert "politica.md" in por_criterio["CRI-GV-02"].detalle
    assert "No se toma como un 0" in por_criterio["CRI-GV-02"].detalle
    # Docs/09 §119: la limitacion dice que hacer en los dos casos, con la recomendacion del
    # criterio para cuando la practica no existe.
    detalle = por_criterio["CRI-GV-02"].detalle
    assert "Que hacer: si existe, aporta el documento que lo declare (role_assigned)" in detalle
    recomendacion = methodology.criterios["CRI-GV-02"].recomendacion.rstrip(".")
    assert f"si no existe, {recomendacion[:1].lower()}{recomendacion[1:]}." in detalle
    # RC-03 necesita eventos: su insuficiencia no es silencio de los documentos.
    assert "CRI-RC-03" not in por_criterio


def test_omitting_the_type_and_marking_it_not_found_now_give_the_same_result(methodology):
    """Antes uno daba 0 y el otro insuficiente segun como respondiera el modelo."""

    no_encontrado = _claim("role_assigned", encontrado=False)
    marcado = engine.evaluate_all(methodology, [_source_info(), no_encontrado])
    omitido = engine.evaluate_all(methodology, [_source_info()])

    def gv02(results):
        r = next(x for x in results if x.criterion_id == "CRI-GV-02")
        return r.estado, r.final_score

    assert gv02(marcado) == gv02(omitido) == (Estado.EVIDENCIA_INSUFICIENTE, None)


def test_without_analyzed_documents_there_is_no_silence_finding(methodology):
    results = engine.evaluate_all(methodology, [])

    assert not [
        f for f in derive_findings(methodology, results, []) if "documento" in f.titulo.lower()
    ]


# -- citas no localizables -----------------------------------------------------------------------


def test_an_unverified_quote_is_reported_for_the_criteria_that_wanted_it(methodology):
    inventada = _claim(
        "policy_exists",
        {"nombre": "Politica", "aprobada_por": "Directorio"},
        limitations=CITA_NO_LOCALIZABLE,
        cita="aprobada por el Directorio en 2024",
    )
    results = engine.evaluate_all(methodology, [_source_info(), inventada])

    gv01 = next(r for r in results if r.criterion_id == "CRI-GV-01")
    assert gv01.final_score is None  # no cuenta
    citas = [
        f for f in derive_findings(methodology, results, [inventada]) if f.titulo.startswith("Cita")
    ]
    assert {f.criterion_id for f in citas} >= {"CRI-GV-01"}
    assert all("aprobada por el Directorio en 2024" in f.detalle for f in citas)


def test_end_to_end_a_policy_set_without_roles(db_session, methodology, tmp_path):
    doc = tmp_path / "politica.md"
    doc.write_text("# Politica\nLa politica fue aprobada por la Direccion General.\n")
    cliente = FakeAIClient(
        {
            "Direccion General": {
                "afirmaciones": [
                    {
                        "tipo": "policy_exists",
                        "encontrado": True,
                        "contenido": {"nombre": "Politica", "aprobada_por": "Direccion General"},
                        "cita": {"fragmento": "aprobada por la Direccion General"},
                        "confianza": 0.9,
                    },
                    {"tipo": "role_assigned", "encontrado": False, "confianza": 0.9},
                ]
            }
        }
    )

    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Empresa Silencio",
        scope="entorno:produccion",
        documents_path=doc,
        ai_client=cliente,
    )
    results = {r.criterion_id: r for r in svc.load_criterion_results(db_session, assessment.id)}

    assert results["CRI-GV-01"].final_score == 75  # aprobada, sin revision: la cita si esta
    assert results["CRI-GV-02"].estado == Estado.EVIDENCIA_INSUFICIENTE
    findings = derive_findings(
        methodology, list(results.values()), svc.load_evidence(db_session, assessment.id)
    )
    assert any(
        f.criterion_id == "CRI-GV-02" and f.titulo == "Ningun documento analizado lo declara"
        for f in findings
    )
