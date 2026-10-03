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

    Rechaza nombres vacios, `.`/`..`, separadores de ruta y bytes nulos, y exige una extension de la
    lista blanca del tipo. `Path(original).name` ya elimina directorios, pero se comprueba ademas
    explicitamente por si el separador es de Windows (`\\`), que en Linux no es especial.
    """

    original = (name or "").strip()
    if not original or "\x00" in original:
        raise ValueError("Nombre de archivo invalido.")
    base = Path(original).name
    if base in ("", ".", "..") or "/" in base or "\\" in base:
        raise ValueError("Nombre de archivo invalido.")
    suffix = Path(base).suffix.lower()
    allowed = ALLOWED_SUFFIXES.get(tipo, ALLOWED_SUFFIXES["default"])
    if suffix not in allowed:
        raise ValueError(f"Extension no permitida para '{tipo}': {suffix or '(sin extension)'}.")
    return base
