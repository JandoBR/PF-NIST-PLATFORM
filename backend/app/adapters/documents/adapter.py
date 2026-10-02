"""Adaptador de documentos: texto -> chunks -> IA (U1) -> evidencia `doc.claim` (docs/02 §3.3)."""

from __future__ import annotations

from pathlib import Path

from app.adapters.documents.extraction_text import chunk_document
from app.ai.client import AIClient
from app.ai.extraction import extract_claims
from app.methodology.loader import Methodology
from app.schemas.evidence import EvidenceInstance

#: Limite de chunks por documento (docs/05 §7: control de costo). Un documento con mas
#: secciones/paginas que esto simplemente deja de analizarse a partir de ese punto; no es
#: un error, pero vale la pena hacerlo visible en el reporte de la CLI.
DEFAULT_MAX_CHUNKS_PER_DOCUMENT = 20


#: Se sube a mano cuando cambia lo que el adaptador emite (docs/11 OP-14).
ADAPTER_VERSION = "1"


class DocumentAdapter:
    """Convierte uno o mas documentos en evidencia `doc.claim`, via el cliente de IA inyectado."""

    def __init__(
        self,
        client: AIClient,
        methodology: Methodology,
        source_id: str,
        scope: str,
        max_chunks_per_document: int = DEFAULT_MAX_CHUNKS_PER_DOCUMENT,
    ) -> None:
        self._client = client
        self._confianza_minima = methodology.settings.ia.umbral_confianza_documental
        self.source_id = source_id
        self.scope = scope
        self._max_chunks_per_document = max_chunks_per_document
        self.chunks_omitidos = 0

    _SUPPORTED_SUFFIXES = (".pdf", ".md", ".markdown", ".txt")

    @classmethod
    def list_files(cls, path: Path) -> list[Path]:
        """Un documento soportado, o todos los que haya en un directorio."""

        path = Path(path)
        if path.is_dir():
            return sorted(f for f in path.iterdir() if f.suffix.lower() in cls._SUPPORTED_SUFFIXES)
        return [path]

    def parse_path(self, path: Path, tipos_solicitados: list[str]) -> list[EvidenceInstance]:
        evidence: list[EvidenceInstance] = []
        for file_path in self.list_files(path):
            evidence.extend(self._parse_file(file_path, tipos_solicitados))
        return evidence

    def _parse_file(self, file_path: Path, tipos_solicitados: list[str]) -> list[EvidenceInstance]:
        evidence: list[EvidenceInstance] = []
        chunks = chunk_document(file_path)
        if len(chunks) > self._max_chunks_per_document:
            self.chunks_omitidos += len(chunks) - self._max_chunks_per_document
            chunks = chunks[: self._max_chunks_per_document]

        for chunk in chunks:
            evidence.extend(
                extract_claims(
                    self._client,
                    chunk_text=chunk.text,
                    chunk_locator=chunk.locator,
                    tipos_solicitados=tipos_solicitados,
                    doc_id=file_path.stem,
                    source_id=self.source_id,
                    scope=self.scope,
                    confianza_minima=self._confianza_minima,
                )
            )
        return evidence
