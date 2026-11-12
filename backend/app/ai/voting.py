"""Votacion de U1 con varias corridas (docs/05 §2.4, docs/09 §105).

`deepseek-flash` razona por defecto e ignora `temperature`: la misma entrada no da siempre la
misma salida. El estudio de varianza mostro que pensar + mayoria de 3 por campo es la mejor
combinacion (recall 94.3 %, precision 98.8 %, frente a 93.8 % / 92.7 % sin pensar). Esto no
cambia el cliente ni el prompt: corre `extract_claims` N veces y combina las afirmaciones ya
validadas (E3 confianza, E8 cita literal).

El voto es generico sobre `contenido`: no hay una lista de campos por tipo. Un campo escalar
gana si el mismo valor normalizado aparece en >= umbral corridas; las listas se combinan elemento
por elemento; `null` y ausente son el mismo estado (sin mayoria -> el campo no va).
`process_defined` se agrupa por (tipo, proceso) para no perder la afirmacion de "mejora" cuando el
modelo la fusiona con la de "respuesta".
"""

from __future__ import annotations

import os
from statistics import median
from typing import Any

from app.schemas.evidence import EvidenceInstance

DEFAULT_VOTES = 3
_MISSING = object()


def votes() -> int:
    """`U1_VOTES` (3 por defecto; 1 = sin votacion). Un valor invalido usa el default."""

    raw = os.environ.get("U1_VOTES")
    if not raw:
        return DEFAULT_VOTES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_VOTES


