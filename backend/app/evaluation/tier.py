"""Estimacion de Tier organizacional (docs/01 §8, reglas T1-T7)."""

from __future__ import annotations

from typing import NamedTuple

from app.evaluation.schemas import CriterionResult, Estado, SiguienteNivel, TierEstimate
from app.methodology.schemas import TierSettings

_NOMBRES = {1: "Partial", 2: "Risk Informed", 3: "Repeatable", 4: "Adaptive"}
_NIVELES = (("t2", 2), ("t3", 3), ("t4", 4))


class _Nivel(NamedTuple):
    """Clasificacion de los requisitos de un nivel de Tier (docs/01 §8.3)."""

    presente: bool
    cumple: bool
    insuficiente: bool
    faltantes: list[str]
    desconocidos: list[str]
    fallidos: list[str]
    cumplidos: int


def _evaluar_nivel(
    thresholds: dict[str, float], results_by_id: dict[str, CriterionResult]
) -> _Nivel:
    """Evalua un nivel de umbrales.

    Un indicador es *evaluable* solo si su criterio dio puntaje (`evaluado`/`no_implementado`):
    todo criterio tiene siempre un resultado, asi que "existe un resultado" no basta para la regla
    T3 (docs/01 §8.3). Un criterio sin resultado en `results_by_id` cuenta como desconocido, nunca
    como falla.
    """

    presente = False
    faltantes: list[str] = []
    desconocidos: list[str] = []
    fallidos: list[str] = []
    cumplidos = 0

    for criterion_id, minimo in thresholds.items():
        result = results_by_id.get(criterion_id)
        if result is None:
            faltantes.append(f"{criterion_id} no evaluado")
            desconocidos.append(criterion_id)
            continue

        if result.estado in (Estado.EVIDENCIA_INSUFICIENTE, Estado.ERROR):
            faltantes.append(f"{criterion_id} con evidencia insuficiente")
            desconocidos.append(criterion_id)
        elif result.estado in (Estado.EVALUADO, Estado.NO_IMPLEMENTADO):
            presente = True
            if result.final_score is None or result.final_score < minimo:
                faltantes.append(f"{criterion_id} = {result.final_score} (< {minimo})")
                fallidos.append(f"{criterion_id} por debajo de {minimo:g}")
            else:
                cumplidos += 1
        else:  # no_aplicable: no puede respaldar un indicador de Tier
            faltantes.append(f"{criterion_id} no_aplicable")
            fallidos.append(f"{criterion_id} no_aplicable")

    return _Nivel(
        presente=presente,
        cumple=cumplidos == len(thresholds),
        insuficiente=bool(desconocidos),
        faltantes=faltantes,
        desconocidos=desconocidos,
        fallidos=fallidos,
        cumplidos=cumplidos,
    )


def _umbrales_hasta(tier_settings: TierSettings, techo: int) -> dict[str, float]:
    """Union de umbrales de los niveles 2..techo; si un criterio se repite, manda el mayor."""

    umbrales: dict[str, float] = {}
    for name, level in _NIVELES:
        if level > techo:
            break
        for criterion_id, minimo in getattr(tier_settings, name).items():
            umbrales[criterion_id] = max(minimo, umbrales.get(criterion_id, minimo))
    return umbrales


def _calcular_techo(
    tier_settings: TierSettings, results_by_id: dict[str, CriterionResult]
) -> tuple[int, list[str], list[str]]:
    """Mayor nivel alcanzable si los requisitos desconocidos se cumplieran (T7).

    Recorre los niveles en orden acumulando sus requisitos: el primer nivel con una falla real
    corta el techo. Un requisito desconocido no corta el techo, solo impide confirmarlo.

    Retorna (techo, criterios_desconocidos_hasta_el_techo, fallas_que_cortaron).
    """

    techo = 1
    fallidos: list[str] = []
    for _name, level in _NIVELES:
        nivel = _evaluar_nivel(_umbrales_hasta(tier_settings, level), results_by_id)
        if nivel.fallidos:
            fallidos = nivel.fallidos
            break
        techo = level

    umbrales = _umbrales_hasta(tier_settings, techo)
    desconocidos = sorted(
        criterion_id
        for criterion_id in umbrales
        if (result := results_by_id.get(criterion_id)) is None
        or result.estado in (Estado.EVIDENCIA_INSUFICIENTE, Estado.ERROR)
    )
    return techo, desconocidos, fallidos


def estimate_tier(tier_settings: TierSettings, results: list[CriterionResult]) -> TierEstimate:
    results_by_id = {r.criterion_id: r for r in results}

    t2 = _evaluar_nivel(tier_settings.t2, results_by_id)
    if not t2.presente:
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
        nivel = _evaluar_nivel(thresholds, results_by_id)
        if nivel.insuficiente:
            provisional = True  # T2
        if nivel.cumple:
            achieved = level
        else:
            faltantes = nivel.faltantes
            break

    techo, faltan_para_techo, fallidos_techo = _calcular_techo(tier_settings, results_by_id)
    siguiente_nivel: SiguienteNivel | None = None
    if achieved < 4:
        thresholds = getattr(tier_settings, f"t{achieved + 1}")
        nivel = _evaluar_nivel(thresholds, results_by_id)
        siguiente_nivel = SiguienteNivel(
            nivel=achieved + 1, cumplidos=nivel.cumplidos, total=len(thresholds)
        )

    if techo > achieved:
        umbrales = _umbrales_hasta(tier_settings, techo)
        detalle = " y ".join(
            f"{criterion_id} llegara a {umbrales[criterion_id]:g}"
            for criterion_id in faltan_para_techo
        )
        justificacion = (
            f"Tier {achieved} ({_NOMBRES[achieved]}) confirmado; hasta Tier {techo} si {detalle}"
            " (sin evidencia suficiente)."
        )
    else:
        justificacion = (
            f"Tier {achieved} ({_NOMBRES[achieved]}): mayor nivel cuyos requisitos se cumplen."
        )
        if provisional:
            justificacion += (
                " Marcado provisional: algun indicador tiene evidencia insuficiente (T2)."
            )
        if achieved < 4 and fallidos_techo:
            justificacion += (
                " El siguiente nivel no es alcanzable: " + "; ".join(fallidos_techo) + "."
            )

    return TierEstimate(
        tier=achieved,
        nombre=_NOMBRES[achieved],
        provisional=provisional,
        estimable=True,
        justificacion=justificacion,
        faltantes=faltantes,
        techo=techo,
        faltan_para_techo=faltan_para_techo,
        siguiente_nivel=siguiente_nivel,
    )
