"""Motor de evaluacion: despacha cada criterio a su regla (docs/01 §4-§5, D5).

Los criterios son fijos (D5): el registro de abajo es la unica fuente de logica de puntaje.
Agregar un criterio al catalogo (`methodology/criteria.yml`) y agregar su regla aqui van siempre
juntos.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai.adjustment import adjust
from app.ai.client import AIClient
from app.evaluation.rules import (
    gv01_policy,
    pr01_encryption,
    pr02_backup,
    pr03_admin_access,
    pr04_ssh_hardening,
    pr05_public_access,
    pr06_logging,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import Methodology
from app.schemas.evidence import EvidenceInstance

RuleFn = Callable[[list[EvidenceInstance]], CriterionResult]

_RULES: dict[str, RuleFn] = {
    gv01_policy.CRITERION_ID: gv01_policy.evaluate,
    pr01_encryption.CRITERION_ID: pr01_encryption.evaluate,
    pr02_backup.CRITERION_ID: pr02_backup.evaluate,
    pr03_admin_access.CRITERION_ID: pr03_admin_access.evaluate,
    pr04_ssh_hardening.CRITERION_ID: pr04_ssh_hardening.evaluate,
    pr05_public_access.CRITERION_ID: pr05_public_access.evaluate,
    pr06_logging.CRITERION_ID: pr06_logging.evaluate,
}


def evaluate_all(
    methodology: Methodology, evidence: list[EvidenceInstance]
) -> list[CriterionResult]:
    """Evalua cada criterio del catalogo que tenga una regla registrada.

    Un criterio en el catalogo sin regla registrada produce `error`: es una metodologia
    inconsistente (ver loader) y no debe pasar silenciosamente como si no existiera.
    """

    results = []
    for criterion_id, criterion in methodology.criterios.items():
        rule = _RULES.get(criterion_id)
        if rule is None:
            results.append(
                CriterionResult(
                    criterion_id=criterion_id,
                    criterion_version=criterion.version,
                    estado=Estado.ERROR,
                    explanation="Criterio en el catalogo sin regla de evaluacion implementada.",
                )
            )
            continue
        result = rule(evidence)
        result.criterion_version = criterion.version
        results.append(result)
    return results


def apply_ai_adjustments(
    methodology: Methodology,
    results: list[CriterionResult],
    evidence: list[EvidenceInstance],
    client: AIClient,
    context: dict[str, Any],
) -> list[CriterionResult]:
    """U2 sobre cada resultado base (docs/05 §3). `base_score` de cada resultado nunca cambia."""

    evidence_by_id = {item.id: item for item in evidence}
    alpha = methodology.settings.ia.alpha
    divergencia_maxima = methodology.settings.ia.divergencia_maxima

    adjusted = []
    for result in results:
        criterion = methodology.criterios.get(result.criterion_id)
        if criterion is None:
            adjusted.append(result)
            continue
        adjusted.append(
            adjust(client, criterion, result, evidence_by_id, context, alpha, divergencia_maxima)
        )
    return adjusted
