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
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.adapters.ansible.adapter import AnsibleAdapter
from app.adapters.documents.adapter import DocumentAdapter
from app.adapters.terraform.adapter import TerraformAdapter
from app.ai.client import AIClient, NullAIClient
from app.core import reproducibility
from app.core.dispatch import dispatch_job
from app.core.repository import (
    evidence_to_row,
    plan_to_row,
    result_to_row,
    row_to_evidence,
    row_to_plan,
    row_to_result,
)
from app.evaluation import contradictions, engine
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import (
    Assessment,
    CriterionResultRow,
    Event,
    EvidenceRow,
    Job,
    Organization,
    PlanRow,
    Source,
)
from app.recommendations import plans as recommendations_plans
from app.recommendations.plans import Plan
from app.schemas.evidence import EvidenceInstance, Locator, Modality
from app.surveillance.events import RawEvent
from app.surveillance.patterns import detect_patterns


class AssessmentNotFoundError(Exception):
    pass


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


def _origin_source_id(origenes: set[str] | list[str] | None) -> str:
    """`source_id` de la evidencia operativa: los origenes distintos, ordenados y unidos con `+`.
    Sin ninguno conocido (filas anteriores a FN-07) se conserva `surveillance:org`."""

    return "+".join(sorted(set(origenes))) if origenes else "surveillance:org"


def _naive(moment: datetime) -> datetime:
    """SQLite descarta tzinfo al guardar `DateTime(timezone=True)`; normalizar antes de comparar."""

    return moment.replace(tzinfo=None)


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass(frozen=True)
class EventSourceSummary:
    """Un origen de eventos (`Event.source_id`) disponible para una organizacion."""

    source_id: str
    scope: str
    eventos: int
    desde: datetime
    hasta: datetime
    ultima_ingesta: datetime | None


@dataclass(frozen=True)
class SurveillanceSnapshot:
    """Evidencia operativa de una seleccion de origenes, mas lo necesario para reproducirla.

    `source_ids` es la seleccion resuelta (todos los origenes del org+scope si se pidio "todas"),
    y `todas` distingue ese caso de una lista explicita: una reevaluacion hereda la seleccion
    explicita, pero una evaluacion que uso todos los origenes sigue viendo los nuevos.
    """

    evidence: list[EvidenceInstance]
    todas: bool
    source_ids: list[str]
    eventos: int
    desde: datetime | None
    hasta: datetime | None
    sha256: str


def list_event_sources(
    session: Session, org_id: str, scope: str | None = None
) -> list[EventSourceSummary]:
    """Origenes de eventos guardados del org (opcionalmente de un scope), con su rango y ultima
    ingesta. La ultima ingesta es `max(creado_en)`: no hay una fila de ingesta por origen, y el
    evento es lo unico que conserva cuando llego."""

    query = session.query(
        Event.source_id,
        Event.scope,
        func.count(Event.id),
        func.min(Event.event_time),
        func.max(Event.event_time),
        func.max(Event.creado_en),
    ).filter(Event.org_id == org_id)
    if scope is not None:
        query = query.filter(Event.scope == scope)
    rows = query.group_by(Event.source_id, Event.scope).order_by(Event.source_id).all()
    return [
        EventSourceSummary(
            source_id=source_id,
            scope=row_scope,
            eventos=conteo,
            desde=_as_utc(desde),
            hasta=_as_utc(hasta),
            ultima_ingesta=_as_utc(ultima) if ultima is not None else None,
        )
        for source_id, row_scope, conteo, desde, hasta, ultima in rows
    ]


def stored_event_rows(session: Session, org_id: str, scope: str, source_ids: list[str] | None):
    """Eventos guardados del org+scope, opcionalmente limitados a una seleccion de origenes."""

    query = session.query(Event).filter_by(org_id=org_id, scope=scope)
    if source_ids is not None:
        if not source_ids:
            return []
        query = query.filter(Event.source_id.in_(source_ids))
    rows = query.all()
    rows.sort(key=lambda r: (_naive(r.event_time), _naive(r.creado_en), r.event_id))
    return rows


