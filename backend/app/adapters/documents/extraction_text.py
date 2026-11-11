"""Extraccion de texto y chunking por seccion/pagina (docs/05 §2.1, docs/02 §7).

Solo documentos con capa de texto: PDFs escaneados sin texto extraible producen
paginas vacias que simplemente se omiten (no es un error, es un limite declarado).

Las secciones (Markdown) y paginas (PDF) consecutivas se agrupan en un chunk hasta un presupuesto
de caracteres, sin partir ninguna. Un documento con muchas subsecciones cortas produce pocos
chunks -- menos llamadas a la IA y menos facetas fragmentadas -- pero cada `Chunk` guarda los
offsets de sus secciones para que la cita se resuelva a la seccion o pagina que la contiene.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from app.schemas.evidence import Locator, Segmento

_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.*)$")

#: Presupuesto de caracteres de un chunk agrupado (docs/05 §2.1). Agrupa varias secciones o
#: paginas cortas sin partirlas; una sola mayor que esto queda como su propio chunk.
DEFAULT_MAX_CHARS_PER_CHUNK = 8000

#: Separador entre secciones agrupadas: el texto conserva los encabezados Markdown, y en un PDF
#: mantiene una pagina separada de la siguiente.
_SEPARADOR = "\n\n"


@dataclass(frozen=True)
class Chunk:
    text: str
    locator: Locator
    segmentos: tuple[Segmento, ...] = ()


def _agrupar(secciones: list[tuple[Locator, str]], max_chars: int) -> list[Chunk]:
    """Agrupa en orden las secciones hasta `max_chars`; nunca parte una seccion.

    Una seccion mayor que el presupuesto queda sola en su chunk (no se recorta: el texto se
    enviaria incompleto sin avisar)."""

    grupos: list[list[tuple[Locator, str]]] = []
    actual: list[tuple[Locator, str]] = []
    largo = 0
    for locator, texto in secciones:
        extra = len(texto) + (len(_SEPARADOR) if actual else 0)
        if actual and largo + extra > max_chars:
            grupos.append(actual)
            actual = []
            largo = 0
            extra = len(texto)
        actual.append((locator, texto))
        largo += extra
    if actual:
        grupos.append(actual)
    return [_chunk(grupo) for grupo in grupos]


def _chunk(secciones: list[tuple[Locator, str]]) -> Chunk:
    partes: list[str] = []
    segmentos: list[Segmento] = []
    largo = 0
    for locator, texto in secciones:
        if partes:
            partes.append(_SEPARADOR)
            largo += len(_SEPARADOR)
        partes.append(texto)
        segmentos.append(Segmento(inicio=largo, fin=largo + len(texto), locator=locator))
        largo += len(texto)
    return Chunk(text="".join(partes), locator=secciones[0][0], segmentos=tuple(segmentos))


def chunk_markdown(path: Path, max_chars: int = DEFAULT_MAX_CHARS_PER_CHUNK) -> list[Chunk]:
    """Secciones por encabezado `#`..`######`, agrupadas hasta `max_chars`; sin encabezados, el
    documento entero."""

    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    en_bloque = False

    for line in lines:
        # Un `#` dentro de un bloque de codigo (``` o ~~~) es un comentario, no un encabezado.
        if line.lstrip().startswith(("```", "~~~")):
            en_bloque = not en_bloque
            current_lines.append(line)
            continue
        match = None if en_bloque else _HEADING_PATTERN.match(line)
        if match:
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = match.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))

    secciones = [
        (Locator(file=str(path), section=heading), "\n".join(section_lines).strip())
        for heading, section_lines in sections
        if "\n".join(section_lines).strip()
    ]
    return _agrupar(secciones, max_chars)


def chunk_pdf(path: Path, max_chars: int = DEFAULT_MAX_CHARS_PER_CHUNK) -> list[Chunk]:
    """Paginas con capa de texto, agrupadas hasta `max_chars`; las vacias se omiten."""

    try:
        reader = PdfReader(str(path))
        paginas = list(reader.pages)
    except (FileNotDecryptedError, PdfReadError):
        # PDF valido pero protegido con contrasena: no se puede leer sin credenciales. Se omite
        # el documento (el adaptador lo reporta con cero secciones), no se tumba la evaluacion.
        return []

    secciones = []
    for page_number, page in enumerate(paginas, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except (FileNotDecryptedError, PdfReadError):
            continue
        if not text:
            continue
        secciones.append((Locator(file=str(path), page=page_number), text))
    return _agrupar(secciones, max_chars)


def chunk_document(path: Path, max_chars: int = DEFAULT_MAX_CHARS_PER_CHUNK) -> list[Chunk]:
    """Despacha por extension. `.txt` se trata como Markdown sin encabezados."""

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return chunk_pdf(path, max_chars)
    if suffix in (".md", ".markdown", ".txt"):
        return chunk_markdown(path, max_chars)
    raise ValueError(f"Extension de documento no soportada: {suffix}")
