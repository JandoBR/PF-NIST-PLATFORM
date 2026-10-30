"""Saneo de nombres de archivo subidos por el cliente (docs/04 §9).

El nombre lo controla quien sube el archivo, asi que nunca se usa crudo para construir una ruta:
se descarta cualquier componente de directorio (path traversal) y se valida la extension contra una
lista blanca por tipo de fuente.
"""

from __future__ import annotations

from pathlib import Path

#: Extensiones admitidas por tipo de fuente (docs/04 §9: lista blanca, sin descompresion recursiva).
ALLOWED_SUFFIXES: dict[str, set[str]] = {
    "terraform": {".tf"},
    "ansible": {".yml", ".yaml"},
    "documents": {".pdf", ".md", ".markdown", ".txt"},
    "events": {".jsonl"},
    "default": {".tf", ".yml", ".yaml", ".pdf", ".md", ".markdown", ".txt", ".jsonl"},
}


def safe_filename(name: str | None, *, tipo: str = "default") -> str:
    """Devuelve un nombre de archivo seguro (solo basename) o levanta `ValueError`.

    Rechaza nombres vacios, `.`/`..`, separadores de Windows y bytes nulos, y exige una extension de
    la lista blanca del tipo. Una ruta con `/` se reduce a su basename (`../../etc/evil.tf` ->
    `evil.tf`); una con `\\` se rechaza.

    El `\\` se comprueba sobre el nombre **original**, antes de `Path(...).name`: `Path` trata `\\`
    como separador en Windows y como un caracter normal en Linux, asi que hacerlo despues dejaba el
    saneo dependiendo del sistema operativo (en Windows `..\\..\\evil.tf` pasaba como `evil.tf`).
    """

    original = (name or "").strip()
    if not original or "\x00" in original:
        raise ValueError("Nombre de archivo invalido.")
    if "\\" in original:
        raise ValueError("Nombre de archivo invalido.")
    base = Path(original).name
    if base in ("", ".", ".."):
        raise ValueError("Nombre de archivo invalido.")
    if len(base.encode("utf-8")) > 255:
        # `NAME_MAX` en Linux; sin esto, `write_bytes` revienta con OSError (500) en vez de 422.
        raise ValueError("Nombre de archivo demasiado largo.")
    suffix = Path(base).suffix.lower()
    allowed = ALLOWED_SUFFIXES.get(tipo, ALLOWED_SUFFIXES["default"])
    if suffix not in allowed:
        raise ValueError(f"Extension no permitida para '{tipo}': {suffix or '(sin extension)'}.")
    return base
