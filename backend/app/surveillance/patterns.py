"""Deteccion de patrones sobre una ventana de eventos (docs/06 §3).

Simplificado a proposito: cada llamada a `load_events_jsonl` + `detect_patterns` trata el lote
ingerido completo como UNA ventana completa (`log.window.completo = True`). Un stream continuo
real con ventanas deslizantes e ingesta parcial es evolucion futura (docs/08 §11); el contrato
de evidencia (`log.window`) ya distingue completo/incompleto para cuando eso exista.

`recovery_communicated` se agrega como siente patron (existencia simple) aunque docs/06 §3 no lo
lista entre los "patrones iniciales": CRI-RC-03 y el disparador D5 (docs/08 §5) lo necesitan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.methodology.schemas import VigilanciaSettings
from app.surveillance.events import RawEvent

#: Patrones de existencia simple: "presente" si hay >=1 evento de ese tipo en la ventana.
_EXISTENCE_PATTERNS = (
    "alert_raised",
    "incident_declared",
    "escalation_done",
    "restore_exercise_run",
    "restore_verified",
    "recovery_communicated",
)


@dataclass(frozen=True)
class PatternMatch:
    patron: str
    resultado: str
    desde: datetime
    hasta: datetime
    conteo: int
    event_ids: list[str]


def _auth_failures_burst(
    events: list[RawEvent], settings: VigilanciaSettings
) -> PatternMatch | None:
    fallos = [e for e in events if e.tipo == "auth_failure"]
    if not fallos:
        return None

    grupos: dict[tuple[str | None, str], list[RawEvent]] = {}
    for evento in fallos:
        grupos.setdefault((evento.actor, evento.recurso), []).append(evento)

    umbral = settings.auth_failures_burst
    for grupo in grupos.values():
        if len(grupo) < umbral.n:
            continue
        desde, hasta = grupo[0].event_time, grupo[-1].event_time
        if (hasta - desde).total_seconds() > umbral.ventana_minutos * 60:
            continue
        return PatternMatch(
            patron="auth_failures_burst",
            resultado="detectado",
            desde=desde,
            hasta=hasta,
            conteo=len(grupo),
            event_ids=[e.event_id for e in grupo],
        )
    return None


def _existence_pattern(events: list[RawEvent], tipo: str) -> PatternMatch | None:
    coincidencias = [e for e in events if e.tipo == tipo]
    if not coincidencias:
        return None
    resultado = str(coincidencias[-1].detalle.get("resultado", "ok"))
    return PatternMatch(
        patron=tipo,
        resultado=resultado,
        desde=coincidencias[0].event_time,
        hasta=coincidencias[-1].event_time,
        conteo=len(coincidencias),
        event_ids=[e.event_id for e in coincidencias],
    )


def detect_patterns(events: list[RawEvent], settings: VigilanciaSettings) -> list[PatternMatch]:
    matches = [_auth_failures_burst(events, settings)]
    matches += [_existence_pattern(events, tipo) for tipo in _EXISTENCE_PATTERNS]
    return [m for m in matches if m is not None]
