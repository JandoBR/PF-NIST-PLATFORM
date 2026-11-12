"""CRI-ID-03 — Identificacion y evaluacion de riesgos (docs/03 §2).

Documental (`doc.claim(tipo=process_defined)`): el `contenido.proceso` distingue el proceso de
riesgos de otros procesos (p. ej. recuperacion, CRI-RC-01) que comparten el mismo tipo de
afirmacion.

Cinco anclas en vez de tres, porque el criterio cubre cinco subcategorias y antes no las
distinguia: `impactos`/`probabilidades` son `ID.RA-04` y solo con ellas se llega al 100. Las
facetas del proceso (`registro_riesgos`, `priorizacion`, `impactos`, `probabilidades`) ya
documentan el proceso aunque el documento no enumere `pasos`: el prompt los pide como texto libre y
el modelo suele omitirlos, y una ausencia en el texto extraido no es evidencia de que el proceso sea
generico (docs/01 §3). Un proceso solo con pasos evidencia `ID.RA-01` y nada mas, asi que baja a 50
(antes daba 75).
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    doc_claims,
    found,
    merged_content,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-03"
CRITERION_VERSION = 3


def _es_de_riesgos(claim: EvidenceInstance) -> bool:
    contenido = claim.value.get("contenido", {})
    proceso = str(contenido.get("proceso", "")).lower()
    # Por valor y no por presencia de la clave: el prompt pide `registro_riesgos`/`priorizacion`
    # en todo `process_defined`, y un proceso de otro tipo los trae en null/false. Los campos de
    # ID.RA-04 son propios de este proceso, asi que un fragmento que solo los trae tambien cuenta.
    return bool(
        "riesgo" in proceso
        or "risk" in proceso
        or contenido.get("registro_riesgos")
        or contenido.get("priorizacion")
        or contenido.get("impactos")
        or contenido.get("probabilidades")
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

    encontradas = found(candidatos)
    contenido, aportantes = merged_content(encontradas)
    if not encontradas:
        return silencio_documental(
            CRITERION_ID,
            "No se declara un proceso de evaluacion de riesgos.",
            [c.id for c in candidatos],
        )

    ids = [c.id for c in aportantes or encontradas]
    registrados = contenido.get("registro_riesgos") or contenido.get("priorizacion")
    # ID.RA-04: "se identifican y registran los impactos y probabilidades potenciales".
    cuantificados = contenido.get("impactos") or contenido.get("probabilidades")

    if contenido.get("pasos") and registrados and cuantificados:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Proceso de evaluacion de riesgos documentado, con registro, priorizacion y los"
            " impactos/probabilidades de cada riesgo.",
            ids,
        )
    if registrados and cuantificados:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Proceso de evaluacion de riesgos documentado con registro, priorizacion e impactos/"
            "probabilidades de cada riesgo, sin pasos detallados en el documento.",
            ids,
        )
    if contenido.get("pasos") and registrados:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Proceso de evaluacion de riesgos con registro y priorizacion, pero sin registrar los"
            " impactos ni las probabilidades potenciales (ID.RA-04).",
            ids,
        )
    if contenido.get("pasos"):
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            "Proceso de evaluacion de riesgos definido, sin registro ni priorizacion de riesgos.",
            ids,
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        25,
        "Evaluacion de riesgos descrita de forma generica, sin pasos concretos.",
        ids,
    )