def _raw_events(rows) -> list[RawEvent]:
    return [
        RawEvent(
            event_id=row.event_id,
            event_time=_as_utc(row.event_time),
            tipo=row.tipo,
            recurso=row.recurso,
            scope=row.scope,
            actor=row.actor,
            detalle=row.detalle or {},
            fuente=row.source_id,
        )
        for row in rows
    ]


def _events_sha256(rows) -> str:
    """Hash canonico de los eventos seleccionados (orden por tiempo e id, JSON estable)."""

    hasher = hashlib.sha256()
    for row in rows:
        payload = {
            "event_id": row.event_id,
            "event_time": _as_utc(row.event_time).isoformat(),
            "tipo": row.tipo,
            "recurso": row.recurso,
            "actor": row.actor,
            "detalle": row.detalle or {},
            "source_id": row.source_id,
        }
        hasher.update(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        )
        hasher.update(b"\n")
    return hasher.hexdigest()


def surveillance_snapshot(
    session: Session,
    org_id: str,
    scope: str,
    settings,
    source_ids: list[str] | None = None,
) -> SurveillanceSnapshot:
    """Evidencia `log.window`/`log.pattern` desde una seleccion de origenes de eventos.

    Los patrones se recalculan en memoria sobre los eventos seleccionados con el mismo codigo
    determinista de la ingesta, en vez de leer `log_patterns`: asi una evaluacion de un subconjunto
    no arrastra patrones de otra fuente, la correlacion entre fuentes seleccionadas sigue siendo
    correcta y una fila duplicada o vieja no puede decidir un criterio (docs/08 §3, docs/09 §98).
    """

    todas = source_ids is None
    rows = stored_event_rows(session, org_id, scope, source_ids)
    if todas:
        seleccionados = sorted({row.source_id for row in rows})
    else:
        seleccionados = sorted(set(source_ids))

    eventos = _raw_events(rows)
    desde = eventos[0].event_time if eventos else None
    hasta = eventos[-1].event_time if eventos else None
    sha256 = _events_sha256(rows)

    evidence: list[EvidenceInstance] = []
    if eventos:
        evidence.append(
            EvidenceInstance(
                type_id="log.window",
                type_version=1,
                subject_type="scope",
                subject_ref=scope,
                scope=scope,
                value={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "completo": True},
                source_id=_origin_source_id(seleccionados),
                locator=Locator(event_id=f"{desde.isoformat()}..{hasta.isoformat()}"),
                observed_at=hasta,
                modality=Modality.OPERATIVA,
                created_by="surveillance",
            )
        )

        fuentes = {evento.event_id: evento.fuente for evento in eventos}
        for match in detect_patterns(eventos, settings):
            fuentes_match = sorted(
                {fuentes[event_id] for event_id in match.event_ids if fuentes.get(event_id)}
            )
            evidence.append(
                EvidenceInstance(
                    type_id="log.pattern",
                    type_version=2,
                    subject_type="scope",
                    subject_ref=scope,
                    scope=scope,
                    value={
                        "patron": match.patron,
                        "resultado": match.resultado,
                        "desde": match.desde.isoformat(),
                        "hasta": match.hasta.isoformat(),
                        "conteo": match.conteo,
                        "fuentes": fuentes_match,
                    },
                    source_id=_origin_source_id(fuentes_match),
                    locator=Locator(event_id=f"{match.patron}:{match.desde.isoformat()}"),
                    observed_at=match.hasta,
                    modality=Modality.OPERATIVA,
                    created_by="surveillance",
                )
            )

    return SurveillanceSnapshot(
        evidence=evidence,
        todas=todas,
        source_ids=seleccionados,
        eventos=len(rows),
        desde=desde,
        hasta=hasta,
        sha256=sha256,
    )


