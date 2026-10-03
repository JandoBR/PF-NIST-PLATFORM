"""Presenta lo que el analisis no pudo determinar como hallazgos `limitacion` (docs/11 OP-04).

Hasta ahora esa informacion solo estaba en la explicacion de cada criterio (CR-06). Un hallazgo
`limitacion` no puntua, no genera plan y no es una brecha: dice **que parte del resultado hay que
leer con cautela** y por que (una expresion que el parser no resolvio, un recurso con estado
desconocido). Se deriva de la evidencia que el propio criterio cito.
"""

from __future__ import annotations

from app.evaluation.schemas import CriterionResult
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
