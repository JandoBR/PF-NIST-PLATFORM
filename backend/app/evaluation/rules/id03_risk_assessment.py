"""CRI-ID-03 — Identificacion y evaluacion de riesgos (docs/03 §2).

Documental (`doc.claim(tipo=process_defined)`): el `contenido.proceso` distingue el proceso de
riesgos de otros procesos (p. ej. recuperacion, CRI-RC-01) que comparten el mismo tipo de
afirmacion.
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, doc_claims, result, silencio_documental
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-03"
CRITERION_VERSION = 1


def _es_de_riesgos(claim: EvidenceInstance) -> bool:
    contenido = claim.value.get("contenido", {})
    proceso = str(contenido.get("proceso", "")).lower()
    # Por valor y no por presencia de la clave: el prompt pide `registro_riesgos`/`priorizacion`
    # en todo `process_defined`, y un proceso de otro tipo los trae en null/false.
    return bool(
        "riesgo" in proceso
        or "risk" in proceso
        or contenido.get("registro_riesgos")
        or contenido.get("priorizacion")
    )


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "process_defined")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre evaluacion de"
            " riesgos.",
        )

    candidatos = [c for c in claims if _es_de_riesgos(c)]
    if not candidatos:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un proceso de identificacion/evaluacion de"
            " riesgos.",
            [c.id for c in claims],
        )

    mejor = best_found(candidatos)
    if mejor is None:
        return silencio_documental(
            CRITERION_ID,
            "No se declara un proceso de evaluacion de riesgos.",
            [c.id for c in candidatos],
        )

    contenido = mejor.value.get("contenido", {})
    if contenido.get("pasos") and (
        contenido.get("registro_riesgos") or contenido.get("priorizacion")
    ):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Proceso de evaluacion de riesgos documentado, con registro y priorizacion.",
            [mejor.id],
        )
    if contenido.get("pasos"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Proceso de evaluacion de riesgos definido, sin registro de riesgos.",
            [mejor.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Evaluacion de riesgos descrita de forma generica.",
        [mejor.id],
    )
