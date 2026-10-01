"""U3 — contenido narrativo de un plan de mejora (docs/05 §4).

Si la IA no esta disponible o responde algo invalido, no se bloquea el plan: se usa la
plantilla de recomendacion del criterio como paso unico (mismo principio de degradacion que
U1/U2, docs/05 §7). `generate_plan_content` nunca lanza; devuelve contenido siempre.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.ai.client import AIClient
from app.ai.schemas import PlanContentResponse
from app.methodology.schemas import CriterionDefinition

PROMPT_VERSION = "plan_v1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_prompt(
    criterion: CriterionDefinition, severidad: str, score: float, evidence_ids: list[str]
) -> str:
    payload = {
        "criterio": {"id": criterion.id, "titulo": criterion.titulo},
        "plantilla_recomendacion": criterion.recomendacion,
        "hallazgo": {"severidad": severidad, "score": score, "evidence_ids": evidence_ids},
    }
    return json.dumps(payload, ensure_ascii=False)


def _template_fallback(criterion: CriterionDefinition) -> PlanContentResponse:
    return PlanContentResponse(
        titulo=f"Corregir: {criterion.titulo}",
        objetivo=criterion.recomendacion,
        pasos=[criterion.recomendacion],
        verificacion=f"Reevaluar {criterion.id} y confirmar que supera el umbral de brecha.",
        dependencias=[],
    )


def generate_plan_content(
    client: AIClient,
    criterion: CriterionDefinition,
    *,
    severidad: str,
    score: float,
    evidence_ids: list[str],
) -> PlanContentResponse:
    """Nunca devuelve None: degrada a la plantilla del criterio si la IA no es usable."""

    user_prompt = _build_user_prompt(criterion, severidad, score, evidence_ids)
    raw = client.complete_json(_SYSTEM_PROMPT, user_prompt)
    if raw is None:
        return _template_fallback(criterion)

    try:
        return PlanContentResponse.model_validate(raw)
    except ValidationError:
        return _template_fallback(criterion)
