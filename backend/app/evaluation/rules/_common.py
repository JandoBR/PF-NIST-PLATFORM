"""Helpers compartidos por las reglas de criterio."""

from __future__ import annotations

from app.schemas.evidence import EvidenceInstance


def by_type(evidence: list[EvidenceInstance], type_id: str) -> list[EvidenceInstance]:
    return [e for e in evidence if e.type_id == type_id]
