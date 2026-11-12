"""Votacion de U1 con varias corridas (docs/05 §2.5, docs/09 §105).

`deepseek-flash` razona por defecto e ignora `temperature`: la misma entrada no da siempre la
misma salida. El estudio de varianza mostro que pensar + mayoria de 3 es la mejor combinacion
(recall 94.3 %, precision 98.8 %, frente a 93.8 % / 92.7 % sin pensar). Esto no cambia el cliente
ni el prompt: corre `extract_claims` N veces y combina las afirmaciones ya validadas (E3 confianza,
E8 cita literal).

Comparar cada campo por igualdad exacta perdia todo el texto libre: dos corridas que describen los
mismos pasos con otras palabras no coincidian y el campo se borraba, aunque las reglas solo
pregunten si esta. Por eso cada campo se vota segun como lo consume la regla (docs/05 §2.5,
docs/09 §113):

- **presencia**: texto libre que las reglas solo miran como verdad (`pasos`, `responsables`,
  `objetivos_riesgo`, `nombre`, ...). Gana si esta en la mayoria estricta de las corridas del
  grupo; el valor guardado es el medoide (el texto mas parecido al resto) de las que lo apoyan.
- **lista**: lista de textos libres (`activos`, `tipos_datos`, ...). Los elementos se emparejan
  entre corridas con similitud tolerante y cada uno sobrevive en la mayoria.
- **lista_dict**: lista de objetos; se emparejan por su clave (`roles` por `rol`, `criticidad` por
  `activo`) y cada subcampo se resuelve con las reglas de arriba.
- **cerrado**: booleanos, enums, fechas y cantidades normalizadas (`retencion`, `tolerancia`,
  `plazos`, `criterios_activacion`): igualdad exacta como antes.

`null` y ausente son el mismo estado. `estado_declarado` se vota aparte como campo cerrado
(`vigente|inexistente|planificado`), y `process_defined` se agrupa por (tipo, proceso) para no
perder la afirmacion de "mejora" cuando el modelo la fusiona con la de "respuesta". Las corridas se
ordenan por el contenido de sus afirmaciones, no por el orden en que llegaron, para que un mismo
conjunto de corridas vote lo mismo en cualquier orden. `claims_to_raw` conserva todos los campos de
la afirmacion, para que un replay desde el store reconstruya exactamente la misma evidencia
(docs/09 §108).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import unicodedata
from statistics import median
from typing import Any

from app.schemas.evidence import EvidenceInstance

DEFAULT_VOTES = 3
_MISSING = object()

#: Estados que declara el documento (docs/09 §106). Es un campo cerrado: un valor fuera de la
#: lista no vota y, sin mayoria, se queda el de la afirmacion de mayor confianza.
_ESTADOS_DECLARADOS = ("vigente", "inexistente", "planificado")

#: Clases de campo de `contenido` (docs/05 §2.5).
PRESENCIA = "presencia"
LISTA = "lista"
LISTA_DICT = "lista_dict"
CERRADO = "cerrado"

_ROLES: dict[str, Any] = {
    "tipo": LISTA_DICT,
    "clave": "rol",
    "jaccard_minimo": 0.5,
    "subcampos": {
        "rol": PRESENCIA,
        "responsable": PRESENCIA,
        "responsabilidades": PRESENCIA,
        "autoridad": PRESENCIA,
    },
}

#: Como se consume cada campo de `contenido` (docs/05 §2.5). Sin entrada, el campo se compara
#: exacto: un campo nuevo no se relaja por olvido. `extraction._CONTENT_FIELDS` es la otra mitad
#: del contrato y `tests/test_ai_voting.py` comprueba que no se separen.
_CAMPOS_POR_TIPO: dict[str, dict[str, Any]] = {
    "policy_exists": {"nombre": PRESENCIA, "aprobada_por": PRESENCIA},
    "policy_review": {"frecuencia": CERRADO, "ultima_revision": CERRADO},
    "role_assigned": {
        "roles": _ROLES,
        "recursos_asignados": CERRADO,
        "practicas_rh": CERRADO,
    },
    "risk_tolerance": {
        "objetivos_riesgo": PRESENCIA,
        "tolerancia": CERRADO,
        "responsable": PRESENCIA,
        "integracion_empresarial": CERRADO,
        "opciones_respuesta": CERRADO,
        "lineas_comunicacion": CERRADO,
        "metodo_estandarizado": CERRADO,
        "oportunidades_estrategicas": CERRADO,
    },
    "data_inventory": {
        "activos": LISTA,
        "tipos_datos": LISTA,
        "clasificacion": PRESENCIA,
        "criticidad": {
            "tipo": LISTA_DICT,
            "clave": "activo",
            "subcampos": {"activo": PRESENCIA, "nivel": PRESENCIA},
        },
    },
    "process_defined": {
        "proceso": CERRADO,
        "pasos": PRESENCIA,
        "responsables": PRESENCIA,
        "criterios_activacion": CERRADO,
        "criterios_declaracion": CERRADO,
        "registro_riesgos": CERRADO,
        "priorizacion": CERRADO,
        "metricas": CERRADO,
        "ajustes": CERRADO,
        "impactos": CERRADO,
        "probabilidades": CERRADO,
        "criterios_recuperacion": CERRADO,
        "planes_actualizados": CERRADO,
    },
    "backup_policy": {
        "respaldo": CERRADO,
        "verificacion_integridad": CERRADO,
        "retencion": CERRADO,
    },
    "notification_list": {
        "destinatarios": LISTA,
        "criterios": PRESENCIA,
        "plazos": CERRADO,
    },
    "escalation_path": {"niveles": PRESENCIA, "criterios": PRESENCIA},
    "org_context": {
        "mision": PRESENCIA,
        "partes_interesadas": LISTA,
        "requisitos_legales": LISTA,
        "servicios_criticos": LISTA,
        "dependencias": LISTA,
    },
    "supplier_program": {
        "programa": CERRADO,
        "roles": CERRADO,
        "proveedores_priorizados": CERRADO,
        "requisitos_contractuales": CERRADO,
        "integracion_riesgo": CERRADO,
        "debida_diligencia": CERRADO,
        "riesgos_monitoreados": CERRADO,
        "en_respuesta_incidentes": CERRADO,
        "monitoreo_ciclo_vida": CERRADO,
        "terminacion": CERRADO,
    },
    "training_program": {
        "programa": CERRADO,
        "frecuencia": CERRADO,
        "roles_especializados": CERRADO,
    },
    "exposure_policy": {
        "bases_publicas_permitidas": CERRADO,
        "descripcion": PRESENCIA,
    },
}


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


def _plano(texto: str) -> str:
    """Texto en minusculas, sin tildes ni marcas, para comparar significados."""

    descompuesto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _tokens(texto: str) -> frozenset[str]:
    return frozenset(re.findall(r"[0-9a-z]+", _plano(texto)))


def _similitud(a: str, b: str) -> float:
    """Parecido entre dos textos: media de Jaccard por tokens y `difflib` (0 a 1)."""

    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    razon = difflib.SequenceMatcher(None, _plano(a), _plano(b)).ratio()
    return (jaccard + razon) / 2


def _parecido(a: str, b: str, *, jaccard_minimo: float = 0.6) -> bool:
    """Dos textos son el mismo elemento si uno contiene al otro o se parecen lo suficiente.

    "aws_s3_bucket" y "s3" son el mismo activo (contencion de tokens) y
    "aws_s3_bucket (documentos)" tambien, porque lo contiene. La comparacion es determinista y no
    depende del orden.
    """

    na, nb = _plano(a).strip(), _plano(b).strip()
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb and (ta <= tb or tb <= ta):
        return True
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= jaccard_minimo


def _presente(valor: Any) -> bool:
    """Un campo de texto libre declara algo si trae texto o elementos, no si trae un booleano."""

    if valor is _MISSING or valor is None or isinstance(valor, bool):
        return False
    if isinstance(valor, str):
        return bool(valor.strip())
    if isinstance(valor, dict):
        return bool(valor)
    if isinstance(valor, list | tuple | set):
        return any(_presente(v) for v in valor)
    return True


def _como_texto(valor: Any) -> str:
    if isinstance(valor, str):
        return valor
    if valor is _MISSING or valor is None:
        return ""
    if isinstance(valor, list | tuple):
        return " ".join(_como_texto(v) for v in valor)
    if isinstance(valor, dict):
        return " ".join(f"{k} {_como_texto(v)}" for k, v in sorted(valor.items()))
    return str(valor)


def _claim_key(claim: EvidenceInstance) -> tuple[str, str, str]:
    """Llave canonica de una afirmacion, para ordenar corridas sin mirar como llegaron.

    Primero el contenido, despues el locator y solo al final el id: dos corridas se ordenan por lo
    que dijeron, no por un identificador aleatorio.
    """

    return (
        json.dumps(claim.value, sort_keys=True, ensure_ascii=False, default=str),
        json.dumps(claim.locator.model_dump(mode="json"), sort_keys=True, ensure_ascii=False),
        str(claim.id),
    )


def _run_key(run: list[EvidenceInstance]) -> tuple[tuple[str, str, str], ...]:
    return tuple(sorted(_claim_key(claim) for claim in run))


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


def _estado(claim: EvidenceInstance) -> str | None:
    """`estado_declarado` normalizado, o `None` si el valor no esta en la lista cerrada."""

    valor = (claim.value or {}).get("estado_declarado")
    if valor is None:
        return None
    normalizado = str(valor).strip().lower()
    return normalizado if normalizado in _ESTADOS_DECLARADOS else None


def _mejor(claims: list[tuple[int, EvidenceInstance]]) -> tuple[int, EvidenceInstance]:
    """Mayor confianza y, en empate, la corrida de menor indice canonico."""

    return max(claims, key=lambda item: (_confianza(item[1]), -item[0]))


def _representante(valores: list[tuple[int, float, Any]]) -> Any:
    """Valor original de la corrida de mayor confianza que produjo ese valor.

    Entre valores equivalentes (mismo texto tras normalizar) prefiere el que no trae espacios
    sobrantes, para guardar una forma limpia; el desempate final es la corrida canonica.
    """

    def preferencia(item: tuple[int, float, Any]) -> tuple[float, bool, int]:
        valor = item[2]
        limpio = not isinstance(valor, str) or valor == valor.strip()
        return item[1], limpio, -item[0]

    return max(valores, key=preferencia)[2]


def _medoide(valores: list[tuple[int, float, Any]]) -> Any:
    """Valor mas parecido al resto de los que apoyan el campo.

    El empate se decide por confianza, luego por el texto (canonico) y por ultimo por la corrida.
    """

    textos = [_como_texto(valor) for _, _, valor in valores]
    sumas = [
        sum(
            _similitud(textos[indice], texto) for otro, texto in enumerate(textos) if otro != indice
        )
        for indice in range(len(textos))
    ]
    mejor = max(sumas)
    empatados = [indice for indice, suma in enumerate(sumas) if suma == mejor]
    mayor_confianza = max(valores[indice][1] for indice in empatados)
    empatados = [indice for indice in empatados if valores[indice][1] == mayor_confianza]
    elegido = min(empatados, key=lambda i: (_plano(textos[i]), textos[i], valores[i][0]))
    return valores[elegido][2]


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


def _votar_presencia(entradas: list[tuple[int, float, Any]], threshold: int) -> tuple[bool, Any]:
    """Texto libre: sobrevive si esta en la mayoria; se guarda el medoide de los que lo traen."""

    apoyan = [(rank, conf, valor) for rank, conf, valor in entradas if _presente(valor)]
    if len({rank for rank, _, _ in apoyan}) < threshold:
        return False, None
    return True, _medoide(apoyan)


def _items(valor: Any) -> list[Any]:
    if isinstance(valor, list | tuple):
        return list(valor)
    if isinstance(valor, dict):
        return [valor]
    return []


def _agrupar(
    apariciones: list[tuple[int, float, int, Any]],
    umbral_corridas: int,
    *,
    clave: str | None = None,
    jaccard_minimo: float = 0.6,
) -> list[list[tuple[int, float, int, Any]]]:
    """Agrupa elementos de las corridas por parecido, sin depender del orden.

    Si `clave` esta, el parecido se decide por ese subcampo del objeto (`rol`, `activo`); si no,
    por el elemento completo. Dos elementos parecidos quedan en el mismo grupo aunque solo se
    parezcan al de en medio (componentes conexas: "CISO" y "responsable de seguridad" se unen por
    "oficial de seguridad (CISO)"). Un grupo sobrevive si aparece en la mayoria de las corridas
    (una corrida con dos elementos parecidos cuenta una vez) y el orden de salida es el de primera
    aparicion en el orden canonico.
    """

    ordenadas = sorted(apariciones, key=lambda a: (a[0], a[2]))
    textos = [_clave_de(aparicion[3], clave) for aparicion in ordenadas]
    padre = list(range(len(ordenadas)))

    def raiz(indice: int) -> int:
        while padre[indice] != indice:
            padre[indice] = padre[padre[indice]]
            indice = padre[indice]
        return indice

    for i in range(len(ordenadas)):
        for j in range(i + 1, len(ordenadas)):
            if _parecido(textos[i], textos[j], jaccard_minimo=jaccard_minimo):
                padre[raiz(j)] = raiz(i)

    componentes: dict[int, list[tuple[int, float, int, Any]]] = {}
    for indice, aparicion in enumerate(ordenadas):
        componentes.setdefault(raiz(indice), []).append(aparicion)
    return [
        componentes[clave_componente]
        for clave_componente in sorted(componentes)
        if len({aparicion[0] for aparicion in componentes[clave_componente]}) >= umbral_corridas
    ]


def _clave_de(elemento: Any, clave: str | None) -> str:
    if isinstance(elemento, dict) and clave:
        valor = elemento.get(clave)
        if _presente(valor):
            return _como_texto(valor)
    return _como_texto(elemento)


def _votar_lista(entradas: list[tuple[int, float, Any]], threshold: int) -> list[Any]:
    """Elementos de texto libre presentes en la mayoria de las corridas, emparejados por parecido.

    El orden es el de primera aparicion en el orden canonico de corridas y posiciones, para que no
    dependa de como llegaron.
    """

    apariciones = [
        (rank, conf, posicion, elemento)
        for rank, conf, valor in entradas
        for posicion, elemento in enumerate(_items(valor))
        if _presente(elemento)
    ]
    return [
        _medoide([(rank, conf, elemento) for rank, conf, _, elemento in grupo])
        for grupo in _agrupar(apariciones, threshold)
    ]


def _votar_lista_dict(
    entradas: list[tuple[int, float, Any]], threshold: int, spec: dict[str, Any]
) -> list[dict[str, Any]]:
    """Lista de objetos emparejados por su clave; cada subcampo se vota como su clase."""

    clave = str(spec.get("clave") or "")
    subcampos: dict[str, str] = spec.get("subcampos") or {}
    jaccard_minimo = float(spec.get("jaccard_minimo", 0.6))
    apariciones = [
        (rank, conf, posicion, elemento)
        for rank, conf, valor in entradas
        for posicion, elemento in enumerate(_items(valor))
        if isinstance(elemento, dict)
    ]
    resultado: list[dict[str, Any]] = []
    for grupo in _agrupar(apariciones, threshold, clave=clave, jaccard_minimo=jaccard_minimo):
        salida: dict[str, Any] = {}
        for subcampo in sorted({str(k) for _, _, _, item in grupo for k in item}):
            if subcampo == clave:
                valores = [
                    (rank, conf, item.get(subcampo))
                    for rank, conf, _, item in grupo
                    if _presente(item.get(subcampo))
                ]
                if valores:
                    salida[subcampo] = _medoide(valores)
                continue
            clase = subcampos.get(subcampo, CERRADO)
            valores = [(rank, conf, item.get(subcampo)) for rank, conf, _, item in grupo]
            if clase == PRESENCIA:
                hay_mayoria, valor = _votar_presencia(valores, threshold)
            else:
                hay_mayoria, valor = _votar_escalar(valores, threshold)
            if hay_mayoria and valor is not None:
                salida[subcampo] = valor
        if salida:
            resultado.append(salida)
    return resultado


def _clase(tipo: str, campo: str) -> Any:
    spec = _CAMPOS_POR_TIPO.get(tipo, {}).get(campo, CERRADO)
    return spec.get("tipo") if isinstance(spec, dict) else spec


def _votar_contenido(
    tipo: str, claims: list[tuple[int, EvidenceInstance]], threshold: int
) -> dict[str, Any]:
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
        spec = _CAMPOS_POR_TIPO.get(tipo, {}).get(campo, CERRADO)
        clase = _clase(tipo, campo)
        if clase == CERRADO and any(isinstance(e[2], list | tuple) for e in entradas):
            # Un campo no declarado que llega como lista se vota como lista: relajarlo de mas es
            # menos probable que perder un dato por un nombre de campo nuevo.
            clase = (
                LISTA_DICT
                if any(
                    isinstance(item, dict) for entrada in entradas for item in _items(entrada[2])
                )
                else LISTA
            )
            if clase == LISTA_DICT:
                spec = {"tipo": LISTA_DICT, "clave": "", "subcampos": {}}
        if clase == PRESENCIA:
            hay_mayoria, valor = _votar_presencia(entradas, threshold)
            if hay_mayoria:
                contenido[campo] = valor
        elif clase == LISTA:
            votados = _votar_lista(entradas, threshold)
            if votados:
                contenido[campo] = votados
        elif clase == LISTA_DICT:
            votados_dict = _votar_lista_dict(entradas, threshold, spec)
            if votados_dict:
                contenido[campo] = votados_dict
        else:
            hay_mayoria, valor = _votar_escalar(entradas, threshold)
            if hay_mayoria and valor is not _MISSING and valor is not None:
                contenido[campo] = valor
    return contenido


def _votar_grupo(claims: list[tuple[int, EvidenceInstance]], threshold: int) -> EvidenceInstance:
    """Combina una afirmacion por corrida (misma clave de grupo)."""

    base = min(claims, key=lambda item: item[0])[1]
    seleccionada = _mejor(claims)[1]
    tipo = str((base.value or {}).get("tipo_afirmacion") or "?")

    entradas_encontrado = [
        (idx, _confianza(c), (c.value or {}).get("encontrado")) for idx, c in claims
    ]
    hay_mayoria, encontrado = _votar_escalar(
        [(idx, conf, bool(valor)) for idx, conf, valor in entradas_encontrado], threshold
    )
    if not hay_mayoria:
        encontrado = bool((seleccionada.value or {}).get("encontrado"))

    confianzas = [_confianza(claim) for _, claim in claims]
    hay_mayoria_estado, estado = _votar_escalar(
        [(idx, _confianza(c), _estado(c)) for idx, c in claims], threshold
    )
    if not hay_mayoria_estado:
        estado = _estado(seleccionada)
    valor = {
        **(base.value or {}),
        "contenido": _votar_contenido(tipo, claims, threshold),
        "encontrado": encontrado,
        "confianza": float(median(confianzas)),
        "cita": (seleccionada.value or {}).get("cita"),
        # Campo cerrado y obligatorio con `encontrado=true` desde `doc.claim@3`: se vota como los
        # demas y se guarda con la afirmacion, o el replay perderia la negacion (docs/09 §108).
        "estado_declarado": estado,
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
    """Afirmaciones votadas de N corridas ya validadas (una lista de evidencia por corrida).

    Las corridas se ordenan por el contenido de sus afirmaciones antes de votar: el mismo conjunto
    de corridas produce el mismo resultado en cualquier orden (docs/00 §7).
    """

    threshold = umbral(len(runs))
    ordenadas = sorted(runs, key=_run_key)
    usables: dict[tuple[str, Any], dict[int, EvidenceInstance]] = {}
    todas: dict[tuple[str, Any], dict[int, EvidenceInstance]] = {}

    for run_idx, claims in enumerate(ordenadas):
        for claim in sorted(claims, key=_claim_key):
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
                "estado_declarado": valor.get("estado_declarado"),
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
