"""CRI-ID-01 — Inventario de activos (docs/03 §2).

Mixto: contrasta el inventario declarado en documentos (`doc.claim(tipo=data_inventory)`) con los
tipos de recurso realmente presentes en Terraform (`tf.resource.present`). La cobertura se calcula
sobre **tipos** de recurso (docs/03 declara esa limitacion): solo se evaluan los tipos soportados.
"""

from __future__ import annotations

from app.adapters.terraform.adapter import CONFIG_RESOURCE_TYPES
from app.evaluation.rules._common import (
    best_found,
    by_type,
    doc_claims,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-01"
CRITERION_VERSION = 1


def _score_por_cobertura(cobertura: float) -> tuple[int, str]:
    if cobertura >= 1.0:
        return 100, "cubre todos los tipos de recurso presentes en Terraform"
    if cobertura >= 0.75:
        return 75, "cubre la mayoria (>= 75%) de los tipos de recurso presentes"
    if cobertura >= 0.25:
        return 50, "cubre parcialmente (25-74%) los tipos de recurso presentes"
    return 25, "menciona un inventario sin cobertura verificable de los recursos"


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "data_inventory")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre inventario de"
            " activos.",
        )

    mejor = best_found(claims)
    if mejor is None:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran un inventario de activos.",
            [c.id for c in claims],
        )

    # Los recursos que solo configuran a otro (versionado o cifrado de un bucket) no son activos:
    # ningun inventario los lista, y contarlos dejaba en 50 a un inventario completo.
    tipos_tf = {
        str(e.value.get("tipo")) for e in by_type(evidence, "tf.resource.present")
    } - CONFIG_RESOURCE_TYPES
    if not tipos_tf:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            25,
            "Inventario declarado, pero sin recursos de Terraform para verificar su cobertura.",
            [mejor.id],
        )

    activos = mejor.value.get("contenido", {}).get("activos") or []
    texto = " ".join(str(a) for a in activos).lower()
    cubiertos = {t for t in tipos_tf if t.lower() in texto}
    score, detalle = _score_por_cobertura(len(cubiertos) / len(tipos_tf))

    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        score,
        f"Inventario de activos {detalle} ({len(cubiertos)}/{len(tipos_tf)}).",
        [mejor.id],
    )
