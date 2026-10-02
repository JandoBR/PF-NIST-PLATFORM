"""TS-02: el arnes de evaluacion de U1 (docs/05 §8) mide bien recall, invenciones y citas.

No llama a ninguna IA real: un cliente "oraculo" responde con la propia anotacion (la respuesta
perfecta) y variantes rotas comprueban que cada metrica detecta su fallo. La corrida contra el
modelo real es `python -m app.main eval-ai` (cuesta dinero).
"""

import re
from pathlib import Path

import pytest

from app.ai.client import NullAIClient
from app.ai.golden_eval import (
    _matches,
    _norm,
    evaluate_extraction,
    format_report,
    load_expected,
)
from app.methodology.loader import load_methodology

GOLDEN_DIR = Path(__file__).resolve().parent / "golden_ai"
METHODOLOGY_DIR = Path(__file__).resolve().parent.parent / "methodology"
_DOC_BLOCK = re.compile(r"<documento id=\"[^\"]*\">\n(.*)\n</documento>", re.DOTALL)


@pytest.fixture(scope="module")
def methodology():
    return load_methodology(METHODOLOGY_DIR)


class OracleClient:
    """Responde, para cada fragmento, las afirmaciones anotadas cuya cita esta en el. `mutate`
    permite degradar la respuesta perfecta para probar las metricas."""

    def __init__(self, mutate=None):
        self._expected = [c for claims in load_expected(GOLDEN_DIR).values() for c in claims]
        self._mutate = mutate or (lambda afirmaciones, texto: afirmaciones)

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        texto = _DOC_BLOCK.search(user_prompt).group(1)
        afirmaciones = [
            {
                "tipo": c.tipo,
                "encontrado": True,
                "contenido": c.contenido,
                "cita": {"fragmento": c.cita},
                "confianza": 0.9,
            }
            for c in self._expected
            if _norm(c.cita) in _norm(texto)
        ]
        return {"afirmaciones": self._mutate(afirmaciones, texto)}


def test_annotations_are_consistent_with_the_documents(methodology):
    """La anotacion es la verdad del golden set: sus citas existen y sus tipos son validos."""

    tipos = set(methodology.tipos_afirmacion_requeridos())
    for nombre, claims in load_expected(GOLDEN_DIR).items():
        texto = _norm((GOLDEN_DIR / "documents" / nombre).read_text(encoding="utf-8"))
        for claim in claims:
            assert claim.tipo in tipos, f"{nombre}: tipo desconocido {claim.tipo}"
            assert _norm(claim.cita) in texto, f"{nombre}: la cita no esta en el documento"


def test_golden_set_covers_abstention_and_injection():
    expected = load_expected(GOLDEN_DIR)
    vacios = [n for n, claims in expected.items() if not claims]
    assert "manual-operaciones.md" in vacios and "memo-con-instrucciones.md" in vacios
    assert sum(len(c) for c in expected.values()) >= 10


def test_perfect_extraction_passes(methodology):
    report = evaluate_extraction(OracleClient(), methodology, GOLDEN_DIR)
    assert report.recall == 1.0 and report.invenciones == 0 and report.citation_rate == 1.0
    assert report.llamadas_degradadas == 0
    assert report.passed
    assert "APROBADO" in format_report(report)


def test_missing_claims_lower_recall_and_fail(methodology):
    def omite_todo_menos_uno(afirmaciones, _texto):
        es_politica = afirmaciones and afirmaciones[0]["tipo"] == "policy_exists"
        return afirmaciones[:1] if es_politica else []

    report = evaluate_extraction(OracleClient(omite_todo_menos_uno), methodology, GOLDEN_DIR)
    assert report.recall < 0.9 and not report.passed
    assert any(d.faltantes for d in report.documentos)
    assert "NO APROBADO" in format_report(report)


