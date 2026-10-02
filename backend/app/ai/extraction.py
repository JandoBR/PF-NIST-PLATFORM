"""U1 — extraccion documental: chunk de texto -> evidencia `doc.claim` validada (docs/05 §2-§3).

La IA produce evidencia, nunca decide el puntaje (docs/05 intro). Este modulo solo valida,
filtra y normaliza; la regla de cada criterio vive en `app/evaluation/rules`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.ai.client import AIClient
from app.ai.schemas import ExtractionResponse
from app.schemas.evidence import EvidenceInstance, Locator, Modality

PROMPT_VERSION = "extract_v1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


#: Campos esperados en `contenido` por tipo de afirmacion. Las reglas de cada criterio leen estas
#: claves (docs/03); declararlas aca evita que la IA invente nombres de campo distintos.
_CONTENT_FIELDS: dict[str, str] = {
    "policy_exists": "nombre (string), aprobada_por (string|null)",
    "policy_review": (
        "frecuencia (mensual|trimestral|semestral|anual), ultima_revision (YYYY-MM-DD|null)"
    ),
    "role_assigned": "roles: lista de {rol, responsable, autoridad}",
    "risk_tolerance": (
        "objetivos_riesgo (string), tolerancia (string|null), responsable (string|null)"
    ),
    "data_inventory": (
        "activos (lista de recursos), tipos_datos (lista), clasificacion (string|null),"
        " criticidad (lista de {activo, nivel}|null)"
    ),
    "process_defined": (
        "proceso (riesgos|recuperacion|otro), pasos (string), responsables (string|null),"
        " criterios_activacion (string|null), registro_riesgos (bool|null),"
        " priorizacion (bool|null)"
    ),
    "backup_policy": (
        "respaldo (bool), verificacion_integridad (bool|null), retencion (string|null)"
    ),
}


def _contenido_esperado(tipos: list[str]) -> str:
    return "\n".join(
        f"- {tipo}: {_CONTENT_FIELDS.get(tipo, 'campos que describan la afirmacion')}"
        for tipo in tipos
    )


def _build_user_prompt(chunk_text: str, tipos_solicitados: list[str], doc_id: str) -> str:
    tipos = ", ".join(tipos_solicitados)
    return (
        f'<documento id="{doc_id}">\n{chunk_text}\n</documento>\n\n'
        f"Tipos de afirmacion a buscar en este fragmento: {tipos}.\n"
        f"Para 'contenido', usa estos campos por tipo:\n{_contenido_esperado(tipos_solicitados)}\n"
        "Responde en JSON con el esquema indicado."
    )


def extract_claims(
    client: AIClient,
    *,
    chunk_text: str,
    chunk_locator: Locator,
    tipos_solicitados: list[str],
    doc_id: str,
    source_id: str,
    scope: str,
    confianza_minima: float,
) -> list[EvidenceInstance]:
    """Ejecuta U1 sobre un chunk y devuelve evidencia `doc.claim` (reglas E1-E7, docs/05 §2.3)."""

    user_prompt = _build_user_prompt(chunk_text, tipos_solicitados, doc_id)
    raw = client.complete_json(_SYSTEM_PROMPT, user_prompt)
    if raw is None:
        return []  # degradado: sin respuesta util, no se inventa evidencia (E4/J4)

    try:
        parsed = ExtractionResponse.model_validate(raw)
    except ValidationError:
        return []  # JSON invalido contra el esquema: se descarta, nunca crashea (R5)

    observed_at = datetime.now(UTC)
    evidence: list[EvidenceInstance] = []

    for claim in parsed.afirmaciones:
        if claim.tipo not in tipos_solicitados:
            continue  # la IA no introduce tipos de afirmacion fuera de lo pedido (D5)

        if claim.encontrado and (claim.cita is None or not claim.cita.fragmento.strip()):
            continue  # E2: una afirmacion encontrada sin cita.fragmento se descarta

        limitations = None
        if claim.encontrado and claim.confianza < confianza_minima:
            limitations = f"confianza baja ({claim.confianza} < {confianza_minima})"  # E3

        locator = chunk_locator
        if claim.cita is not None:
            locator = Locator(
                file=chunk_locator.file,
                page=claim.cita.pagina if claim.cita.pagina is not None else chunk_locator.page,
                section=(
                    claim.cita.seccion if claim.cita.seccion is not None else chunk_locator.section
                ),
            )

        evidence.append(
            EvidenceInstance(
                type_id="doc.claim",
                type_version=1,
                subject_type="document",
                subject_ref=f"doc:{doc_id}",
                scope=scope,
                value={
                    "tipo_afirmacion": claim.tipo,
                    "contenido": claim.contenido,
                    "encontrado": claim.encontrado,
                    "confianza": claim.confianza,
                },
                source_id=source_id,
                locator=locator,
                observed_at=observed_at,
                modality=Modality.DOCUMENTAL,
                limitations=limitations,
                created_by="ai:extraction",
            )
        )

    return evidence
