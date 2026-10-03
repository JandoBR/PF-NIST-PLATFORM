"""U1 — extraccion documental: chunk de texto -> evidencia `doc.claim` validada (docs/05 §2-§3).

La IA produce evidencia, nunca decide el puntaje (docs/05 intro). Este modulo solo valida,
filtra y normaliza; la regla de cada criterio vive en `app/evaluation/rules`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.ai.calllog import call_context
from app.ai.client import AIClient
from app.ai.schemas import ExtractionResponse
from app.schemas.evidence import EvidenceInstance, Locator, Modality

#: v2: `process_defined.proceso` ofrece `respuesta` (plan de respuesta a incidentes). Sin esa opcion,
#: el modelo nunca podia etiquetar un plan de respuesta y `CRI-RS-01` no lo encontraba (docs/09 §59).
PROMPT_VERSION = "extract_v2"
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
        "proceso (riesgos|respuesta|recuperacion|revision|analisis incidentes|otro), pasos (string),"
        " responsables (string|null), criterios_activacion (string|null),"
        " criterios_declaracion (bool|null), registro_riesgos (bool|null),"
        " priorizacion (bool|null), metricas (bool|null), ajustes (bool|null)"
    ),
    "backup_policy": (
        "respaldo (bool), verificacion_integridad (bool|null), retencion (string|null)"
    ),
    "notification_list": ("destinatarios (lista), criterios (string|null), plazos (string|null)"),
    "escalation_path": "niveles (string), criterios (string|null)",
    "exposure_policy": (
        "bases_publicas_permitidas (bool|null: false si la politica prohibe bases de datos"
        " accesibles desde Internet, true si las permite), descripcion (string|null)"
    ),
}


#: Frecuencias de revision aceptadas (docs/05 §2.3 E5); otro valor se descarta.
_FRECUENCIAS = {"mensual", "trimestral", "semestral", "anual"}
_FECHA_MINIMA = date(1990, 1, 1)
_ROL_MAX_CHARS = 120


def _sanitize_content(tipo: str, contenido: dict) -> dict:
    """E5 (docs/05 §2.3): campos de fecha/rol se validan contra formatos esperados y los valores
    absurdos se descartan. El campo descartado se quita (los criterios lo ven como ausente) y queda
    anotado en `_descartados`; la afirmacion no se invalida entera."""

    limpio = dict(contenido)
    descartados: list[str] = []

    if tipo == "policy_review":
        ultima = limpio.get("ultima_revision")
        if ultima is not None:
            try:
                fecha = date.fromisoformat(str(ultima))
                valida = _FECHA_MINIMA <= fecha <= date.today() + timedelta(days=1)
            except ValueError:
                valida = False
            if not valida:
                limpio["ultima_revision"] = None
                descartados.append(f"ultima_revision={ultima!r}: fecha invalida o fuera de rango")
        frecuencia = limpio.get("frecuencia")
        if frecuencia is not None and str(frecuencia).lower() not in _FRECUENCIAS:
            limpio["frecuencia"] = None
            descartados.append(f"frecuencia={frecuencia!r}: no es una frecuencia reconocida")

    if tipo == "role_assigned" and "roles" in limpio:
        roles = limpio["roles"]
        if not isinstance(roles, list):
            limpio.pop("roles")
            descartados.append("roles: se esperaba una lista")
        else:
            validos = [
                r
                for r in roles
                if isinstance(r, dict)
                and isinstance(r.get("rol"), str)
                and 0 < len(r["rol"].strip()) <= _ROL_MAX_CHARS
            ]
            if len(validos) != len(roles):
                descartados.append(f"roles: {len(roles) - len(validos)} entrada(s) invalida(s)")
            limpio["roles"] = validos

    if descartados:
        limpio["_descartados"] = descartados
    return limpio


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
    with call_context(paso="U1", prompt_version=PROMPT_VERSION, doc_id=doc_id):
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
                    "contenido": _sanitize_content(claim.tipo, claim.contenido),
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
