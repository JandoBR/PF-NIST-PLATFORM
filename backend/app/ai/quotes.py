"""Comprobar que la cita de una afirmacion esta en el texto (docs/00 §7 principio 3, docs/05 §2.3).

La misma normalizacion la usan la extraccion (para descartar citas inventadas) y el golden set (para
medirlas), asi que el producto y la prueba no pueden discrepar sobre que es "la misma cita".
"""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """Minusculas, sin acentos y con espacios colapsados: una cita no falla por formato."""

    sin_acentos = unicodedata.normalize("NFKD", text)
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos).strip().lower()


def quote_in_text(fragmento: str, texto: str) -> bool:
    """`fragmento` aparece en `texto`, sin distinguir mayusculas, acentos ni espacios."""

    cita = normalize(fragmento)
    return bool(cita) and cita in normalize(texto)
