"""Presenta lo que el analisis no pudo determinar como hallazgos `limitacion` (docs/11 OP-04).

Hasta ahora esa informacion solo estaba en la explicacion de cada criterio (CR-06). Un hallazgo
`limitacion` no puntua, no genera plan y no es una brecha: dice **que parte del resultado hay que
leer con cautela** y por que (una expresion que el parser no resolvio, un recurso con estado
desconocido, documentos analizados que no dicen lo que el criterio necesita, una cita que no esta en
el texto). Se deriva de la evidencia que el propio criterio cito o pidio.
"""

from __future__ import annotations

from app.ai.extraction import CITA_NO_LOCALIZABLE
from app.evaluation.rules._common import SILENCIO_DOCUMENTAL
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import Methodology
from app.recommendations.findings import Finding
from app.schemas.evidence import EvidenceInstance

#: Una limitacion no es una gravedad del sistema evaluado, sino de la certeza del analisis.
SEVERIDAD = "baja"


def detect_limitations(
    methodology: Methodology, results: list[CriterionResult], evidence: list[EvidenceInstance]
) -> list[Finding]:
    """Un hallazgo por (criterio, evidencia limitante): la misma expresion sin resolver afecta a
    cada criterio que la cito, y cada uno la lee distinto."""

    by_id = {e.id: e for e in evidence}
    findings: list[Finding] = []
    for result in results:
        criterio = methodology.criterios.get(result.criterion_id)
        nombre = criterio.titulo if criterio else result.criterion_id
        citadas = [by_id[i] for i in dict.fromkeys(result.evidence_ids) if i in by_id]
        # Un recurso desconocido *porque* una expresion no se resolvio ya queda explicado por esa
        # expresion: repetirlo como "estado desconocido" seria ruido.
        con_expresion = {
            e.value["recurso"] for e in citadas if e.type_id == "tf.expression.unresolved"
        }
        for item in citadas:
            if item is None:
                continue
            if item.type_id == "tf.expression.unresolved":
                value = item.value
                titulo = f"{value['recurso']}.{value['atributo']} sin resolver"
                detalle = (
                    f"Expresion `{value['expresion']}`: {value['motivo']}. "
                    f"El puntaje de «{nombre}» solo refleja lo que si se pudo resolver."
                )
            elif (
                item.type_id.startswith("tf.")
                and isinstance(item.value, dict)
                and item.value.get("estado") == "unknown"
                and item.subject_ref not in con_expresion
            ):
                titulo = f"{item.subject_ref}: estado desconocido"
                detalle = (
                    f"El valor no esta declarado de forma determinista en el archivo. "
                    f"«{nombre}» no lo cuenta como cumplido ni como incumplido."
                )
            else:
                continue
            findings.append(
                Finding(
                    criterion_id=result.criterion_id,
                    titulo=titulo,
                    tipo="limitacion",
                    severidad=SEVERIDAD,
                    score=None,
                    detalle=detalle,
                    evidence_ids=[item.id],
                )
            )
    return findings


def _documentos_analizados(evidence: list[EvidenceInstance]) -> list[str]:
    return [
        e.value["archivo"]
        for e in evidence
        if e.type_id == "doc.source.info" and e.value.get("analizadas", 0) > 0
    ]


def _es_documental(criterio) -> bool:
    return bool(criterio.evidencias) and all(
        ev.startswith("doc.claim") for ev in criterio.evidencias
    )


def detect_document_silence(
    methodology: Methodology, results: list[CriterionResult], evidence: list[EvidenceInstance]
) -> list[Finding]:
    """Criterios sin evidencia aunque se analizaron documentos (docs/09 §60). El resultado es
    `evidencia_insuficiente`, no 0: esto lo hace visible para que no se lea como "no se miro"."""

    documentos = _documentos_analizados(evidence)
    if not documentos:
        return []
    findings: list[Finding] = []
    for result in results:
        if result.estado != Estado.EVIDENCIA_INSUFICIENTE:
            continue
        criterio = methodology.criterios.get(result.criterion_id)
        if criterio is None:
            continue
        # La regla dijo explicitamente que los documentos callan, o el criterio es solo
        # documental y no tuvo nada (el modelo ni siquiera marco el tipo como no encontrado).
        if not (result.explanation.endswith(SILENCIO_DOCUMENTAL) or _es_documental(criterio)):
            continue
        tipos = ", ".join(criterio.regla.get("tipos_afirmacion", [])) or "afirmaciones documentales"
        findings.append(
            Finding(
                criterion_id=result.criterion_id,
                titulo="Ningun documento analizado lo declara",
                tipo="limitacion",
                severidad=SEVERIDAD,
                score=None,
                detalle=(
                    f"Se analizaron {len(documentos)} documento(s) ({', '.join(documentos)}) y"
                    f" ninguno declara lo que «{criterio.titulo}» necesita ({tipos}). No se toma"
                    " como un 0: puede que el documento correspondiente no se haya aportado."
                ),
                evidence_ids=list(result.evidence_ids),
            )
        )
    return findings


def detect_unverified_quotes(
    methodology: Methodology, evidence: list[EvidenceInstance]
) -> list[Finding]:
    """Afirmaciones descartadas porque su cita no aparece en el texto (E8, docs/09 §60)."""

    findings: list[Finding] = []
    for item in evidence:
        if item.type_id != "doc.claim" or CITA_NO_LOCALIZABLE not in (item.limitations or ""):
            continue
        tipo = item.value.get("tipo_afirmacion")
        for criterio in methodology.criterios.values():
            if tipo not in criterio.regla.get("tipos_afirmacion", []):
                continue
            findings.append(
                Finding(
                    criterion_id=criterio.id,
                    titulo=f"Cita no localizable ({tipo})",
                    tipo="limitacion",
                    severidad=SEVERIDAD,
                    score=None,
                    detalle=(
                        f"La IA cito «{item.value.get('cita')}» de {item.subject_ref}, pero ese"
                        " texto no aparece en el documento: la afirmacion se guarda pero no"
                        f" cuenta para «{criterio.titulo}»."
                    ),
                    evidence_ids=[item.id],
                )
            )
    return findings
