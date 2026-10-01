"""Adaptador de documentos: texto -> chunks -> IA (U1) -> evidencia `doc.claim` (docs/02 §3.3)."""

from __future__ import annotations

from pathlib import Path

from app.adapters.documents.extraction_text import chunk_document
from app.ai.client import AIClient
from app.ai.extraction import extract_claims
from app.methodology.loader import Methodology
from app.schemas.evidence import EvidenceInstance


class DocumentAdapter:
    """Convierte uno o mas documentos en evidencia `doc.claim`, via el cliente de IA inyectado."""

    def __init__(
        self, client: AIClient, methodology: Methodology, source_id: str, scope: str
    ) -> None:
        self._client = client
        self._confianza_minima = methodology.settings.ia.umbral_confianza_documental
        self.source_id = source_id
        self.scope = scope

    def parse_path(self, path: Path, tipos_solicitados: list[str]) -> list[EvidenceInstance]:
        """Procesa un documento o todos los documentos soportados de un directorio."""

        path = Path(path)
        supported = (".pdf", ".md", ".markdown", ".txt")
        files = (
            sorted(f for f in path.iterdir() if f.suffix.lower() in supported)
            if path.is_dir()
            else [path]
        )
        evidence: list[EvidenceInstance] = []
        for file_path in files:
            evidence.extend(self._parse_file(file_path, tipos_solicitados))
        return evidence

    def _parse_file(self, file_path: Path, tipos_solicitados: list[str]) -> list[EvidenceInstance]:
        evidence: list[EvidenceInstance] = []
        for chunk in chunk_document(file_path):
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
