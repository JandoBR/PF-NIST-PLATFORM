"""Orquesta una evaluacion: adaptadores + motor + persistencia (docs/04 §5-§6).

`create_pending_assessment`/`run_pending_assessment` separan "crear el registro" de "correr el
pipeline pesado" (docs/09 §16): la API encola lo segundo en `app/workers/core.py` via Redis en
vez de correrlo dentro del request. `run_assessment` sigue siendo el atajo sincronico que usan
la CLI y los tests -- hace ambas cosas en un solo paso, sin tocar la cola. `estado` ahora pasa
por `pendiente` -> `en_progreso` -> `completada`/`fallida`; antes solo distinguia las dos
ultimas porque todo corria en un solo paso sincronico.

`reevaluate`/`create_pending_reevaluation` implementan "nueva evaluacion heredando fuentes"
(docs/01 §10, docs/04 §5) re-leyendo las mismas rutas registradas en la evaluacion anterior, por
lo que una correccion aplicada a esos mismos archivos se refleja en la siguiente evaluacion.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.ansible.adapter import AnsibleAdapter
from app.adapters.documents.adapter import DocumentAdapter
from app.adapters.terraform.adapter import TerraformAdapter
from app.ai.client import AIClient, NullAIClient
from app.core import jobs as job_service
from app.core.queue import QUEUE_CORE, enqueue
from app.core.repository import (
    evidence_to_row,
    plan_to_row,
    result_to_row,
    row_to_evidence,
    row_to_plan,
    row_to_result,
)
from app.evaluation import aggregation, engine
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import (
    Assessment,
    CriterionResultRow,
    Event,
    EvidenceRow,
    Incident,
    Job,
    LogPatternRow,
    Organization,
    PlanRow,
    Source,
)
from app.ops.incidents import set_incident_estado, upsert_incident
from app.ops.plans import generate_incident_plan
from app.ops.triggers import evaluate_triggers
from app.recommendations import plans as recommendations_plans
from app.recommendations.plans import Plan
from app.schemas.evidence import EvidenceInstance, Locator, Modality
from app.surveillance.events import load_events_jsonl
from app.surveillance.patterns import detect_patterns


class AssessmentNotFoundError(Exception):
    pass


def _naive(moment: datetime) -> datetime:
    """SQLite descarta tzinfo al guardar `DateTime(timezone=True)`; normalizar antes de comparar."""

    return moment.replace(tzinfo=None)


def _hash_files(files: list[Path]) -> str:
    hasher = hashlib.sha256()
    for file_path in sorted(files):
        hasher.update(str(file_path).encode())
        hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def get_or_create_organization(session: Session, nombre: str) -> Organization:
    org = session.query(Organization).filter_by(nombre=nombre).one_or_none()
    if org is None:
        org = Organization(nombre=nombre)
        session.add(org)
        session.flush()
    return org


def _collect_surveillance_evidence(
    session: Session, org_id: str, scope: str
) -> list[EvidenceInstance]:
    """Evidencia `log.window`/`log.pattern` desde lo ya ingerido para este org/scope (docs/08 §3:
    "assessments consumen ventanas de events/log_patterns"). Nunca requiere una ruta de archivo:
    es implicito, no un adaptador que haya que invocar explicitamente.
    """

    events = session.query(Event).filter_by(org_id=org_id, scope=scope).all()
    if not events:
        return []

    desde = min(e.event_time for e in events)
    hasta = max(e.event_time for e in events)
    window = EvidenceInstance(
        type_id="log.window",
        type_version=1,
        subject_type="scope",
        subject_ref=scope,
        scope=scope,
        value={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "completo": True},
        source_id="surveillance:org",
        locator=Locator(event_id=f"{desde.isoformat()}..{hasta.isoformat()}"),
        observed_at=hasta,
        modality=Modality.OPERATIVA,
        created_by="surveillance",
    )

    patterns = session.query(LogPatternRow).filter_by(org_id=org_id, scope=scope).all()
    pattern_evidence = [
        EvidenceInstance(
            type_id="log.pattern",
            type_version=1,
            subject_type="scope",
            subject_ref=scope,
            scope=scope,
            value={
                "patron": p.patron,
                "resultado": p.resultado,
                "desde": p.desde.isoformat(),
                "hasta": p.hasta.isoformat(),
                "conteo": p.conteo,
            },
            source_id="surveillance:org",
            locator=Locator(event_id=p.id),
            observed_at=p.hasta,
            modality=Modality.OPERATIVA,
            created_by="surveillance",
        )
        for p in patterns
    ]
    return [window, *pattern_evidence]


def _collect_evidence_and_sources(
    session: Session,
    methodology: Methodology,
    org_id: str,
    terraform_path: Path | None,
    ansible_path: Path | None,
    documents_path: Path | None,
    scope: str,
    ai_client: AIClient | None,
) -> tuple[list[EvidenceInstance], list[Source]]:
    evidence: list[EvidenceInstance] = list(_collect_surveillance_evidence(session, org_id, scope))
    sources: list[Source] = []

    if terraform_path is not None:
        files = TerraformAdapter.list_files(terraform_path)
        sha256 = _hash_files(files)
        sources.append(Source(tipo="terraform", ruta=str(terraform_path), sha256=sha256))
        adapter = TerraformAdapter(source_id=f"assessment:terraform:{terraform_path}", scope=scope)
        evidence.extend(adapter.parse_path(terraform_path))

    if ansible_path is not None:
        files = AnsibleAdapter.list_files(ansible_path)
        sha256 = _hash_files(files)
        sources.append(Source(tipo="ansible", ruta=str(ansible_path), sha256=sha256))
        adapter = AnsibleAdapter(source_id=f"assessment:ansible:{ansible_path}", scope=scope)
        evidence.extend(adapter.parse_path(ansible_path))

    if documents_path is not None:
        files = DocumentAdapter.list_files(documents_path)
        sha256 = _hash_files(files)
        sources.append(Source(tipo="documents", ruta=str(documents_path), sha256=sha256))
        client = ai_client or NullAIClient()
        adapter = DocumentAdapter(
            client, methodology, source_id=f"assessment:documents:{documents_path}", scope=scope
        )
        tipos_solicitados = methodology.tipos_afirmacion_requeridos()
        evidence.extend(adapter.parse_path(documents_path, tipos_solicitados=tipos_solicitados))

    return evidence, sources


def create_pending_assessment(
    session: Session,
    methodology: Methodology,
    *,
    org_name: str,
    scope: str,
    previous_assessment_id: str | None = None,
) -> Assessment:
    """Crea el registro de `Assessment` sin ejecutar el pipeline todavia (docs/09 §16: la API
    ahora encola la ejecucion pesada en vez de correrla en el request). Se usa tanto para una
    evaluacion nueva como, con `create_pending_reevaluation`, para una reevaluacion.

    `previous_assessment_id` es la fuente de la herencia del estado de seguimiento de los planes
    (docs/05 §4.4). En una reevaluacion lo pasa `create_pending_reevaluation`; en una evaluacion
    nueva se autodetecta: la ultima evaluacion completada de la misma organizacion y scope, para que
    volver a evaluar el mismo entorno no pierda el avance. `None` si no hay ninguna previa."""

    org = get_or_create_organization(session, org_name)
    if previous_assessment_id is None:
        previous = (
            session.query(Assessment)
            .filter_by(org_id=org.id, scope=scope, estado="completada")
            .order_by(Assessment.creado_en.desc())
            .first()
        )
        previous_assessment_id = previous.id if previous is not None else None
    assessment = Assessment(
        org_id=org.id,
        estado="pendiente",
        methodology_version=methodology.methodology_version,
        scope=scope,
        previous_assessment_id=previous_assessment_id,
    )
    session.add(assessment)
    session.commit()
    return assessment


def run_pending_assessment(
    session: Session,
    methodology: Methodology,
    assessment_id: str,
    *,
    terraform_path: Path | None = None,
    ansible_path: Path | None = None,
    documents_path: Path | None = None,
    ai_client: AIClient | None = None,
    apply_ai_adjustment: bool = False,
    context: dict[str, Any] | None = None,
) -> Assessment:
    """Ejecuta el pipeline (adaptadores + motor + persistencia) contra un `Assessment` ya
    creado por `create_pending_assessment`. Esto es lo que corre `app/workers/core.py` por cada
    job `assessment_run`; `run_assessment` (abajo) sigue siendo el atajo sincronico que usa la
    CLI, implementado en terminos de esta misma funcion para no duplicar el pipeline."""

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError(assessment_id)

    assessment.estado = "en_progreso"
    session.commit()

    try:
        evidence, sources = _collect_evidence_and_sources(
            session,
            methodology,
            assessment.org_id,
            terraform_path,
            ansible_path,
            documents_path,
            assessment.scope,
            ai_client,
        )
        results = engine.evaluate_all(methodology, evidence)

        if apply_ai_adjustment and ai_client is not None:
            results = engine.apply_ai_adjustments(
                methodology, results, evidence, ai_client, context or {}
            )

        for source in sources:
            source.assessment_id = assessment.id
            session.add(source)
        for item in evidence:
            session.add(evidence_to_row(assessment.id, item))
        for result in results:
            session.add(result_to_row(assessment.id, result))

        assessment.estado = "completada"
        session.commit()
        # Los planes se generan solos al completar, con la plantilla determinista y sin IA
        # (docs/11 UI-02): el usuario no tiene que pedirlos. La IA sigue siendo explicita via
        # `POST /assessments/{id}/plans?use_ai=true`, que los recalcula.
        generate_plans(session, methodology, assessment.id)
    except Exception as exc:
        assessment.estado = "fallida"
        assessment.error = str(exc)
        session.commit()
        raise

    return assessment


def run_assessment(
    session: Session,
    methodology: Methodology,
    *,
    org_name: str,
    scope: str,
    terraform_path: Path | None = None,
    ansible_path: Path | None = None,
    documents_path: Path | None = None,
    ai_client: AIClient | None = None,
    apply_ai_adjustment: bool = False,
    context: dict[str, Any] | None = None,
) -> Assessment:
    """Atajo sincronico (CLI, tests): crea y ejecuta en un solo paso, sin pasar por la cola."""

    assessment = create_pending_assessment(session, methodology, org_name=org_name, scope=scope)
    return run_pending_assessment(
        session,
        methodology,
        assessment.id,
        terraform_path=terraform_path,
        ansible_path=ansible_path,
        documents_path=documents_path,
        ai_client=ai_client,
        apply_ai_adjustment=apply_ai_adjustment,
        context=context,
    )


def _resolve_previous_sources(previous: Assessment) -> dict[str, Path | None]:
    terraform_path: Path | None = None
    ansible_path: Path | None = None
    documents_path: Path | None = None
    for source in previous.sources:
        if source.tipo == "terraform":
            terraform_path = Path(source.ruta)
        elif source.tipo == "ansible":
            ansible_path = Path(source.ruta)
        elif source.tipo == "documents":
            documents_path = Path(source.ruta)
    return {
        "terraform_path": terraform_path,
        "ansible_path": ansible_path,
        "documents_path": documents_path,
    }


def create_pending_reevaluation(
    session: Session, methodology: Methodology, previous_assessment_id: str
) -> tuple[Assessment, dict[str, Path | None]]:
    """Version encolable de `reevaluate`: crea el nuevo `Assessment` (misma organizacion/scope
    que el anterior) y devuelve las rutas resueltas de sus fuentes, para que la ruta de la API
    pueda encolar un job `assessment_run` sin que el worker tenga que volver a mirar la
    evaluacion anterior."""

    previous = session.get(Assessment, previous_assessment_id)
    if previous is None:
        raise AssessmentNotFoundError(previous_assessment_id)

    paths = _resolve_previous_sources(previous)
    assessment = create_pending_assessment(
        session,
        methodology,
        org_name=previous.organization.nombre,
        scope=previous.scope,
        previous_assessment_id=previous.id,
    )
    return assessment, paths


def reevaluate(
    session: Session,
    methodology: Methodology,
    previous_assessment_id: str,
    *,
    ai_client: AIClient | None = None,
    apply_ai_adjustment: bool = False,
    context: dict[str, Any] | None = None,
) -> Assessment:
    """Atajo sincronico (CLI, tests): crea una nueva evaluacion re-leyendo las mismas rutas que
    la anterior, sin pasar por la cola."""

    assessment, paths = create_pending_reevaluation(
        session, methodology, previous_assessment_id
    )
    return run_pending_assessment(
        session,
        methodology,
        assessment.id,
        ai_client=ai_client,
        apply_ai_adjustment=apply_ai_adjustment,
        context=context,
        **paths,
    )


def enqueue_reevaluation(
    session: Session,
    methodology: Methodology,
    redis_client,
    previous_assessment_id: str,
    *,
    apply_ai_adjustment: bool = False,
    context: dict[str, Any] | None = None,
) -> tuple[Assessment, Job]:
    """Crea una reevaluacion y encola su `assessment_run` en la cola del core. Lo usan
    `POST /assessments/{id}/reevaluate` y el refresco automatico de madurez (docs/08 §8)."""

    assessment, paths = create_pending_reevaluation(session, methodology, previous_assessment_id)
    job = job_service.create_job(session, "assessment_run", assessment_id=assessment.id)
    enqueue(
        redis_client,
        QUEUE_CORE,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": str(paths["terraform_path"]) if paths["terraform_path"] else None,
            "ansible_path": str(paths["ansible_path"]) if paths["ansible_path"] else None,
            "documents_path": str(paths["documents_path"]) if paths["documents_path"] else None,
            "ai_requested": apply_ai_adjustment,
            "apply_ai_adjustment": apply_ai_adjustment,
            "context": context or {},
        },
    )
    return assessment, job


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

    assessment, _paths = create_pending_reevaluation(
        session, methodology, previous_assessment_id
    )
    job = job_service.create_job(session, "assessment_run", assessment_id=assessment.id)
    enqueue(
        redis_client,
        QUEUE_CORE,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "previous_assessment_id": previous_assessment_id,
            "selective_refresh": True,
            "ai_requested": False,
            "apply_ai_adjustment": False,
            "context": {},
        },
    )
    return assessment, job


#: Tipos de evidencia operativa (vigilancia). El refresco selectivo los recalcula; el resto de la
#: evidencia y de los resultados se reusa de la evaluacion anterior (docs/06 §6).
SURVEILLANCE_EVIDENCE_TYPES = frozenset({"log.pattern", "log.window"})


def _criterion_uses_surveillance(criterion) -> bool:
    return any(
        ev.split("@", 1)[0] in SURVEILLANCE_EVIDENCE_TYPES for ev in criterion.evidencias
    )


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
    fresh = _collect_surveillance_evidence(session, assessment.org_id, assessment.scope)
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


def load_criterion_results(session: Session, assessment_id: str) -> list[CriterionResult]:
    rows = session.query(CriterionResultRow).filter_by(assessment_id=assessment_id).all()
    return [row_to_result(row) for row in rows]


def load_evidence(session: Session, assessment_id: str) -> list[EvidenceInstance]:
    rows = session.query(EvidenceRow).filter_by(assessment_id=assessment_id).all()
    return [row_to_evidence(row) for row in rows]


def generate_plans(
    session: Session,
    methodology: Methodology,
    assessment_id: str,
    ai_client: AIClient | None = None,
) -> list[PlanRow]:
    """Genera los planes de un assessment (docs/05 §4). Idempotente: reemplaza los anteriores."""

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError(assessment_id)

    results = load_criterion_results(session, assessment_id)
    plans = recommendations_plans.generate_plans(methodology, results, client=ai_client)

    # Regenerar (p.ej. con IA) no debe perder el seguimiento ya hecho por el usuario (docs/05
    # §4.4): se conserva el `estado` de cada criterio que ya tenia plan.
    estados = {
        row.criterion_id: row.estado
        for row in session.query(PlanRow).filter_by(assessment_id=assessment_id).all()
    }
    # Primera generacion de una reevaluacion: hereda el estado de la evaluacion inmediatamente
    # anterior por criterio, para no perder el avance (docs/05 §4.4).
    if not estados and assessment.previous_assessment_id:
        estados = {
            row.criterion_id: row.estado
            for row in session.query(PlanRow)
            .filter_by(assessment_id=assessment.previous_assessment_id)
            .all()
        }
    session.query(PlanRow).filter_by(assessment_id=assessment_id).delete()
    rows = [plan_to_row(plan, assessment_id=assessment_id) for plan in plans]
    for row in rows:
        if row.criterion_id in estados:
            row.estado = estados[row.criterion_id]
    session.add_all(rows)
    session.commit()
    return rows


def set_plan_estado(
    session: Session, assessment_id: str, plan_id: str, estado: str
) -> PlanRow | None:
    """Cambia el estado de *seguimiento* de un plan (docs/05 §4.4, docs/11 UI-08). `None` si el
    plan no existe o no pertenece a ese assessment (la ruta ya valida el assessment/org)."""

    row = (
        session.query(PlanRow)
        .filter_by(id=plan_id, assessment_id=assessment_id)
        .one_or_none()
    )
    if row is None:
        return None
    row.estado = estado
    session.commit()
    return row


def load_plans(session: Session, assessment_id: str) -> list[Plan]:
    rows = session.query(PlanRow).filter_by(assessment_id=assessment_id).all()
    return [row_to_plan(row) for row in rows]


@dataclass
class IngestResult:
    org_id: str
    eventos_ingeridos: int
    nuevos_incidentes: list[Incident]
    incidentes_actualizados: list[Incident]
    #: Patrones (`log.pattern`) realmente nuevos por scope, es decir la evidencia que consume la
    #: madurez. Reingerir el mismo archivo da 0. Alimenta el refresco automatico (docs/08 §8).
    patrones_nuevos_por_scope: dict[str, int] = field(default_factory=dict)


def ingest_events(
    session: Session,
    methodology: Methodology,
    org_name: str,
    jsonl_path: Path,
    ai_client: AIClient | None = None,
) -> IngestResult:
    """Flujo B completo (docs/08 §1): eventos -> patrones -> disparadores -> incidentes -> planes.

    El flujo A (evidencia de madurez) no se recalcula aqui: la proxima vez que se corra
    `run_assessment` para este org/scope, `_collect_surveillance_evidence` ya vera los
    `log_patterns` persistidos ahora (docs/06 §6: "recalcular SOLO los criterios afectados" se
    logra simplemente evaluando una nueva assessment, nunca mutando una anterior).
    """

    org = get_or_create_organization(session, org_name)
    raw_events = load_events_jsonl(jsonl_path)

    por_scope: dict[str, list] = {}
    for evento in raw_events:
        por_scope.setdefault(evento.scope, []).append(evento)

    nuevos: list[Incident] = []
    actualizados: list[Incident] = []
    patrones_nuevos_por_scope: dict[str, int] = {}

    for scope, eventos in por_scope.items():
        ya_ingeridos = {
            row.event_id
            for row in session.query(Event.event_id).filter_by(org_id=org.id, scope=scope).all()
        }
        for evento in eventos:
            if evento.event_id in ya_ingeridos:
                continue  # mismo archivo reingerido: no duplicar filas append-only
            session.add(
                Event(
                    org_id=org.id,
                    scope=scope,
                    event_id=evento.event_id,
                    event_time=evento.event_time,
                    tipo=evento.tipo,
                    recurso=evento.recurso,
                    actor=evento.actor,
                    detalle=evento.detalle,
                    source_id=f"events:{jsonl_path}",
                )
            )
        session.flush()

        matches = detect_patterns(eventos, methodology.settings.vigilancia)
        # SQLite no conserva tzinfo en DateTime(timezone=True): se compara en naive UTC para
        # que el dedup no falle silenciosamente por un desajuste de tipo, no de valor.
        patrones_existentes = {
            (row.patron, _naive(row.desde), _naive(row.hasta), row.conteo)
            for row in session.query(LogPatternRow).filter_by(org_id=org.id, scope=scope).all()
        }
        agregados = 0
        for match in matches:
            clave = (match.patron, _naive(match.desde), _naive(match.hasta), match.conteo)
            if clave in patrones_existentes:
                continue  # mismo archivo reingerido: no duplicar el patron ya detectado
            session.add(
                LogPatternRow(
                    org_id=org.id,
                    scope=scope,
                    patron=match.patron,
                    resultado=match.resultado,
                    desde=match.desde,
                    hasta=match.hasta,
                    conteo=match.conteo,
                )
            )
            agregados += 1
        patrones_nuevos_por_scope[scope] = agregados
        session.flush()

        triggers = evaluate_triggers(matches, methodology.settings.vigilancia, scope)
        for trigger in triggers:
            incident, es_nuevo = upsert_incident(session, org.id, scope, trigger)
            (nuevos if es_nuevo else actualizados).append(incident)

            plan = generate_incident_plan(methodology, trigger, client=ai_client)
            session.query(PlanRow).filter_by(incident_id=incident.id).delete()
            session.add(plan_to_row(plan, incident_id=incident.id))

    session.commit()
    return IngestResult(
        org_id=org.id,
        eventos_ingeridos=len(raw_events),
        nuevos_incidentes=nuevos,
        incidentes_actualizados=actualizados,
        patrones_nuevos_por_scope=patrones_nuevos_por_scope,
    )


def list_incidents(session: Session, org_name: str) -> list[Incident]:
    org = session.query(Organization).filter_by(nombre=org_name).one_or_none()
    if org is None:
        return []
    return (
        session.query(Incident)
        .filter_by(org_id=org.id)
        .order_by(Incident.actualizado_en.desc())
        .all()
    )


def load_incident_plans(session: Session, incident_id: str) -> list[Plan]:
    rows = session.query(PlanRow).filter_by(incident_id=incident_id).all()
    return [row_to_plan(row) for row in rows]


def get_incident(session: Session, incident_id: str) -> Incident | None:
    return session.get(Incident, incident_id)


def update_incident_estado(
    session: Session, incident_id: str, estado: str
) -> Incident | None:
    """Cambia el estado y persiste (docs/11 UI-06/OP-04). `None` si el incidente no existe."""

    incident = session.get(Incident, incident_id)
    if incident is None:
        return None
    set_incident_estado(incident, estado)
    session.commit()
    return incident


def get_organization(session: Session, org_id: str) -> Organization | None:
    return session.get(Organization, org_id)


def list_organizations(session: Session) -> list[Organization]:
    return session.query(Organization).order_by(Organization.nombre).all()


def get_assessment(session: Session, assessment_id: str) -> Assessment | None:
    return session.get(Assessment, assessment_id)


def list_assessments(session: Session, *, org_id: str | None = None) -> list[Assessment]:
    """Si se pasa `org_id`, filtra por organizacion (doc 10 §4: cada usuario ve solo la suya)."""

    query = session.query(Assessment)
    if org_id is not None:
        query = query.filter_by(org_id=org_id)
    return query.order_by(Assessment.creado_en.desc()).all()


@dataclass
class CriterionDiff:
    criterion_id: str
    titulo: str
    estado_antes: str | None
    estado_despues: str | None
    score_antes: float | None
    score_despues: float | None

    @property
    def cambio(self) -> bool:
        return (self.estado_antes, self.score_antes) != (self.estado_despues, self.score_despues)


@dataclass
class ComparisonReport:
    assessment_id_a: str
    assessment_id_b: str
    diffs: list[CriterionDiff]
    global_antes: float | None
    global_despues: float | None

    @property
    def cambios(self) -> list[CriterionDiff]:
        return [d for d in self.diffs if d.cambio]


def compare(
    session: Session, methodology: Methodology, assessment_id_a: str, assessment_id_b: str
) -> ComparisonReport:
    for assessment_id in (assessment_id_a, assessment_id_b):
        if session.get(Assessment, assessment_id) is None:
            raise AssessmentNotFoundError(assessment_id)

    results_a = {r.criterion_id: r for r in load_criterion_results(session, assessment_id_a)}
    results_b = {r.criterion_id: r for r in load_criterion_results(session, assessment_id_b)}

    diffs = []
    for criterion_id in sorted(set(results_a) | set(results_b)):
        ra, rb = results_a.get(criterion_id), results_b.get(criterion_id)
        criterio = methodology.criterios.get(criterion_id)
        diffs.append(
            CriterionDiff(
                criterion_id=criterion_id,
                titulo=criterio.titulo if criterio else criterion_id,
                estado_antes=ra.estado.value if ra else None,
                estado_despues=rb.estado.value if rb else None,
                score_antes=ra.final_score if ra else None,
                score_despues=rb.final_score if rb else None,
            )
        )

    global_antes = _global_score(methodology, list(results_a.values()))
    global_despues = _global_score(methodology, list(results_b.values()))

    return ComparisonReport(
        assessment_id_a=assessment_id_a,
        assessment_id_b=assessment_id_b,
        diffs=diffs,
        global_antes=global_antes,
        global_despues=global_despues,
    )


def _global_score(methodology: Methodology, results: list[CriterionResult]) -> float | None:
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    return aggregation.aggregate_global(methodology, funciones).score
