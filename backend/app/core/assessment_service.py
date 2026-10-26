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
from pathlib import Path
from typing import Any

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
    LogPatternRow,
    Organization,
    PlanRow,
    Source,
)
from app.recommendations import plans as recommendations_plans
from app.recommendations.plans import Plan
from app.schemas.evidence import EvidenceInstance, Locator, Modality


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


def collect_surveillance_evidence(
    session: Session, org_id: str, scope: str
) -> list[EvidenceInstance]:
    """Evidencia `log.window`/`log.pattern` desde lo ya ingerido para este org/scope (docs/08 §3:
    "assessments consumen ventanas de events/log_patterns"). Nunca requiere una ruta de archivo:
    es implicito, no un adaptador que haya que invocar explicitamente.
    """

    events = session.query(Event).filter_by(org_id=org_id, scope=scope).all()
    if not events:
        return []
    origenes_ventana = {e.source_id for e in events}

    desde = min(e.event_time for e in events)
    hasta = max(e.event_time for e in events)
    window = EvidenceInstance(
        type_id="log.window",
        type_version=1,
        subject_type="scope",
        subject_ref=scope,
        scope=scope,
        value={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "completo": True},
        source_id=_origin_source_id(origenes_ventana),
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
            source_id=_origin_source_id(p.fuentes),
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
    evidence: list[EvidenceInstance] = list(collect_surveillance_evidence(session, org_id, scope))
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
) -> Assessment:
    """Ejecuta el pipeline (adaptadores + motor + persistencia) contra un `Assessment` ya
    creado por `create_pending_assessment`. Esto es lo que corre `app/workers/core.py` por cada
    job `assessment_run`; `run_assessment` (abajo) sigue siendo el atajo sincronico que usa la
    CLI, implementado en terminos de esta misma funcion para no duplicar el pipeline."""

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError(assessment_id)

    assessment.estado = "en_progreso"
    # La version se fija cuando el worker ejecuta, no cuando la API encola: si la metodologia
    # cambio entre ambos, la fila debe reflejar la que realmente calculo (docs/01 §10).
    assessment.methodology_version = methodology.methodology_version
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
        assessment.reproducibility = reproducibility.build(
            terraform=terraform_path is not None,
            ansible=ansible_path is not None,
            documents=documents_path is not None,
            ai_client=ai_client,
            ai_adjustment=apply_ai_adjustment,
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


def has_documents(session: Session, assessment_id: str) -> bool:
    """Si la evaluacion tiene una fuente documental (para pedir U1 al reevaluar)."""

    return (
        session.query(Source).filter_by(assessment_id=assessment_id, tipo="documents").first()
        is not None
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

    assessment, paths = create_pending_reevaluation(session, methodology, previous_assessment_id)
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
    request_documents_ai: bool = False,
    context: dict[str, Any] | None = None,
) -> tuple[Assessment, Job]:
    """Crea una reevaluacion y encola su `assessment_run` en la cola del core. Lo usan
    `POST /assessments/{id}/reevaluate`, el refresco automatico de madurez (docs/08 §8) y el
    fallback del refresco cuando cambia la metodologia."""

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