def umbral(n: int) -> int:
    """Corridas que debe repetir un valor para ganar (mayoria estricta; 1 corrida = todo vale)."""

    return 1 if n <= 1 else max(2, n // 2 + 1)


def _norm(value: Any) -> Any:
    """Forma comparable: texto sin mayusculas ni espacios sobrantes; el resto, valor exacto."""

    if isinstance(value, str):
        return ("str", value.strip().casefold())
    if isinstance(value, bool | int | float):
        return ("scalar", value)
    if value is None:
        return ("null",)
    if isinstance(value, dict):
        return ("dict", tuple(sorted((str(k), _norm(v)) for k, v in value.items())))
    if isinstance(value, list | tuple):
        return ("list", tuple(_norm(v) for v in value))
    return ("raw", str(value))


def _group_key(claim: EvidenceInstance) -> tuple[str, Any]:
    valor = claim.value or {}
    tipo = str(valor.get("tipo_afirmacion") or "?")
    if tipo == "process_defined":
        proceso = (valor.get("contenido") or {}).get("proceso")
        return tipo, _norm(proceso) if proceso is not None else None
    return tipo, None


def _confianza(claim: EvidenceInstance) -> float:
    try:
        return float((claim.value or {}).get("confianza") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _mejor(claims: list[tuple[int, EvidenceInstance]]) -> tuple[int, EvidenceInstance]:
    """Mayor confianza y, en empate, la corrida de menor indice: desempate determinista."""

    return max(claims, key=lambda item: (_confianza(item[1]), -item[0]))


def _representante(valores: list[tuple[int, float, Any]]) -> Any:
    """Valor original (sin normalizar) de la corrida de mayor confianza que produjo ese valor."""

    return max(valores, key=lambda item: (item[1], -item[0]))[2]


def _votar_escalar(entradas: list[tuple[int, float, Any]], threshold: int) -> tuple[bool, Any]:
    """(hay mayoria, valor). `None`/ausente es un estado mas y puede ser el que gane."""

    por_valor: dict[Any, list[tuple[int, float, Any]]] = {}
    for entrada in entradas:
        valor = entrada[2]
        por_valor.setdefault(_norm(None if valor is _MISSING else valor), []).append(entrada)
    ganador = max(
        por_valor.values(),
        key=lambda valores: (len(valores), max(v[1] for v in valores), -min(v[0] for v in valores)),
    )
    if len(ganador) < threshold:
        return False, None
    return True, _representante(ganador)


def _votar_lista(entradas: list[tuple[int, float, Any]], threshold: int) -> list[Any]:
    """Elementos presentes en >= umbral corridas, comparados normalizados.

    El orden sale del representante de mayor confianza; lo que no estaba en su lista se agrega en
    orden de primera aparicion (corrida y posicion).
    """

    por_elemento: dict[Any, list[tuple[int, float, Any]]] = {}
    primera_aparicion: dict[Any, tuple[int, int]] = {}
    for run_idx, confianza, valor in entradas:
        if not isinstance(valor, list | tuple):
            continue
        for posicion, elemento in enumerate(valor):
            clave = _norm(elemento)
            por_elemento.setdefault(clave, []).append((run_idx, confianza, elemento))
            primera_aparicion.setdefault(clave, (run_idx, posicion))

    sobreviven = {
        clave: valores
        for clave, valores in por_elemento.items()
        if len({v[0] for v in valores}) >= threshold
    }
    if not sobreviven:
        return []

    representante = _representante(entradas)
    orden: list[Any] = []
    if isinstance(representante, list | tuple):
        for elemento in representante:
            clave = _norm(elemento)
            if clave in sobreviven and clave not in orden:
                orden.append(clave)
    for clave in sorted(
        (c for c in sobreviven if c not in orden), key=lambda c: primera_aparicion[c]
    ):
        orden.append(clave)
    return [_representante(sobreviven[clave]) for clave in orden]


def _votar_contenido(claims: list[tuple[int, EvidenceInstance]], threshold: int) -> dict[str, Any]:
    campos = sorted(
        {
            key
            for _, claim in claims
            for key in (claim.value.get("contenido") or {})
            if not str(key).startswith("_")
        }
    )
    contenido: dict[str, Any] = {}
    for campo in campos:
        entradas = [
            (run_idx, _confianza(claim), (claim.value.get("contenido") or {}).get(campo, _MISSING))
            for run_idx, claim in claims
        ]
        if any(isinstance(entrada[2], list | tuple) for entrada in entradas):
            votados = _votar_lista(entradas, threshold)
            if votados:
                contenido[campo] = votados
            continue
        hay_mayoria, valor = _votar_escalar(entradas, threshold)
        if hay_mayoria and valor is not _MISSING and valor is not None:
            contenido[campo] = valor
    return contenido


def _votar_grupo(claims: list[tuple[int, EvidenceInstance]], threshold: int) -> EvidenceInstance:
    """Combina una afirmacion por corrida (misma clave de grupo)."""

    base = min(claims, key=lambda item: item[0])[1]
    seleccionada = _mejor(claims)[1]

    entradas_encontrado = [
        (idx, _confianza(c), (c.value or {}).get("encontrado")) for idx, c in claims
    ]
    hay_mayoria, encontrado = _votar_escalar(
        [(idx, conf, bool(valor)) for idx, conf, valor in entradas_encontrado], threshold
    )
    if not hay_mayoria:
        encontrado = bool((seleccionada.value or {}).get("encontrado"))

    confianzas = [_confianza(claim) for _, claim in claims]
    valor = {
        **(base.value or {}),
        "contenido": _votar_contenido(claims, threshold),
        "encontrado": encontrado,
        "confianza": float(median(confianzas)),
        "cita": (seleccionada.value or {}).get("cita"),
    }
    return base.model_copy(
        update={
            "value": valor,
            "locator": seleccionada.locator,
            "observed_at": seleccionada.observed_at,
            "limitations": None,
        }
    )


def vote(runs: list[list[EvidenceInstance]]) -> list[EvidenceInstance]:
    """Afirmaciones votadas de N corridas ya validadas (una lista de evidencia por corrida)."""

    threshold = umbral(len(runs))
    usables: dict[tuple[str, Any], dict[int, EvidenceInstance]] = {}
    todas: dict[tuple[str, Any], dict[int, EvidenceInstance]] = {}

    for run_idx, claims in enumerate(runs):
        for claim in claims:
            key = _group_key(claim)
            actual = todas.setdefault(key, {}).get(run_idx)
            if actual is None or _confianza(claim) > _confianza(actual):
                todas[key][run_idx] = claim
            if claim.limitations is None:
                actual = usables.setdefault(key, {}).get(run_idx)
                if actual is None or _confianza(claim) > _confianza(actual):
                    usables[key][run_idx] = claim

    resultado: dict[tuple[str, Any], EvidenceInstance] = {}
    for key, por_corrida in usables.items():
        if len(por_corrida) >= threshold:
            resultado[key] = _votar_grupo(sorted(por_corrida.items()), threshold)

    # Una afirmacion que ninguna corrida valido (confianza baja o cita no localizable) no se vota,
    # pero tampoco se borra si la mayoria de las corridas la produjo: se conserva la de mayor
    # confianza con sus limitaciones, para que quede a la vista y no cuente (E3/E8, docs/05 §2.3).
    for key, por_corrida in todas.items():
        if key in resultado or (key in usables and len(usables[key]) >= threshold):
            continue
        if len(por_corrida) >= threshold:
            resultado[key] = _mejor(sorted(por_corrida.items()))[1]

    return sorted(
        resultado.values(),
        key=lambda claim: (
            str((claim.value or {}).get("tipo_afirmacion") or ""),
            str(_group_key(claim)[1] or ""),
        ),
    )


def claims_to_raw(claims: list[EvidenceInstance]) -> dict[str, Any]:
    """Forma cruda (`ExtractionResponse`) de las afirmaciones votadas, para guardarlas."""

    afirmaciones = []
    for claim in claims:
        valor = claim.value or {}
        cita = valor.get("cita")
        afirmaciones.append(
            {
                "tipo": valor.get("tipo_afirmacion"),
                "encontrado": bool(valor.get("encontrado")),
                "contenido": valor.get("contenido") or {},
                "cita": (
                    {
                        "fragmento": cita,
                        "pagina": claim.locator.page,
                        "seccion": claim.locator.section,
                    }
                    if cita
                    else None
                ),
                "confianza": valor.get("confianza", 0.0),
            }
        )
    return {"afirmaciones": afirmaciones}


def run_summary(runs: list[tuple[dict | None, list[EvidenceInstance]]]) -> dict[str, Any]:
    """Resumen compacto de las corridas crudas, para auditar una respuesta votada (meta)."""

    return {
        "votos": len(runs),
        "runs": [
            {
                "crudo": raw is not None,
                "afirmaciones": len(claims),
                "usables": sum(1 for claim in claims if claim.limitations is None),
            }
            for raw, claims in runs
        ],
    }
