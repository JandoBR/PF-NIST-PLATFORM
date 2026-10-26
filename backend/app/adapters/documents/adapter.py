"""Adaptador de documentos: texto -> chunks -> IA (U1) -> evidencia `doc.claim` (docs/02 §3.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.adapters.documents.extraction_text import chunk_document
from app.ai.client import AIClient
from app.ai.extraction import extract_claims
from app.methodology.loader import Methodology
from app.schemas.evidence import EvidenceInstance, Locator, Modality

#: Limite de chunks por documento (docs/05 §7: control de costo). Un documento con mas
#: secciones/paginas que esto simplemente deja de analizarse a partir de ese punto; no es
#: un error, pero vale la pena hacerlo visible en el reporte de la CLI.
DEFAULT_MAX_CHUNKS_PER_DOCUMENT = 20


#: Se sube a mano cuando cambia lo que el adaptador emite (docs/11 OP-14).
#: v2: emite `doc.source.info` por documento analizado (docs/11 CR-07).
#: v3: BOM UTF-8, encabezados Markdown dentro de bloques de codigo y PDFs cifrados que se omiten
#: en vez de tumbar la evaluacion.
ADAPTER_VERSION = "3"


class _CountingClient:
    """Cuenta cuantas llamadas contesto la IA y cuantas no (`None` = degradado)."""

    def __init__(self, inner: AIClient) -> None:
        self._inner = inner
        self.respondidas = 0
        self.sin_respuesta = 0

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        respuesta = self._inner.complete_json(system_prompt, user_prompt)
        if respuesta is None:
            self.sin_respuesta += 1
        else:
            self.respondidas += 1
        return respuesta


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

    def _source_info(
        self, file_path: Path, secciones: int, enviadas: int, sin_respuesta: int
    ) -> EvidenceInstance:
        """Marca de documento analizado (E6, docs/11 CR-07): existe aunque ninguna seccion de
        afirmaciones. `analizadas` cuenta las que la IA respondio; `omitidas` las que el tope de
        secciones dejo sin enviar y `sin_respuesta` las que se enviaron y la IA no contesto."""

        return EvidenceInstance(
            type_id="doc.source.info",
            type_version=1,
            subject_type="document",
            subject_ref=f"doc:{file_path.stem}",
            scope=self.scope,
            value={
                "titulo": file_path.stem,
                "archivo": file_path.name,
                "secciones": secciones,
                "analizadas": enviadas - sin_respuesta,
                "omitidas": secciones - enviadas,
                "sin_respuesta": sin_respuesta,
            },
            source_id=self.source_id,
            locator=Locator(file=str(file_path)),
            observed_at=datetime.now(UTC),
            modality=Modality.DOCUMENTAL,
            created_by="adapter:documents",
        )

    def _parse_file(self, file_path: Path, tipos_solicitados: list[str]) -> list[EvidenceInstance]:
        chunks = chunk_document(file_path)
        total = len(chunks)
        if total > self._max_chunks_per_document:
            self.chunks_omitidos += total - self._max_chunks_per_document
            chunks = chunks[: self._max_chunks_per_document]

        contador = _CountingClient(self._client)
        claims: list[EvidenceInstance] = []
        for chunk in chunks:
            claims.extend(
                extract_claims(
                    contador,
                    chunk_text=chunk.text,
                    chunk_locator=chunk.locator,
                    tipos_solicitados=tipos_solicitados,
                    doc_id=file_path.stem,
                    source_id=self.source_id,
                    scope=self.scope,
                    confianza_minima=self._confianza_minima,
                )
            )

        # Un documento al que la IA no contesto en ninguna seccion NO se marca como analizado: eso
        # diria "se leyo y no habia nada" cuando en realidad no se leyo (degradar sin inventar).
        if chunks and contador.respondidas == 0:
            return claims
        info = self._source_info(file_path, total, len(chunks), contador.sin_respuesta)
        return [info, *claims]
