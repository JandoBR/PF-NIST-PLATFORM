"""Disparadores deterministicos (docs/08 §5). La IA nunca decide si se abre un incidente,
solo sintetiza el plan despues (O1: "deteccion deterministica primero").

D2 (`alert_raised` sin `incident_triaged` a tiempo) se agrego despues (docs/11 OP-05, docs/09 §53)
junto con el patron `incident_triaged` (FN-08).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.methodology.schemas import VigilanciaSettings
from app.surveillance.patterns import PatternMatch


@dataclass(frozen=True)
class TriggerMatch:
    disparador: str
    correlation_key: str
    severidad: str
    criterios: list[str]
    titulo: str
    recurso: str
    first_event_time: datetime
    last_event_time: datetime
    event_ids: list[str]


def _by_patron(matches: list[PatternMatch], patron: str) -> PatternMatch | None:
    for match in matches:
        if match.patron == patron:
            return match
    return None


def _d1_sin_alerta(matches: list[PatternMatch], scope: str) -> TriggerMatch | None:
    burst = _by_patron(matches, "auth_failures_burst")
    if burst is None or _by_patron(matches, "alert_raised") is not None:
        return None
    recurso = burst.recurso or scope
    return TriggerMatch(
        disparador="D1",
        correlation_key=f"auth-burst:{recurso}:{burst.desde.isoformat()}",
        severidad="media",
        criterios=["CRI-DE-02", "CRI-DE-03"],
        titulo="Actividad sospechosa sin alerta de deteccion",
        recurso=recurso,
        first_event_time=burst.desde,
        last_event_time=burst.hasta,
        event_ids=burst.event_ids,
    )


def _d2_sin_triaje(
    matches: list[PatternMatch], settings: VigilanciaSettings, scope: str
) -> TriggerMatch | None:
    """Hubo una alerta y nadie la triajeo dentro del plazo (`plazo_triaje_minutos`)."""

    alerta = _by_patron(matches, "alert_raised")
    if alerta is None:
        return None

    triaje = _by_patron(matches, "incident_triaged")
    if triaje is not None:
        delta_segundos = (triaje.desde - alerta.desde).total_seconds()
        if 0 <= delta_segundos <= settings.plazo_triaje_minutos * 60:
            return None  # triajeo a tiempo: sin disparador

    recurso = alerta.recurso or scope
    event_ids = alerta.event_ids + (triaje.event_ids if triaje else [])
    return TriggerMatch(
        disparador="D2",
        correlation_key=f"alert-sin-triaje:{recurso}:{alerta.desde.isoformat()}",
        severidad="media",
        criterios=["CRI-RS-01"],
        titulo="Alerta sin triaje a tiempo",
        recurso=recurso,
        first_event_time=alerta.desde,
        last_event_time=(triaje.hasta if triaje else alerta.hasta),
        event_ids=event_ids,
    )


def _d3_sin_escalar(
    matches: list[PatternMatch], settings: VigilanciaSettings, scope: str
) -> TriggerMatch | None:
    declarado = _by_patron(matches, "incident_declared")
    if declarado is None:
        return None

    escalado = _by_patron(matches, "escalation_done")
    if escalado is not None:
        delta_segundos = (escalado.desde - declarado.desde).total_seconds()
        # Como en D2: un escalamiento anterior a la declaracion no es el de este incidente.
        if 0 <= delta_segundos <= settings.plazo_escalamiento_minutos * 60:
            return None  # escalo a tiempo: sin disparador

    recurso = declarado.recurso or scope
    event_ids = declarado.event_ids + (escalado.event_ids if escalado else [])
    return TriggerMatch(
        disparador="D3",
        correlation_key=f"incident:{recurso}:{declarado.desde.isoformat()}",
        severidad="alta",
        criterios=["CRI-RS-01"],
        titulo="Incidente declarado sin escalamiento a tiempo",
        recurso=recurso,
        first_event_time=declarado.desde,
        last_event_time=(escalado.hasta if escalado else declarado.hasta),
        event_ids=event_ids,
    )


def _d4_restauracion_fallida(matches: list[PatternMatch], scope: str) -> TriggerMatch | None:
    ejercicio = _by_patron(matches, "restore_exercise_run")
    if ejercicio is None or ejercicio.resultado != "fail":
        return None
    recurso = ejercicio.recurso or scope
    return TriggerMatch(
        disparador="D4",
        correlation_key=f"restore-fail:{recurso}:{ejercicio.desde.isoformat()}",
        severidad="alta",
        criterios=["CRI-RC-02", "CRI-RC-03"],
        titulo="Ejercicio de restauracion fallido",
        recurso=recurso,
        first_event_time=ejercicio.desde,
        last_event_time=ejercicio.hasta,
        event_ids=ejercicio.event_ids,
    )


def _d5_sin_comunicar(matches: list[PatternMatch], scope: str) -> TriggerMatch | None:
    verificado = _by_patron(matches, "restore_verified")
    if verificado is None or _by_patron(matches, "recovery_communicated") is not None:
        return None
    recurso = verificado.recurso or scope
    return TriggerMatch(
        disparador="D5",
        correlation_key=f"restore-sin-comunicar:{recurso}:{verificado.desde.isoformat()}",
        severidad="baja",
        criterios=["CRI-RC-03"],
        titulo="Restauracion verificada sin comunicacion de recuperacion",
        recurso=recurso,
        first_event_time=verificado.desde,
        last_event_time=verificado.hasta,
        event_ids=verificado.event_ids,
    )


def evaluate_triggers(
    matches: list[PatternMatch], settings: VigilanciaSettings, scope: str
) -> list[TriggerMatch]:
    candidatos = (
        _d1_sin_alerta(matches, scope),
        _d2_sin_triaje(matches, settings, scope),
        _d3_sin_escalar(matches, settings, scope),
        _d4_restauracion_fallida(matches, scope),
        _d5_sin_comunicar(matches, scope),
    )
    return [t for t in candidatos if t is not None]