def collect_surveillance_evidence(
    session: Session,
    org_id: str,
    scope: str,
    settings,
    source_ids: list[str] | None = None,
) -> list[EvidenceInstance]:
    """Evidencia operativa de una seleccion de origenes (todos si `source_ids` es `None`)."""

    return surveillance_snapshot(session, org_id, scope, settings, source_ids).evidence


def _eventos_entry(snapshot: SurveillanceSnapshot) -> dict[str, Any]:
    return {
        "todas": snapshot.todas,
        "source_ids": snapshot.source_ids,
        "conteo": snapshot.eventos,
        "desde": snapshot.desde.isoformat() if snapshot.desde else None,
        "hasta": snapshot.hasta.isoformat() if snapshot.hasta else None,
        "sha256": snapshot.sha256,
    }


def _collect_evidence_and_sources(
    session: Session,
    methodology: Methodology,
    org_id: str,
    terraform_path: Path | None,
    ansible_path: Path | None,
    documents_path: Path | None,
    scope: str,
    ai_client: AIClient | None,
    event_source_ids: list[str] | None = None,
) -> tuple[list[EvidenceInstance], list[Source], SurveillanceSnapshot]:
    snapshot = surveillance_snapshot(
        session,
        org_id,
        scope,
        methodology.settings.vigilancia,
        event_source_ids,
    )
    evidence: list[EvidenceInstance] = list(snapshot.evidence)
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

    return evidence, sources, snapshot


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


def _cap_contradicted(
    session: Session,
    assessment: Assessment,
    results: list[CriterionResult],
    evidence: list[EvidenceInstance],
) -> list[CriterionResult]:
    """Un criterio con contradiccion sin resolver no puede subir el puntaje respecto a la
    evaluacion anterior del mismo org+scope (docs/02 §5, docs/09 §42)."""

    previous_id = assessment.previous_assessment_id
    if previous_id is None:
        return results
    current = contradictions.detect(evidence)
    if not current:
        return results
    previous_scores = {
        r.criterion_id: r.final_score for r in load_criterion_results(session, previous_id)
    }
    return contradictions.cap_contradicted(results, current, previous_scores)


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
    event_source_ids: list[str] | None = None,
) -> Assessment:
    """Ejecuta el pipeline (adaptadores + motor + persistencia) contra un `Assessment` ya
    creado por `create_pending_assessment`. Esto es lo que corre `app/workers/core.py` por cada
    job `assessment_run`; `run_assessment` (abajo) sigue siendo el atajo sincronico que usa la
    CLI, implementado en terminos de esta misma funcion para no duplicar el pipeline.

    `event_source_ids` limita la evidencia operativa a esos origenes (`Event.source_id`); `None`
    significa todos los del org+scope (docs/08 §3, docs/09 §98)."""

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError(assessment_id)

    assessment.estado = "en_progreso"
    # La version se fija cuando el worker ejecuta, no cuando la API encola: si la metodologia
    # cambio entre ambos, la fila debe reflejar la que realmente calculo (docs/01 §10).
    assessment.methodology_version = methodology.methodology_version
    session.commit()

    try:
        evidence, sources, snapshot = _collect_evidence_and_sources(
            session,
            methodology,
            assessment.org_id,
            terraform_path,
            ansible_path,
            documents_path,
            assessment.scope,
            ai_client,
            event_source_ids,
        )
        results = engine.evaluate_all(methodology, evidence)
        assessment.reproducibility = reproducibility.with_eventos(
            reproducibility.build(
                methodology=methodology,
                terraform=terraform_path is not None,
                ansible=ansible_path is not None,
                documents=documents_path is not None,
                ai_client=ai_client,
                ai_adjustment=apply_ai_adjustment,
            ),
            _eventos_entry(snapshot),
        )

        if apply_ai_adjustment and ai_client is not None:
            results = engine.apply_ai_adjustments(
                methodology, results, evidence, ai_client, context or {}
            )
        results = _cap_contradicted(session, assessment, results, evidence)

        for source in sources:
            source.assessment_id = assessment.id
            session.add(source)
        for item in evidence:
            session.add(evidence_to_row(assessment.id, item))
        for result in results:
            session.add(result_to_row(assessment.id, result))

        # Los planes se generan antes de publicar `completada`, con la plantilla determinista y
        # sin IA (docs/11 UI-02): nadie debe ver una evaluacion completada con cero planes.
        generate_plans(session, methodology, assessment.id)
        assessment.estado = "completada"
        session.commit()
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
    event_source_ids: list[str] | None = None,
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
        event_source_ids=event_source_ids,
    )


