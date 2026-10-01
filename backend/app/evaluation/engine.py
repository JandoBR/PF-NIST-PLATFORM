"""Motor de evaluacion: despacha cada criterio a su regla (docs/01 §4-§5, D5).

Los criterios son fijos (D5): el registro de abajo es la unica fuente de logica de puntaje.
Agregar un criterio al catalogo (`methodology/criteria.yml`) y agregar su regla aqui van siempre
juntos.
"""

from __future__ import annotations

from collections.abc import Callable

from app.evaluation.rules import (
    gv01_policy,
    pr01_encryption,
    pr02_backup,
    pr03_admin_access,
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
