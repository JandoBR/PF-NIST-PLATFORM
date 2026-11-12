"""Normalizacion determinista de cantidades escritas con palabras (docs/05 §2.3 E5).

Un documento puede decir "noventa dias" o "setenta y dos horas" en vez de "90 dias" o "72 horas".
El esquema guarda el texto tal como viene y las reglas que leen una cantidad (retencion, plazos,
tolerancias) esperan un numero: sin esta normalizacion la cifra se pierde aunque el documento la
declare. Se aplica en `_sanitize_content` sobre los campos de cantidad y queda como respaldo en
las reglas que parsean una cantidad de texto libre.

Solo se reescribe una cantidad cuando va seguida de una unidad reconocida ("noventa dias" ->
"90 dias"); asi "uno de los roles" no se convierte en "1 de los roles". La cita textual no se
toca nunca: la normalizacion es del `contenido`, no de lo que el documento dice.
"""

from __future__ import annotations

import re
import unicodedata

_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")

#: Cardinales sueltos del espanol. "un/una" valen 1; "medio/media" valen 0.5. Los cientos y
#: "mil"/"millon" se combinan en `_valor`.
_ES: dict[str, float] = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintiun": 21,
    "veintiuna": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "doscientas": 200,
    "trescientos": 300,
    "trescientas": 300,
    "cuatrocientos": 400,
    "cuatrocientas": 400,
    "quinientos": 500,
    "quinientas": 500,
    "seiscientos": 600,
    "seiscientas": 600,
    "setecientos": 700,
    "setecientas": 700,
    "ochocientos": 800,
    "ochocientas": 800,
    "novecientos": 900,
    "novecientas": 900,
    "medio": 0.5,
    "media": 0.5,
}

_EN: dict[str, float] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "half": 0.5,
}

#: Articulos que valen 1 solo delante de una unidad ("a month", "an hour").
_EN_ARTICULOS = {"a", "an"}

_CIENTOS = {"cien", "ciento"}
_POTENCIAS = {"mil": 1_000, "millon": 1_000_000, "millones": 1_000_000}
_EN_POTENCIAS = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}

_UNIDADES = {
    "dia",
    "dias",
    "semana",
    "semanas",
    "mes",
    "meses",
    "ano",
    "anos",
    "hora",
    "horas",
    "minuto",
    "minutos",
    "segundo",
    "segundos",
    "vez",
    "veces",
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
    "hour",
    "hours",
    "minute",
    "minutes",
    "second",
    "seconds",
    "time",
    "times",
}

_CONECTORES = {"y", "and"}


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _clave(palabra: str) -> str:
    return _sin_acentos(palabra).lower()


def _valor(palabras: list[str]) -> float | None:
    """Valor de una secuencia de palabras numericas ("setenta y dos", "dos mil veintiseis")."""

    total = 0.0
    actual = 0.0
    visto = False
    for palabra in palabras:
        if palabra in _CONECTORES:
            continue
        if palabra in _POTENCIAS:
            total += (actual or 1) * _POTENCIAS[palabra]
            actual = 0.0
        elif palabra in _EN_POTENCIAS:
            potencia = _EN_POTENCIAS[palabra]
            if potencia == 100:
                actual = (actual or 1) * potencia
            else:
                total += (actual or 1) * potencia
                actual = 0.0
        elif palabra in _ES:
            actual += _ES[palabra]
        elif palabra in _EN:
            actual += _EN[palabra]
        elif palabra in _EN_ARTICULOS:
            actual += 1
        else:
            return None
        visto = True
    if not visto:
        return None
    return total + actual


def _formato(valor: float) -> str:
    if float(valor).is_integer():
        return str(int(valor))
    return f"{valor:g}"


def numero(texto: str) -> int | float | None:
    """Valor cardinal de una frase escrita con palabras, o `None` si no es una cantidad.

    Acepta espanol e ingles basico, hasta millones: "noventa", "setenta y dos", "dos mil
    veintiseis", "one hundred twenty", "half". No interpreta ordinales ni fechas completas.
    """

    palabras = [_clave(p) for p in _PALABRA.findall(texto)]
    if not palabras:
        return None
    valor = _valor(palabras)
    if valor is None:
        return None
    return int(valor) if float(valor).is_integer() else valor


def normalizar_cantidades(texto: str) -> str:
    """Reescribe las cantidades en palabras seguidas de una unidad como digitos con esa unidad.

    "noventa dias" -> "90 dias"; "setenta y dos horas" -> "72 horas"; "cada tres meses" ->
    "cada 3 meses"; "media hora" -> "0.5 hora"; "ninety days" -> "90 days". Lo que no va seguido
    de una unidad se deja intacto, y una frase sin cantidades se devuelve tal cual.
    """

    if not texto:
        return texto

    coincidencias = list(_PALABRA.finditer(texto))
    salida: list[str] = []
    ultimo = 0
    i = 0
    while i < len(coincidencias):
        primera = coincidencias[i]
        if _clave(primera.group()) not in _ES_FRASES:
            i += 1
            continue

        palabras = [_clave(primera.group())]
        fin = primera.end()
        j = i
        while j + 1 < len(coincidencias):
            siguiente = coincidencias[j + 1]
            hueco = texto[fin : siguiente.start()]
            palabra = _clave(siguiente.group())
            if _es_conector(hueco) and palabra in _ES_FRASES:
                j += 1
                palabras.append(palabra)
                fin = coincidencias[j].end()
            else:
                break

        k = j + 1
        unidad = coincidencias[k] if k < len(coincidencias) else None
        if unidad is not None:
            hueco = texto[fin : unidad.start()]
            if hueco.strip() == "" and _clave(unidad.group()) in _UNIDADES:
                valor = _valor(palabras)
                if valor is not None:
                    salida.append(texto[ultimo : primera.start()])
                    salida.append(_formato(valor))
                    ultimo = fin
        i = j + 1

    salida.append(texto[ultimo:])
    return "".join(salida)


def _es_conector(hueco: str) -> bool:
    """True si el hueco entre dos palabras es solo espacio, guion o la conjuncion "y"/"and"."""

    limpio = hueco.strip().strip("-").strip()
    return limpio == "" or _clave(limpio) in _CONECTORES


#: Palabras que pueden abrir una cantidad. Se calcula una vez.
_ES_FRASES = (
    frozenset(_ES)
    | frozenset(_EN)
    | frozenset(_EN_ARTICULOS)
    | frozenset(_POTENCIAS)
    | frozenset(_EN_POTENCIAS)
    | frozenset(_CONECTORES)
)
