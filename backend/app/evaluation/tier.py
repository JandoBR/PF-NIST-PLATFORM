"""Estimacion de Tier organizacional (docs/01 §8, reglas T1-T5)."""

from __future__ import annotations

from app.evaluation.schemas import CriterionResult, Estado, TierEstimate
from app.methodology.schemas import TierSettings

_NOMBRES = {1: "Partial", 2: "Risk Informed", 3: "Repeatable", 4: "Adaptive"}
_NIVELES = (("t2", 2), ("t3", 3), ("t4", 4))


def _check_level(
    thresholds: dict[str, float], results_by_id: dict[str, CriterionResult]
) -> tuple[bool, bool, bool, list[str]]:
    """Evalua un nivel de umbrales.

    Retorna (algun_indicador_evaluable, cumple_todos, hay_insuficiente, faltantes).

    Un indicador es *evaluable* solo si su criterio dio puntaje (`evaluado`/`no_implementado`):
    todo criterio tiene siempre un resultado, asi que "existe un resultado" no basta para la regla
    T3 (docs/01 §8.3). Antes se contaba cualquier resultado y "no estimable" era inalcanzable.
    """

    presente = False
    cumple = True
    insuficiente = False
    faltantes: list[str] = []

    for criterion_id, minimo in thresholds.items():
        result = results_by_id.get(criterion_id)
        if result is None:
            cumple = False
            faltantes.append(f"{criterion_id} no evaluado")
            continue

        if result.estado in (Estado.EVIDENCIA_INSUFICIENTE, Estado.ERROR):
            insuficiente = True
            cumple = False
            faltantes.append(f"{criterion_id} con evidencia insuficiente")
        elif result.estado in (Estado.EVALUADO, Estado.NO_IMPLEMENTADO):
            presente = True
            if result.final_score is None or result.final_score < minimo:
                cumple = False
                faltantes.append(f"{criterion_id} = {result.final_score} (< {minimo})")
        else:  # no_aplicable: no puede respaldar un indicador de Tier
            cumple = False
            faltantes.append(f"{criterion_id} no_aplicable")

    return presente, cumple, insuficiente, faltantes


def estimate_tier(tier_settings: TierSettings, results: list[CriterionResult]) -> TierEstimate:
    results_by_id = {r.criterion_id: r for r in results}

    t2_presente, _, _, _ = _check_level(tier_settings.t2, results_by_id)
    if not t2_presente:
        return TierEstimate(
            tier=None,
            nombre=None,
            provisional=False,
            estimable=False,
            justificacion=(
                "No estimable: ningun criterio indicador de Tier 2 tiene evidencia suficiente para"
                " puntuar (T3)."
            ),
            faltantes=[f"{cid} con evidencia insuficiente" for cid in sorted(tier_settings.t2)],
        )

    achieved = 1
    provisional = False
    faltantes: list[str] = []

    for name, level in _NIVELES:
        thresholds = getattr(tier_settings, name)
        _, cumple, insuficiente, nivel_faltantes = _check_level(thresholds, results_by_id)
        if insuficiente:
            provisional = True  # T2
        if cumple:
            achieved = level
        else:
            faltantes = nivel_faltantes
            break

    justificacion = (
        f"Tier {achieved} ({_NOMBRES[achieved]}): mayor nivel cuyos requisitos se cumplen."
    )
    if provisional:
        justificacion += " Marcado provisional: algun indicador tiene evidencia insuficiente (T2)."

    return TierEstimate(
        tier=achieved,
        nombre=_NOMBRES[achieved],
        provisional=provisional,
        estimable=True,
        justificacion=justificacion,
        faltantes=faltantes,
    )
