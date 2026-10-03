"""Helpers compartidos por las reglas de criterio."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance


def by_type(evidence: list[EvidenceInstance], type_id: str) -> list[EvidenceInstance]:
    return [e for e in evidence if e.type_id == type_id]


def doc_claims(evidence: list[EvidenceInstance], tipo_afirmacion: str) -> list[EvidenceInstance]:
    """`doc.claim` de un `tipo_afirmacion`, excluyendo los de confianza baja (E3, docs/05 §2.3):
    una confianza baja no cuenta como evidencia suficiente."""

    return [
        e
        for e in by_type(evidence, "doc.claim")
        if e.value.get("tipo_afirmacion") == tipo_afirmacion and e.limitations is None
    ]


def best_found_with(claims: list[EvidenceInstance], campo: str) -> EvidenceInstance | None:
    """Como `best_found`, pero solo entre las afirmaciones que traen `contenido[campo]` con algo.

    Una afirmacion encontrada que calla ese dato (p. ej. una `notification_list` sin
    `destinatarios`) no compite con otra que si lo declara, aunque tenga mas confianza: no dice
    algo distinto, no dice nada sobre ese campo."""

    return best_found(
        [c for c in claims if (c.value.get("contenido") or {}).get(campo) not in (None, "", [], {})]
    )


def best_found(claims: list[EvidenceInstance]) -> EvidenceInstance | None:
    """La afirmacion `encontrado=true` con mayor confianza, o `None` si ninguna declara el hecho."""

    encontradas = [c for c in claims if c.value.get("encontrado")]
    if not encontradas:
        return None
    return max(encontradas, key=lambda c: c.value.get("confianza", 0))


def result(
    criterion_id: str,
    estado: Estado,
    score: int | None,
    explanation: str,
    evidence_ids: list[str] | None = None,
) -> CriterionResult:
    """Construye un `CriterionResult`. `criterion_version` lo sobreescribe el motor con la version
    del catalogo (engine._evaluate_one)."""

    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=estado,
        base_score=score,
        final_score=score,
        explanation=explanation,
        evidence_ids=evidence_ids or [],
    )


def noting_unresolved(atributos: set[str]) -> Callable:
    """Decorador de `evaluate`: si el parser dejo expresiones sin resolver sobre los `atributos`
    que decide el criterio, el resultado lo declara como limitacion y cita esa evidencia
    (`tf.expression.unresolved`, docs/02 §4). El puntaje no cambia: se calcula sobre lo resuelto
    y la limitacion queda visible, igual que los recursos `unknown`."""

    def decorator(evaluate: Callable[[list[EvidenceInstance]], CriterionResult]) -> Callable:
        @wraps(evaluate)
        def wrapper(evidence: list[EvidenceInstance]) -> CriterionResult:
            resultado = evaluate(evidence)
            pendientes = [
                e
                for e in by_type(evidence, "tf.expression.unresolved")
                if e.value["atributo"] in atributos
            ]
            if not pendientes or resultado.estado == Estado.NO_APLICABLE:
                return resultado
            detalle = ", ".join(
                sorted({f"{e.value['recurso']}.{e.value['atributo']}" for e in pendientes})
            )
            return resultado.model_copy(
                update={
                    "explanation": (
                        f"{resultado.explanation} Limitacion: {len(pendientes)} expresion(es) sin"
                        f" resolver ({detalle}); el puntaje solo refleja lo resuelto."
                    ),
                    "evidence_ids": [*resultado.evidence_ids, *(e.id for e in pendientes)],
                }
            )

        return wrapper

    return decorator
