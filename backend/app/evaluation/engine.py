"""Motor de evaluacion: despacha cada criterio a su regla (docs/01 §4-§5, D5).

Los criterios son fijos (D5): el registro de abajo es la unica fuente de logica de puntaje.
Agregar un criterio al catalogo (`methodology/criteria.yml`) y agregar su regla aqui van siempre
juntos.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai.adjustment import adjust, is_adjustable
from app.ai.client import AIClient
from app.evaluation.contradictions import Contradiction, detect, excluded_by_criterion
from app.evaluation.rules import (
    de01_monitoring,
    de02_event_analysis,
    de03_alert_notification,
    gv01_policy,
    gv02_roles,
    gv03_risk_tolerance,
    gv04_strategy_review,
    id01_asset_inventory,
    id02_asset_criticality,
    id03_risk_assessment,
    id04_data_inventory,
    pr01_encryption,
    pr02_backup,
    pr03_admin_access,
    pr04_ssh_hardening,
    pr05_public_access,
    pr06_logging,
    rc01_recovery_procedure,
    rc02_backup_verification,
    rc03_recovery_communication,
    rs01_response_plan,
    rs02_incident_analysis,
    rs03_notification,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.methodology.loader import Methodology
from app.schemas.evidence import EvidenceInstance

RuleFn = Callable[[list[EvidenceInstance]], CriterionResult]

_RULES: dict[str, RuleFn] = {
    gv01_policy.CRITERION_ID: gv01_policy.evaluate,
    gv02_roles.CRITERION_ID: gv02_roles.evaluate,
    gv03_risk_tolerance.CRITERION_ID: gv03_risk_tolerance.evaluate,
    gv04_strategy_review.CRITERION_ID: gv04_strategy_review.evaluate,
    id01_asset_inventory.CRITERION_ID: id01_asset_inventory.evaluate,
    id02_asset_criticality.CRITERION_ID: id02_asset_criticality.evaluate,
    id03_risk_assessment.CRITERION_ID: id03_risk_assessment.evaluate,
    id04_data_inventory.CRITERION_ID: id04_data_inventory.evaluate,
    de01_monitoring.CRITERION_ID: de01_monitoring.evaluate,
    pr01_encryption.CRITERION_ID: pr01_encryption.evaluate,
    pr02_backup.CRITERION_ID: pr02_backup.evaluate,
    pr03_admin_access.CRITERION_ID: pr03_admin_access.evaluate,
    pr04_ssh_hardening.CRITERION_ID: pr04_ssh_hardening.evaluate,
    pr05_public_access.CRITERION_ID: pr05_public_access.evaluate,
    pr06_logging.CRITERION_ID: pr06_logging.evaluate,
    de02_event_analysis.CRITERION_ID: de02_event_analysis.evaluate,
    de03_alert_notification.CRITERION_ID: de03_alert_notification.evaluate,
    rs01_response_plan.CRITERION_ID: rs01_response_plan.evaluate,
    rc01_recovery_procedure.CRITERION_ID: rc01_recovery_procedure.evaluate,
    rc02_backup_verification.CRITERION_ID: rc02_backup_verification.evaluate,
    rc03_recovery_communication.CRITERION_ID: rc03_recovery_communication.evaluate,
    rs02_incident_analysis.CRITERION_ID: rs02_incident_analysis.evaluate,
    rs03_notification.CRITERION_ID: rs03_notification.evaluate,
}


def _evaluate_one(
    methodology: Methodology,
    criterion_id: str,
    evidence: list[EvidenceInstance],
) -> CriterionResult:
    """Evalua un criterio. Uno sin regla registrada produce `error`: es una metodologia
    inconsistente (ver loader) y no debe pasar silenciosamente como si no existiera."""

    criterion = methodology.criterios[criterion_id]
    rule = _RULES.get(criterion_id)
    if rule is None:
        return CriterionResult(
            criterion_id=criterion_id,
            criterion_version=criterion.version,
            estado=Estado.ERROR,
            explanation="Criterio en el catalogo sin regla de evaluacion implementada.",
        )
    result = rule(evidence)
    result.criterion_version = criterion.version
    return result


def _annotate_contradictions(
    results: list[CriterionResult], contradicciones: list[Contradiction]
) -> list[CriterionResult]:
    """Deja constancia en la explicacion de que una afirmacion documental no conto (docs/02 §5)."""

    if not contradicciones:
        return results
    por_criterio: dict[str, list[Contradiction]] = {}
    for c in contradicciones:
        por_criterio.setdefault(c.criterion_id, []).append(c)

    anotados = []
    for r in results:
        pendientes = por_criterio.get(r.criterion_id)
        if not pendientes or r.estado == Estado.ERROR:
            anotados.append(r)
            continue
        detalle = " ".join(c.detalle for c in pendientes)
        anotados.append(
            r.model_copy(
                update={
                    "explanation": (
                        f"{r.explanation} Contradiccion entre fuentes: {detalle} La afirmacion"
                        " documental contradicha no cuenta para este puntaje (ver hallazgo)."
                    )
                }
            )
        )
    return anotados


def _evaluate_without_contradicted(
    methodology: Methodology, evidence: list[EvidenceInstance], criterion_ids: list[str]
) -> list[CriterionResult]:
    """Cada criterio se evalua sin las afirmaciones documentales que lo contradicen (docs/02 §5).
    La exclusion es por criterio: la misma afirmacion sigue contando para los demas."""

    contradicciones = detect(evidence)
    excluidas = excluded_by_criterion(contradicciones)
    results = []
    for criterion_id in criterion_ids:
        fuera = excluidas.get(criterion_id)
        visible = [e for e in evidence if e.id not in fuera] if fuera else evidence
        results.append(_evaluate_one(methodology, criterion_id, visible))
    return _annotate_contradictions(results, contradicciones)


def evaluate_all(
    methodology: Methodology, evidence: list[EvidenceInstance]
) -> list[CriterionResult]:
    """Evalua cada criterio del catalogo que tenga una regla registrada. Las afirmaciones
    documentales que contradicen a otra fuente no cuentan para puntuar el criterio contradicho
    (docs/02 §5)."""

    return _evaluate_without_contradicted(methodology, evidence, list(methodology.criterios))


def evaluate_only(
    methodology: Methodology,
    evidence: list[EvidenceInstance],
    criterion_ids: list[str],
) -> list[CriterionResult]:
    """Evalua solo los criterios indicados: la base del refresco selectivo (docs/06 §6, FN-06)."""

    return _evaluate_without_contradicted(
        methodology, evidence, [cid for cid in criterion_ids if cid in methodology.criterios]
    )


def _criterios_a_ajustar(methodology: Methodology, results: list[CriterionResult]) -> set[str]:
    """Ids que U2 intentara ajustar, respetando `max_criterios_ajustados_por_evaluacion`: si hay
    mas candidatos que el tope, los de mayor peso (desempate por id), de forma determinista."""

    candidatos = [
        r.criterion_id
        for r in results
        if (c := methodology.criterios.get(r.criterion_id)) is not None and is_adjustable(c, r)
    ]
    tope = methodology.settings.ia.max_criterios_ajustados_por_evaluacion
    if tope is not None and len(candidatos) > tope:
        candidatos = sorted(candidatos, key=lambda cid: (-methodology.criterios[cid].peso, cid))[
            : max(tope, 0)
        ]
    return set(candidatos)


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

    permitidos = _criterios_a_ajustar(methodology, results)

    adjusted = []
    for result in results:
        criterion = methodology.criterios.get(result.criterion_id)
        if criterion is None or result.criterion_id not in permitidos:
            adjusted.append(result)
            continue
        adjusted.append(
            adjust(client, criterion, result, evidence_by_id, context, alpha, divergencia_maxima)
        )
    return adjusted
