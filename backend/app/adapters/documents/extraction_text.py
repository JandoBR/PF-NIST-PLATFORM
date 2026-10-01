"""Extraccion de texto y chunking por seccion/pagina (docs/05 §2.1, docs/02 §7).

Solo documentos con capa de texto: PDFs escaneados sin texto extraible producen
paginas vacias que simplemente se omiten (no es un error, es un limite declarado).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.schemas.evidence import Locator

_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    text: str
    locator: Locator


def chunk_markdown(path: Path) -> list[Chunk]:
    """Una secciones por encabezado `#`..`######`; sin encabezados, el documento entero."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        match = _HEADING_PATTERN.match(line)
        if match:
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = match.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))

    return [
        Chunk(
            text="\n".join(section_lines).strip(),
            locator=Locator(file=str(path), section=heading),
        )
        for heading, section_lines in sections
        if "\n".join(section_lines).strip()
    ]


def chunk_pdf(path: Path) -> list[Chunk]:
    """Una pagina por chunk; paginas sin capa de texto se omiten."""

    reader = PdfReader(str(path))
    chunks = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        chunks.append(Chunk(text=text, locator=Locator(file=str(path), page=page_number)))
    return chunks


def chunk_document(path: Path) -> list[Chunk]:
    """Despacha por extension. `.txt` se trata como Markdown sin encabezados."""

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return chunk_pdf(path)
    if suffix in (".md", ".markdown", ".txt"):
        return chunk_markdown(path)
    raise ValueError(f"Extension de documento no soportada: {suffix}")
