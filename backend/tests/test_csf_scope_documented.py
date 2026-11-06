"""Cada subcategoria del CSF 2.0 tiene criterio o tiene motivo escrito.

`docs/12 §5` afirma de si mismo que el motivo de lo no declarado "va aqui, no en la cabeza de
nadie". Hasta la Oleada C eso no se cumplia: de las 25 subcategorias descubiertas, nueve no
aparecian en ninguna parte del documento, y nada lo detectaba porque la cobertura solo cuenta las
que **si** estan cubiertas.

Este test convierte la afirmacion en algo que cuesta mantener: la lista no puede quedarse atras de
`criteria.yml` en ninguna de las dos direcciones. Es el mismo movimiento que
`test_criteria_matrix_doc.py` hizo con la matriz de criterios.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.methodology import coverage

ALCANCE = Path(__file__).resolve().parents[2] / "docs" / "12-alcance-y-trabajo-futuro.md"
_SUBCATEGORIA = re.compile(r"\b([A-Z]{2}\.[A-Z]{2}-\d{2})\b")


def _descubiertas(methodology) -> set[str]:
    """Las del nucleo que ningun criterio declara, calculadas por el modulo de cobertura."""

    declaradas = {s for c in methodology.criterios.values() for s in c.subcategorias}
    cobertura = coverage.compute(methodology.criterios, methodology.nucleo_csf)
    todas = _todas(methodology.nucleo_csf)
    assert len(todas) == cobertura.subcategorias_totales, (
        "el recuento de este test y el de coverage.py discrepan: "
        f"{len(todas)} vs {cobertura.subcategorias_totales}"
    )
    return todas - declaradas


def _todas(nucleo) -> set[str]:
    encontradas: set[str] = set()

    def recorrer(nodo) -> None:
        if isinstance(nodo, dict):
            if "id" in nodo and "titulo" in nodo and _SUBCATEGORIA.fullmatch(str(nodo["id"])):
                encontradas.add(str(nodo["id"]))
            for valor in nodo.values():
                recorrer(valor)
        elif isinstance(nodo, list):
            for valor in nodo:
                recorrer(valor)

    recorrer(nucleo.model_dump())
    return encontradas


def _mencionadas() -> set[str]:
    return set(_SUBCATEGORIA.findall(ALCANCE.read_text(encoding="utf-8")))


def test_every_uncovered_subcategory_has_a_documented_reason(methodology):
    """Lo que el marco pide y el sistema no evalua tiene que tener su porque escrito."""

    sin_motivo = sorted(_descubiertas(methodology) - _mencionadas())

    assert not sin_motivo, (
        "subcategorias sin criterio y sin motivo en docs/12 §5: "
        f"{sin_motivo}. O se cubren con un criterio, o se explica por que no."
    )


def test_no_reason_is_left_over_for_a_covered_subcategory(methodology):
    """La otra direccion: si una oleada la cubre, hay que sacarla de la lista.

    Un motivo que sobrevive a su causa es peor que no tenerlo: afirma que algo esta fuera de
    alcance cuando ya se evalua.
    """

    declaradas = {s for c in methodology.criterios.values() for s in c.subcategorias}
    sobrantes = sorted(declaradas & _mencionadas() - _descubiertas(methodology))
    # Una subcategoria cubierta puede citarse legitimamente para explicar otra cosa (p. ej.
    # `GV.SC-07`, que AMP-07 nombra para decir que ya tiene respaldo determinista), asi que solo
    # se exige que no aparezca en la tabla de descubiertas.
    tabla = _tabla_de_descubiertas()
    en_la_tabla = sorted(s for s in sobrantes if s in tabla)

    assert not en_la_tabla, (
        "estas subcategorias ya tienen criterio pero siguen listadas como descubiertas en "
        f"docs/12 §5: {en_la_tabla}"
    )


def _tabla_de_descubiertas() -> set[str]:
    """Las subcategorias que la seccion presenta COMO descubiertas.

    Solo la primera columna de cada fila: la segunda es la explicacion, y ahi se citan de forma
    legitima subcategorias que si estan cubiertas (`RS.CO-02` para decir que `CRI-RS-03` cubre el
    plan de notificacion, `RC.CO-03` para situar `recovery_communicated`). Leer la fila entera
    las confundia con descubiertas.
    """

    texto = ALCANCE.read_text(encoding="utf-8")
    inicio = texto.index("### Las 25 subcategorías descubiertas")
    fin = texto.index("\n## ", inicio)
    sujetos: set[str] = set()
    for linea in texto[inicio:fin].splitlines():
        if not linea.startswith("|") or set(linea) <= set("|- "):
            continue
        celdas = linea.split("|")
        if len(celdas) > 2:
            sujetos |= set(_SUBCATEGORIA.findall(celdas[1]))
    return sujetos


def test_the_section_claims_the_right_total(methodology):
    """El encabezado dice un numero: que sea el de verdad."""

    descubiertas = _descubiertas(methodology)
    cabecera = re.search(r"### Las (\d+) subcategorías descubiertas", ALCANCE.read_text("utf-8"))

    assert cabecera, "no se encontro el encabezado de la seccion de descubiertas"
    assert int(cabecera.group(1)) == len(descubiertas), (
        f"el encabezado dice {cabecera.group(1)} descubiertas y hay {len(descubiertas)}"
    )
