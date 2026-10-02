"""Presenta las contradicciones como hallazgos (docs/02 §5, docs/11 OP-04).

La deteccion y su efecto en el puntaje viven en `app/evaluation/contradictions.py`; aqui solo se
convierten en `Finding` de tipo `contradiccion` (sin puntaje propio y sin plan).
"""

from __future__ import annotations

from app.evaluation import contradictions
from app.recommendations.findings import Finding
from app.schemas.evidence import EvidenceInstance


def detect_contradictions(evidence: list[EvidenceInstance]) -> list[Finding]:
    return [
        Finding(
            criterion_id=c.criterion_id,
            titulo=c.titulo,
            tipo="contradiccion",
            severidad=c.severidad,
            score=None,
            detalle=c.detalle,
            evidence_ids=c.evidence_ids,
        )
        for c in contradictions.detect(evidence)
    ]
