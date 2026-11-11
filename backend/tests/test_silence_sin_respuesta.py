"""docs/09 §100: un silencio por secciones sin respuesta de la IA no es silencio del documento.

`respuesta_vacia` en un chunk hacia que la regla concluyera "los documentos no lo declaran", que es
una afirmacion sobre el texto que nadie leyo. El motor ahora lo distingue y el hallazgo lo dice.
"""

from datetime import UTC, datetime

from app.evaluation import engine
from app.evaluation.schemas import Estado
from app.recommendations.findings import derive_findings
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(tipo, encontrado=False):
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=2,
        subject_type="document",
        subject_ref="doc:politica",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": tipo,
            "contenido": {},
            "encontrado": encontrado,
            "confianza": 0.9,
            "cita": "x",
        },
        source_id="s",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


def _source_info(archivo="politica.md", secciones=2, sin_respuesta=0):
    return EvidenceInstance(
        type_id="doc.source.info",
        type_version=1,
        subject_type="document",
        subject_ref=f"doc:{archivo.removesuffix('.md')}",
        scope="entorno:produccion",
        value={
            "titulo": archivo.removesuffix(".md"),
            "archivo": archivo,
            "secciones": secciones,
            "analizadas": secciones - sin_respuesta,
            "omitidas": 0,
            "sin_respuesta": sin_respuesta,
        },
        source_id="s",
        locator=Locator(file=archivo),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="adapter:documents",
    )


def _gv02(results):
    return next(r for r in results if r.criterion_id == "CRI-GV-02")


def test_silence_from_unanswered_sections_is_insufficient_evidence_with_the_limitation(methodology):
    evidence = [_source_info(sin_respuesta=2), _claim("role_assigned")]
    resultado = _gv02(engine.evaluate_all(methodology, evidence))

    assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert resultado.final_score is None
    assert "la IA no respondio para 2 seccion(es) de politica.md" in resultado.explanation
    assert "no es silencio del documento" in resultado.explanation


def test_the_limitation_becomes_a_finding_that_does_not_blame_the_documents(methodology):
    evidence = [
        _source_info(archivo="continuidad.md", secciones=4, sin_respuesta=2),
        _claim("role_assigned"),
    ]
    results = engine.evaluate_all(methodology, evidence)

    hallazgos = [
        f for f in derive_findings(methodology, results, evidence) if f.criterion_id == "CRI-GV-02"
    ]
    limitacion = next(f for f in hallazgos if f.tipo == "limitacion")
    assert limitacion.titulo == "La IA no respondio para parte de los documentos"
    assert "2 seccion(es) de continuidad.md" in limitacion.detalle
    assert "no se cuenta como ausencia" in limitacion.detalle
    assert not any(f.titulo == "Ningun documento analizado lo declara" for f in hallazgos)


def test_without_unanswered_sections_the_silence_finding_is_unchanged(methodology):
    evidence = [_source_info(sin_respuesta=0), _claim("role_assigned")]
    results = engine.evaluate_all(methodology, evidence)

    hallazgos = [
        f for f in derive_findings(methodology, results, evidence) if f.criterion_id == "CRI-GV-02"
    ]
    assert [f.titulo for f in hallazgos] == ["Ningun documento analizado lo declara"]
