"""`docs/03-matriz-de-criterios.md` describe el catalogo: que lo siga describiendo.

La cabecera de ese documento afirma que "las reglas de esta matriz describen el codigo" y que se
actualiza en el mismo commit. Hasta ahora nada lo comprobaba, y se noto dos veces:

- La Oleada A añadio `CRI-GV-05`, `CRI-GV-06` y `CRI-PR-07` al catalogo **sin ficha**: la tabla
  decia "Govern | 6" y habia cuatro fichas (docs/09 §77).
- `CRI-GV-03` cubria las siete subcategorias de `GV.RM` con el titulo viejo, y la Oleada B lo
  encontro mirando la pantalla, no los tests (docs/09 §78). Al escribir las fichas que faltaban se
  colaron dos titulos truncados mas, que aparecieron revisando la Oleada C.

Tres veces el mismo fallo es un test que falta, no mala suerte.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[2] / "docs" / "03-matriz-de-criterios.md"
_FICHA = re.compile(r"^### (CRI-[A-Z]{2}-\d{2}) — (.+?)\s*$", re.MULTILINE)

#: Anotaciones que la ficha puede añadir al titulo del catalogo sin que sea un descuadre.
_SUFIJOS_PERMITIDOS = (" *(privacidad, secundaria)*",)


def _fichas() -> dict[str, str]:
    encontradas = _FICHA.findall(DOC.read_text(encoding="utf-8"))
    assert len(encontradas) == len({c for c, _ in encontradas}), "hay fichas duplicadas"
    return dict(encontradas)


def test_every_criterion_has_exactly_one_card(methodology):
    fichas = _fichas()

    assert set(fichas) == set(methodology.criterios), (
        "la matriz y el catalogo no describen los mismos criterios: "
        f"solo en docs/03={sorted(set(fichas) - set(methodology.criterios))}, "
        f"solo en criteria.yml={sorted(set(methodology.criterios) - set(fichas))}"
    )


def test_every_card_title_matches_the_catalog(methodology):
    """Un criterio cuyo titulo dice menos de lo que evalua produce recomendaciones incompletas."""

    fichas = _fichas()
    descuadres = []
    for cid, titulo_ficha in sorted(fichas.items()):
        titulo = titulo_ficha
        for sufijo in _SUFIJOS_PERMITIDOS:
            if titulo.endswith(sufijo):
                titulo = titulo[: -len(sufijo)]
        if _norm(titulo) != _norm(methodology.criterios[cid].titulo):
            descuadres.append(
                f"{cid}: ficha='{titulo_ficha}' catalogo='{methodology.criterios[cid].titulo}'"
            )

    assert not descuadres, "titulos que no coinciden:\n  " + "\n  ".join(descuadres)


@pytest.mark.parametrize("campo", ["Subcategorías", "Evidencias", "Regla"])
def test_every_card_declares_its_sections(campo):
    """Una ficha sin subcategorias, evidencias o regla no describe nada."""

    # Se busca solo el prefijo en negrita: las fichas escriben `**Regla:**`, pero tambien
    # `**Regla** (exige una ventana completa)` y `**Regla (por recurso soportado):**`.
    texto = DOC.read_text(encoding="utf-8")
    bloques = re.split(r"^### CRI-[A-Z]{2}-\d{2} — ", texto, flags=re.MULTILINE)[1:]
    sin_campo = [b.splitlines()[0] for b in bloques if f"**{campo}" not in b]

    assert not sin_campo, f"fichas sin `{campo}`: {sin_campo}"


def _norm(s: str) -> str:
    """Compara ignorando tildes y mayusculas: el catalogo va sin tildes y las fichas con ellas."""

    import unicodedata

    plano = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", plano.lower()).strip()