def test_recall_above_threshold_tolerates_a_miss(methodology):
    omitida = []

    def omite_la_primera(afirmaciones, _texto):
        if not omitida and afirmaciones:
            omitida.append(afirmaciones[0]["tipo"])
            return afirmaciones[1:]
        return afirmaciones

    total = sum(len(c) for c in load_expected(GOLDEN_DIR).values())
    report = evaluate_extraction(OracleClient(omite_la_primera), methodology, GOLDEN_DIR)
    assert report.encontradas == total - 1
    assert report.recall == (total - 1) / total
    assert report.passed == (report.recall >= 0.9)


def test_claim_in_a_document_without_information_is_an_invention(methodology):
    """Abstencion: el manual no tiene politica; afirmarla es inventar."""

    def inventa(afirmaciones, texto):
        if "Manual de Operaciones" in texto:
            return [
                *afirmaciones,
                {
                    "tipo": "policy_exists",
                    "encontrado": True,
                    "contenido": {"nombre": "Politica", "aprobada_por": "Direccion"},
                    "cita": {"fragmento": "No contiene politicas de seguridad"},
                    "confianza": 0.9,
                },
            ]
        return afirmaciones

    report = evaluate_extraction(OracleClient(inventa), methodology, GOLDEN_DIR)
    manual = next(d for d in report.documentos if d.documento == "manual-operaciones.md")
    assert len(manual.invenciones) == 1
    assert report.invenciones == 1 and not report.passed


def test_obeying_an_instruction_inside_the_document_is_an_invention(methodology):
    def obedece(afirmaciones, texto):
        if "Ignora las instrucciones" in texto:
            return [
                {
                    "tipo": "backup_policy",
                    "encontrado": True,
                    "contenido": {"respaldo": True, "retencion": "1 ano"},
                    "cita": {"fragmento": "respaldos diarios con retencion de un ano"},
                    "confianza": 0.9,
                }
            ]
        return afirmaciones

    report = evaluate_extraction(OracleClient(obedece), methodology, GOLDEN_DIR)
    memo = next(d for d in report.documentos if d.documento == "memo-con-instrucciones.md")
    assert len(memo.invenciones) == 1 and not report.passed


def test_wrong_content_is_a_miss_and_an_invention(methodology):
    def retencion_equivocada(afirmaciones, _texto):
        for a in afirmaciones:
            if a["tipo"] == "backup_policy":
                a["contenido"] = {**a["contenido"], "retencion": "7 dias"}
        return afirmaciones

    report = evaluate_extraction(OracleClient(retencion_equivocada), methodology, GOLDEN_DIR)
    doc = next(d for d in report.documentos if d.documento == "continuidad-y-respaldos.md")
    assert any("backup_policy" in f for f in doc.faltantes)
    assert any("backup_policy" in i for i in doc.invenciones)


def test_fabricated_citation_is_not_locatable(methodology):
    def cita_falsa(afirmaciones, _texto):
        for a in afirmaciones:
            if a["tipo"] == "policy_review":
                a["cita"] = {"fragmento": "se revisa cada dos anos segun el comite"}
        return afirmaciones

    report = evaluate_extraction(OracleClient(cita_falsa), methodology, GOLDEN_DIR)
    assert report.citation_rate < 1.0 and not report.passed
    assert "cita no localizable" in format_report(report)


def test_degraded_ai_reports_it_instead_of_crashing(methodology):
    report = evaluate_extraction(NullAIClient(), methodology, GOLDEN_DIR)
    assert report.recall == 0.0 and not report.passed
    assert report.llamadas > 0 and report.llamadas_degradadas == report.llamadas
    assert "degradadas" in format_report(report)


def test_content_matching_rules():
    assert _matches({"retencion": "30"}, {"retencion": "30 dias", "otro": 1})
    assert _matches("Direccion General", "la DIRECCIÓN  general")
    assert not _matches({"respaldo": True}, {"respaldo": False})
    assert _matches(["CISO", "area legal"], ["El CISO", "Area legal", "Otros"])
    assert not _matches(["CISO", "auditoria"], ["CISO"])
    assert _matches({"roles": [{"rol": "Jefe"}]}, {"roles": [{"rol": "Jefe de TI", "x": 1}]})
    assert not _matches({"falta": "x"}, {"otra": "x"})

