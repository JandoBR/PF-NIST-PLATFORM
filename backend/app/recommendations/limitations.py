"""Presenta lo que el analisis no pudo determinar como hallazgos `limitacion` (docs/11 OP-04).

Hasta ahora esa informacion solo estaba en la explicacion de cada criterio (CR-06). Un hallazgo
`limitacion` no puntua, no genera plan y no es una brecha: dice **que parte del resultado hay que
leer con cautela** y por que (una expresion que el parser no resolvio, un recurso con estado
desconocido, documentos analizados que no dicen lo que el criterio necesita, una cita que no esta en
el texto). Se deriva de la evidencia que el propio criterio cito o pidio.
"""

from __future__ import annotations

from app.ai.extraction import CITA_NO_LOCALIZABLE
from app.evaluation.rules._common import (
    AVISO_SIN_RESPUESTA,
    contradicciones_booleanas,
    documentos_sin_respuesta,
    es_silencio_documental,
)
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


def que_hacer_si_calla(criterio, tipos: str) -> str:
    """Accion para un criterio en silencio documental (docs/09 §119): sin saber si la practica
    existe, se ofrecen los dos caminos. La segunda parte es la `recomendacion` del criterio."""

    recomendacion = criterio.recomendacion.strip().rstrip(".")
    recomendacion = recomendacion[:1].lower() + recomendacion[1:]
    return (
        f"Que hacer: si existe, aporta el documento que lo declare ({tipos}) y vuelve a evaluar;"
        f" si no existe, {recomendacion}."
    )


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
    pendientes = documentos_sin_respuesta(evidence)
    findings: list[Finding] = []
    for result in results:
        if result.estado != Estado.EVIDENCIA_INSUFICIENTE:
            continue
        criterio = methodology.criterios.get(result.criterion_id)
        if criterio is None:
            continue
        # La regla dijo explicitamente que los documentos callan, o el criterio es solo
        # documental y no tuvo nada (el modelo ni siquiera marco el tipo como no encontrado).
        if not (es_silencio_documental(result) or _es_documental(criterio)):
            continue
        tipos = ", ".join(criterio.regla.get("tipos_afirmacion", [])) or "afirmaciones documentales"
        if AVISO_SIN_RESPUESTA in result.explanation and pendientes:
            # La IA dejo secciones sin responder (docs/09 §100): el hallazgo no puede decir que
            # ningun documento lo declara, porque parte del texto no se llego a leer.
            findings.append(
                Finding(
                    criterion_id=result.criterion_id,
                    titulo="La IA no respondio para parte de los documentos",
                    tipo="limitacion",
                    severidad=SEVERIDAD,
                    score=None,
                    detalle=(
                        f"La IA no respondio para {sum(n for _, n in pendientes)} seccion(es) de"
                        f" {', '.join(a for a, _ in pendientes)}. Sin esa lectura"
                        f" «{criterio.titulo}» queda en evidencia insuficiente: lo que no se pudo"
                        f" leer ({tipos}) no se cuenta como ausencia ni como 0."
                    ),
                    evidence_ids=list(result.evidence_ids),
                )
            )
            continue
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
                    " como un 0: puede que el documento correspondiente no se haya aportado. "
                    + que_hacer_si_calla(criterio, tipos)
                ),
                evidence_ids=list(result.evidence_ids),
            )
        )
    return findings


def detect_document_conflicts(
    results: list[CriterionResult], evidence: list[EvidenceInstance]
) -> list[Finding]:
    """Documentos que se contradicen sobre un booleano que el criterio uso (docs/09 §101).

    A diferencia de `contradictions.py`, el choque no es entre fuentes distintas sino entre
    fragmentos del mismo documento. No invalida la afirmacion: la regla ya resolvio con el valor de
    la mas confiable. El hallazgo deja visible que ese valor podia ser el opuesto."""

    conflictos = contradicciones_booleanas(evidence)
    findings: list[Finding] = []
    for result in results:
        citados = set(result.evidence_ids)
        for conflicto in conflictos:
            if not citados.intersection(conflicto.claim_ids):
                continue
            valor = "si" if conflicto.valor else "no"
            findings.append(
                Finding(
                    criterion_id=result.criterion_id,
                    titulo=(
                        f"El documento {conflicto.archivo} se contradice sobre {conflicto.campo}"
                    ),
                    tipo="limitacion",
                    severidad=SEVERIDAD,
                    score=None,
                    detalle=(
                        f"El documento {conflicto.archivo} declara y niega «{conflicto.campo}» en"
                        f" fragmentos distintos. Se usa el valor de la afirmacion mas confiable"
                        f" ({valor}); el fragmento que dice lo contrario no se suma."
                    ),
                    evidence_ids=list(conflicto.claim_ids),
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