def has_documents(session: Session, assessment_id: str) -> bool:
    """Si la evaluacion tiene una fuente documental (para pedir U1 al reevaluar)."""

    return (
        session.query(Source).filter_by(assessment_id=assessment_id, tipo="documents").first()
        is not None
    )


def event_source_selection(assessment: Assessment) -> list[str] | None:
    """Seleccion de origenes que uso una evaluacion, para heredarla (docs/09 §98).

    `None` si uso todos los origenes del org+scope (o si es anterior a esta funcion): asi una
    reevaluacion sigue viendo los origenes nuevos. Una lista explicita se conserva tal cual.
    """

    eventos = (assessment.reproducibility or {}).get("eventos") or {}
    if not eventos or eventos.get("todas", True):
        return None
    return list(eventos.get("source_ids") or [])


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
    la anterior, sin pasar por la cola. La seleccion de origenes de eventos tambien se hereda."""

    previous = session.get(Assessment, previous_assessment_id)
    selection = event_source_selection(previous) if previous is not None else None
    assessment, paths = create_pending_reevaluation(session, methodology, previous_assessment_id)
    return run_pending_assessment(
        session,
        methodology,
        assessment.id,
        ai_client=ai_client,
        apply_ai_adjustment=apply_ai_adjustment,
        context=context,
        event_source_ids=selection,
        **paths,
    )


def enqueue_reevaluation(
    session: Session,
    methodology: Methodology,
    redis_client,
    previous_assessment_id: str,
    *,
    apply_ai_adjustment: bool = False,
    request_documents_ai: bool = False,
    context: dict[str, Any] | None = None,
) -> tuple[Assessment, Job]:
    """Crea una reevaluacion y encola su `assessment_run` en la cola del core. Lo usan
    `POST /assessments/{id}/reevaluate`, el refresco automatico de madurez (docs/08 §8) y el
    fallback del refresco cuando cambia la metodologia. Hereda la seleccion de origenes de
    eventos de la evaluacion anterior (docs/09 §98)."""

    previous = session.get(Assessment, previous_assessment_id)
    event_source_ids = event_source_selection(previous) if previous is not None else None
    assessment, paths = create_pending_reevaluation(session, methodology, previous_assessment_id)
    job = dispatch_job(
        session,
        redis_client,
        "assessment_run",
        {
            "assessment_id": assessment.id,
            "terraform_path": str(paths["terraform_path"]) if paths["terraform_path"] else None,
            "ansible_path": str(paths["ansible_path"]) if paths["ansible_path"] else None,
            "documents_path": str(paths["documents_path"]) if paths["documents_path"] else None,
            # U1 se necesita si hay documentos: sin IA, la reevaluacion perderia todos los
            # `doc.claim` de la evaluacion anterior (docs/09 §74).
            "ai_requested": apply_ai_adjustment or request_documents_ai,
            "apply_ai_adjustment": apply_ai_adjustment,
            "context": context or {},
            "event_source_ids": event_source_ids,
        },
        assessment_id=assessment.id,
    )
    return assessment, job


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
    if ai_client is not None:
        assessment.reproducibility = reproducibility.with_plans_ai(
            assessment.reproducibility, ai_client
        )
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

    row = session.query(PlanRow).filter_by(id=plan_id, assessment_id=assessment_id).one_or_none()
    if row is None:
        return None
    row.estado = estado
    session.commit()
    return row


def load_plans(session: Session, assessment_id: str) -> list[Plan]:
    rows = session.query(PlanRow).filter_by(assessment_id=assessment_id).all()
    return [row_to_plan(row) for row in rows]


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
