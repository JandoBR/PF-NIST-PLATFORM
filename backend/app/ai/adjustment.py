"""U2 — ajuste contextual acotado (docs/05 §3, docs/01 §5).

El motor calcula `B` (determinista); esto propone `A`, lo acota a `[B-D, B+D]` y mezcla con
`alpha` para obtener `S`. Nunca cambia evidencia ni estados (R3), nunca sube un criterio
`evidencia_insuficiente` (R4/J3), y una respuesta invalida/vacia degrada a `S = B` en vez de
fallar (R5/J4) — el mismo principio de "si la IA desaparece, el sistema sigue funcionando"
que ya aplica a la extraccion documental (docs/05 §7).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.ai.calllog import call_context
from app.ai.client import AIClient
from app.ai.schemas import AdjustmentResponse
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.schemas import CriterionDefinition
from app.schemas.evidence import EvidenceInstance

PROMPT_VERSION = "adjust_v1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

#: Solo estos estados admiten ajuste (J1 ya lo acota por criterio; esto acota por resultado,
#: docs/01 §5.3 R4: evidencia_insuficiente/error nunca se tocan).
_ADJUSTABLE_STATES = (Estado.EVALUADO, Estado.NO_IMPLEMENTADO)


def _build_user_prompt(
    criterion: CriterionDefinition,
    result: CriterionResult,
    evidence_by_id: dict[str, EvidenceInstance],
    context: dict[str, Any],
    divergencia_maxima: float,
) -> str:
    evidencias = [
        {
            "id": eid,
            "tipo": evidence_by_id[eid].type_id,
            "valor": evidence_by_id[eid].value,
            "limitaciones": evidence_by_id[eid].limitations,
        }
        for eid in result.evidence_ids
        if eid in evidence_by_id
    ]
    payload = {
        "criterion": {"id": criterion.id, "titulo": criterion.titulo, "regla": criterion.regla},
        "base_score": result.base_score,
        "estado": result.estado.value,
        "evidencias": evidencias,
        "contexto": context,
        "margen_maximo": divergencia_maxima,
    }
    return json.dumps(payload, ensure_ascii=False)


def _degraded(result: CriterionResult) -> CriterionResult:
    return result.model_copy(update={"degradado": True})


def is_adjustable(criterion: CriterionDefinition, result: CriterionResult) -> bool:
    """Si `adjust` llamaria a la IA para este resultado (J1/R4): ajustable, estado que lo admite
    y con puntaje base."""

    return (
        criterion.ai_adjustable
        and result.estado in _ADJUSTABLE_STATES
        and result.base_score is not None
    )


def adjust(
    client: AIClient,
    criterion: CriterionDefinition,
    result: CriterionResult,
    evidence_by_id: dict[str, EvidenceInstance],
    context: dict[str, Any],
    alpha: float,
    divergencia_maxima: float,
) -> CriterionResult:
    """Devuelve un `CriterionResult` nuevo; `base_score` nunca cambia.

    No intenta ajustar en absoluto (ni marca `degradado`) cuando el criterio no es
    `ai_adjustable` o el estado no lo admite: eso no es un fallo de IA, es la regla J1/R4.
    """

    if not is_adjustable(criterion, result):
        return result
    assert result.base_score is not None

    user_prompt = _build_user_prompt(criterion, result, evidence_by_id, context, divergencia_maxima)
    with call_context(paso="U2", prompt_version=PROMPT_VERSION, criterion_id=criterion.id):
        raw = client.complete_json(_SYSTEM_PROMPT, user_prompt)
    if raw is None:
        return _degraded(result)

    try:
        parsed = AdjustmentResponse.model_validate(raw)
    except ValidationError:
        return _degraded(result)

    if not parsed.evidencias_referenciadas:
        return _degraded(result)  # J5: la justificacion debe citar evidencia existente
    if any(eid not in evidence_by_id for eid in parsed.evidencias_referenciadas):
        return _degraded(result)  # evidencia inventada: no existe en lo que se le dio a la IA

    propuesto = parsed.puntaje_propuesto
    if result.estado == Estado.NO_IMPLEMENTADO and propuesto > result.base_score:
        propuesto = result.base_score  # J2: no_implementado nunca se ajusta hacia arriba

    b, d = result.base_score, divergencia_maxima
    a_acotado = min(max(propuesto, b - d), b + d)
    s = round(min(max((1 - alpha) * b + alpha * a_acotado, 0), 100))

    # J7: el ajuste se registra siempre, incluso sin cambio neto en el puntaje.
    if s == b:
        nota = f"Ajuste contextual evaluado, sin cambio ({parsed.justificacion})"
    else:
        signo = "+" if s > b else ""
        nota = f"Ajuste contextual: {signo}{s - b:g} ({parsed.justificacion})"

    return result.model_copy(
        update={"final_score": float(s), "explanation": f"{result.explanation} {nota}"}
    )
