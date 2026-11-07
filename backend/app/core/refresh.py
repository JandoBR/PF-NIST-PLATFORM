"""Refresco de madurez tras ingerir eventos (docs/06 §6, docs/08 §8, FN-05/FN-06).

Decide si una ingesta justifica reevaluar (umbral de patrones nuevos) y corre el refresco
selectivo: reusa todo lo no operativo de la evaluacion anterior (incluida la IA) y recalcula solo
los criterios que leen eventos.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core import reproducibility
from app.core.assessment_service import (
    AssessmentNotFoundError,
    collect_surveillance_evidence,
    create_pending_reevaluation,
    enqueue_reevaluation,
    has_documents,
    load_criterion_results,
    load_evidence,
)
from app.core.dispatch import dispatch_job
from app.core.repository import (
    evidence_to_row,
    plan_to_row,
    result_to_row,
)
from app.evaluation import engine
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import (
    Assessment,
    EvidenceRow,
    Job,
    PlanRow,
    Source,
)
from app.recommendations import plans as recommendations_plans


def maybe_enqueue_maturity_refresh(
    session: Session,
    methodology: Methodology,
    redis_client,
    *,
    org_id: str,
    scope: str,
    nuevos_patrones: int,
) -> Assessment | None:
    """Refresco automatico de madurez al ingerir eventos (docs/06 §6, docs/08 §8): si la ingesta
    agrego suficientes `log.pattern` nuevos para ese scope, encola una reevaluacion de la ultima
    evaluacion completada del org+scope. `None` si no corresponde.

    No dispara si: no hay evaluacion previa (nada que refrescar), no hay Redis, no se alcanza el
    umbral (`settings.vigilancia.refresco_min_patrones_nuevos`) o ya hay una evaluacion en vuelo
    para ese org+scope (evita apilar)."""

    min_patrones = methodology.settings.vigilancia.refresco_min_patrones_nuevos
    if redis_client is None or nuevos_patrones < min_patrones:
        return None

    in_flight = (
        session.query(Assessment)
        .filter(
            Assessment.org_id == org_id,
            Assessment.scope == scope,
            Assessment.estado.in_(["pendiente", "en_progreso"]),
        )
        .first()
    )
    if in_flight is not None:
        return None

    previous = (
        session.query(Assessment)
        .filter_by(org_id=org_id, scope=scope, estado="completada")
        .order_by(Assessment.creado_en.desc())
        .first()
    )
    if previous is None:
        return None

    assessment, _ = enqueue_surveillance_refresh(session, methodology, redis_client, previous.id)
    return assessment


def enqueue_surveillance_refresh(
    session: Session,
    methodology: Methodology,
    redis_client,
    previous_assessment_id: str,
) -> tuple[Assessment, Job]:
    """Crea una reevaluacion **selectiva** y encola su `assessment_run` (docs/06 §6, FN-06): el
    worker corre `run_surveillance_refresh` (reusa lo previo, recalcula solo lo operativo) en vez
    del pipeline completo y sin IA."""

    previous = session.get(Assessment, previous_assessment_id)
    if previous is None:
        raise AssessmentNotFoundError(previous_assessment_id)

    if previous.methodology_version != methodology.methodology_version:
        # La metodologia cambio desde la evaluacion anterior: reusar sus resultados mezclaria
        # versiones y dejaria fuera criterios nuevos. Se hace un re-run completo con las mismas
        # fuentes (y U1 si hay documentos), en vez de un refresco selectivo (docs/09 §74).
        return enqueue_reevaluation(
            session,
            methodology,
            redis_client,
            previous_assessment_id,
            request_documents_ai=has_documents(session, previous_assessment_id),
        )

    assessment, _paths = create_pending_reevaluation(session, methodology, previous_assessment_id)
    job = dispatch_job(
        session,
        redis_client,
        "assessment_run",
        {
            "assessment_id": assessment.id,
            "previous_assessment_id": previous_assessment_id,
            "selective_refresh": True,
            "ai_requested": False,
            "apply_ai_adjustment": False,
            "context": {},
        },
        assessment_id=assessment.id,
    )
    return assessment, job


#: Tipos de evidencia operativa (vigilancia). El refresco selectivo los recalcula; el resto de la
#: evidencia y de los resultados se reusa de la evaluacion anterior (docs/06 §6).
SURVEILLANCE_EVIDENCE_TYPES = frozenset({"log.pattern", "log.window"})


def _criterion_uses_surveillance(criterion) -> bool:
    return any(ev.split("@", 1)[0] in SURVEILLANCE_EVIDENCE_TYPES for ev in criterion.evidencias)


def run_surveillance_refresh(
    session: Session,
    methodology: Methodology,
    assessment_id: str,
    previous_assessment_id: str,
) -> Assessment:
    """Refresco selectivo de madurez (docs/06 §6, docs/11 FN-06).

    Reusa evidencia, resultados y planes de la evaluacion anterior y **recalcula solo los criterios
    que consumen evidencia de vigilancia** (`log.pattern`/`log.window`) con los patrones frescos.
    Asi se preserva lo derivado de IA (claims U1, ajuste U2, texto de planes) en los criterios no
    afectados, sin gastar IA ni degradar el resto."""

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError(assessment_id)
    previous = session.get(Assessment, previous_assessment_id)
    if previous is None:
        raise AssessmentNotFoundError(previous_assessment_id)

    if previous.methodology_version != methodology.methodology_version:
        # Defensa en profundidad: un job selectivo encolado antes de un deploy de metodologia no
        # puede completar una evaluacion mezclando versiones.
        assessment.estado = "fallida"
        assessment.error = (
            "El refresco selectivo requiere la misma metodologia que la evaluacion anterior"
            f" ({previous.methodology_version} != {methodology.methodology_version})."
        )
        session.commit()
        raise ValueError(assessment.error)

    assessment.estado = "en_progreso"
    session.commit()

    try:
        _apply_selective_refresh(session, methodology, assessment, previous)
        assessment.estado = "completada"
    except Exception as exc:
        assessment.estado = "fallida"
        assessment.error = str(exc)
        session.commit()
        raise

    session.commit()
    return assessment


def _remap_result_evidence(result: CriterionResult, remap: dict[str, str]) -> CriterionResult:
    if not result.evidence_ids:
        return result
    return result.model_copy(
        update={"evidence_ids": [remap.get(ev, ev) for ev in result.evidence_ids]}
    )


def _clone_plan_row(row: PlanRow, assessment_id: str) -> PlanRow:
    return PlanRow(
        assessment_id=assessment_id,
        incident_id=None,
        criterion_id=row.criterion_id,
        origen=row.origen,
        titulo=row.titulo,
        prioridad=row.prioridad,
        objetivo=row.objetivo,
        pasos=row.pasos,
        verificacion=row.verificacion,
        dependencias=row.dependencias,
        generado_por=row.generado_por,
        estado=row.estado,
        diagnostico_observable=row.diagnostico_observable,
        hipotesis=row.hipotesis,
        comprobaciones_seguras=row.comprobaciones_seguras,
        advertencia=row.advertencia,
    )


def _apply_selective_refresh(
    session: Session, methodology: Methodology, assessment: Assessment, previous: Assessment
) -> None:
    affected = {
        cid
        for cid, criterion in methodology.criterios.items()
        if _criterion_uses_surveillance(criterion)
    }
    # Lo no afectado se reusa tal cual (incluido lo derivado de IA): hereda con que se calculo.
    assessment.reproducibility = reproducibility.with_methodology(
        previous.reproducibility, methodology
    )

    # 1. Fuentes (trazabilidad) y evidencia base (todo menos vigilancia), con remapeo de ids.
    for source in previous.sources:
        session.add(
            Source(
                assessment_id=assessment.id,
                tipo=source.tipo,
                ruta=source.ruta,
                sha256=source.sha256,
            )
        )
    remap: dict[str, str] = {}
    for row in session.query(EvidenceRow).filter_by(assessment_id=previous.id).all():
        if row.type_id in SURVEILLANCE_EVIDENCE_TYPES:
            continue
        new_evidence_id = str(uuid4())
        remap[row.id] = new_evidence_id
        session.add(
            EvidenceRow(
                id=new_evidence_id,
                assessment_id=assessment.id,
                type_id=row.type_id,
                type_version=row.type_version,
                subject_type=row.subject_type,
                subject_ref=row.subject_ref,
                scope=row.scope,
                value=row.value,
                source_id=row.source_id,
                locator=row.locator,
                observed_at=row.observed_at,
                modality=row.modality,
                limitations=row.limitations,
                created_by=row.created_by,
            )
        )
    session.flush()

    # 2. Evidencia de vigilancia fresca (los log.pattern/log.window actuales del org+scope).
    fresh = collect_surveillance_evidence(session, assessment.org_id, assessment.scope)
    session.add_all(evidence_to_row(assessment.id, item) for item in fresh)
    session.flush()

    # 3. Resultados: copiar los NO afectados (remapeando su evidencia) y recalcular los afectados.
    for result in load_criterion_results(session, previous.id):
        if result.criterion_id in affected:
            continue
        session.add(result_to_row(assessment.id, _remap_result_evidence(result, remap)))
    session.flush()

    all_evidence = load_evidence(session, assessment.id)
    recomputed = engine.evaluate_only(methodology, all_evidence, sorted(affected))
    for result in recomputed:
        session.add(result_to_row(assessment.id, result))
    session.flush()

    # 4. Planes: copiar los de criterios NO afectados (conserva texto/estado, incluida la IA) y
    #    regenerar (plantilla) solo los afectados, preservando su estado de seguimiento.
    previous_estado: dict[str, str] = {}
    for row in session.query(PlanRow).filter_by(assessment_id=previous.id).all():
        previous_estado[row.criterion_id] = row.estado
        if row.criterion_id in affected:
            continue
        session.add(_clone_plan_row(row, assessment.id))
    for plan in recommendations_plans.generate_plans(methodology, recomputed):
        new_row = plan_to_row(plan, assessment_id=assessment.id)
        if new_row.criterion_id in previous_estado:
            new_row.estado = previous_estado[new_row.criterion_id]
        session.add(new_row)
    session.flush()
