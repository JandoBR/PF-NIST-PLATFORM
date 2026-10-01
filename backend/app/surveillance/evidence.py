"""Patrones detectados -> evidencia `log.pattern`/`log.window` (docs/02 §3.4, docs/06 §6).

El core es el unico que persiste evidencia (docs/04 §3.1, P4): este modulo solo construye las
instancias; quien las persiste es `app/core/assessment_service.py`, igual que con los demas
adaptadores.
"""

from __future__ import annotations

from app.schemas.evidence import EvidenceInstance, Locator, Modality
from app.surveillance.events import RawEvent
from app.surveillance.patterns import PatternMatch


def window_evidence(
    events: list[RawEvent], scope: str, source_id: str, created_by: str = "surveillance"
) -> EvidenceInstance:
    """Un `log.window` por lote ingerido; `completo=True` porque el lote se trata como la
    ventana entera (ver docstring de `patterns.py` sobre la simplificacion)."""

    desde = min(e.event_time for e in events)
    hasta = max(e.event_time for e in events)
    return EvidenceInstance(
        type_id="log.window",
        type_version=1,
        subject_type="scope",
        subject_ref=scope,
        scope=scope,
        value={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "completo": True},
        source_id=source_id,
        locator=Locator(event_id=f"{desde.isoformat()}..{hasta.isoformat()}"),
        observed_at=hasta,
        modality=Modality.OPERATIVA,
        created_by=created_by,
    )


def pattern_evidence(
    match: PatternMatch, scope: str, source_id: str, created_by: str = "surveillance"
) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="log.pattern",
        type_version=1,
        subject_type="scope",
        subject_ref=scope,
        scope=scope,
        value={
            "patron": match.patron,
            "resultado": match.resultado,
            "desde": match.desde.isoformat(),
            "hasta": match.hasta.isoformat(),
            "conteo": match.conteo,
        },
        source_id=source_id,
        locator=Locator(event_id=",".join(match.event_ids)),
        observed_at=match.hasta,
        modality=Modality.OPERATIVA,
        created_by=created_by,
    )


def build_evidence(
    events: list[RawEvent], matches: list[PatternMatch], scope: str, source_id: str
) -> list[EvidenceInstance]:
    if not events:
        return []
    evidence = [window_evidence(events, scope, source_id)]
    evidence += [pattern_evidence(match, scope, source_id) for match in matches]
    return evidence
