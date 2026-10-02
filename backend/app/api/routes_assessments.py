"""POST/GET /assessments y sub-recursos (docs/04 §6).

`POST /assessments` y `POST /assessments/{id}/reevaluate` encolan el pipeline pesado en
`worker-core` en vez de correrlo dentro del request (docs/09 §16): crean el `Assessment` en
estado `pendiente`, encolan un job `assessment_run` y devuelven 202 con `job_id`. El cliente
sondea `GET /jobs/{job_id}` y, cuando `estado == "completado"`, pide `GET /assessments/{id}`
para el detalle real -- el `Job` nunca carga el resultado, solo estado/progreso/error.

Todas las rutas exigen sesion (doc 10) y la organizacion sale del usuario: `org_name` del
formulario se ignora, y un assessment de otra organizacion responde 404.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import redis
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai.client import build_default_client
from app.ai.guard import check_live_ai_guard
from app.api.deps import get_current_user, get_methodology, get_redis, get_session
from app.api.schemas import (
    AssessmentAccepted,
    AssessmentDetail,
    ComparisonDiffOut,
    ComparisonOut,
    PlanUpdate,
)
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core.queue import QUEUE_CORE, enqueue
from app.core.repository import row_to_plan
from app.evaluation import aggregation, tier
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import Assessment, User
from app.recommendations.findings import Finding, derive_findings
from app.recommendations.plans import PLAN_ESTADOS, Plan
from app.schemas.evidence import EvidenceInstance

router = APIRouter(tags=["assessments"])

#: Los archivos subidos se guardan aqui en vez de en un directorio temporal autolimpiado:
#: `reevaluate` re-lee la misma ruta mas tarde (docs/01 §10), asi que tiene que seguir existiendo
#: despues de que termine el request que la creo. Un directorio temporal con cleanup automatico
#: rompia `reevaluate` en produccion, no solo en los tests — se detecto con un test real.
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / ".data" / "uploads"


def _require_assessment(session: Session, assessment_id: str, user: User) -> Assessment:
    assessment = svc.get_assessment(session, assessment_id)
    if assessment is None or assessment.org_id != user.org_id:
        raise HTTPException(status_code=404, detail=f"No existe el assessment {assessment_id!r}.")
    return assessment


def _assessment_detail(
    session: Session, methodology: Methodology, assessment: Assessment
) -> AssessmentDetail:
    results = svc.load_criterion_results(session, assessment.id)
    categorias = aggregation.aggregate_by_categoria(methodology, results)
    funciones = aggregation.aggregate_by_funcion(methodology, results)
    glob = aggregation.aggregate_global(methodology, funciones)
    tier_estimate = tier.estimate_tier(methodology.settings.tier, results)

    return AssessmentDetail(
        id=assessment.id,
        org_id=assessment.org_id,
        org_nombre=assessment.organization.nombre,
        estado=assessment.estado,
        scope=assessment.scope,
        methodology_version=assessment.methodology_version,
        creado_en=assessment.creado_en,
        error=assessment.error,
        score_global=glob.score,
        cobertura_global=glob.cobertura,
        agregados_categoria=categorias,
        agregados_funcion=funciones,
        tier=tier_estimate,
    )


async def _save_uploads(files: list[UploadFile] | None, tipo: str) -> Path | None:
    if not files:
        return None
    upload_dir = UPLOADS_DIR / str(uuid4()) / tipo
    upload_dir.mkdir(parents=True, exist_ok=True)
    for upload in files:
        name = upload.filename or "archivo"
        content = await upload.read()
        (upload_dir / name).write_bytes(content)
    return upload_dir


@router.post("/assessments", response_model=AssessmentAccepted, status_code=202)
async def create_assessment(
    scope: str = Form("entorno:produccion"),
    ai_adjust: bool = Form(False),
    use_ai_for_documents: bool = Form(False),
    context: str = Form("{}"),
    confirm_live_ai: bool = Form(False),
    terraform_files: list[UploadFile] | None = File(None),
    ansible_files: list[UploadFile] | None = File(None),
    document_files: list[UploadFile] | None = File(None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
    redis_client: redis.Redis = Depends(get_redis),
) -> AssessmentAccepted:
    if not (terraform_files or ansible_files or document_files):
        raise HTTPException(
            status_code=422,
            detail=(
                "Se requiere al menos un archivo: terraform_files, ansible_files o"
                " document_files."
            ),
        )

    ai_requested = ai_adjust or (use_ai_for_documents and bool(document_files))
    guard_error = check_live_ai_guard(
        ai_requested, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai
    )
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)

    terraform_path = await _save_uploads(terraform_files, "terraform")
    ansible_path = await _save_uploads(ansible_files, "ansible")
    documents_path = await _save_uploads(document_files, "documents")

    # La organizacion sale de la sesion, nunca del formulario (doc 10 §4).
    assessment = svc.create_pending_assessment(
        session, methodology, org_name=user.organization.nombre, scope=scope
    )
    job = job_service.create_job(session, "assessment_run", assessment_id=assessment.id)
    enqueue(
        redis_client,
        QUEUE_CORE,
        {
            "job_id": job.id,
            "assessment_id": assessment.id,
            "terraform_path": str(terraform_path) if terraform_path else None,
            "ansible_path": str(ansible_path) if ansible_path else None,
            "documents_path": str(documents_path) if documents_path else None,
            "ai_requested": ai_requested,
            "apply_ai_adjustment": ai_adjust,
            "context": json.loads(context),
        },
    )

    return AssessmentAccepted(
        assessment_id=assessment.id,
        org_id=assessment.org_id,
        org_nombre=assessment.organization.nombre,
        job_id=job.id,
    )


@router.get("/assessments", response_model=list[AssessmentDetail])
def list_assessments(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> list[AssessmentDetail]:
    return [
        _assessment_detail(session, methodology, a)
        for a in svc.list_assessments(session, org_id=user.org_id)
    ]


@router.get("/assessments/{assessment_id}", response_model=AssessmentDetail)
def get_assessment(
    assessment_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> AssessmentDetail:
    assessment = _require_assessment(session, assessment_id, user)
    return _assessment_detail(session, methodology, assessment)


@router.get("/assessments/{assessment_id}/criteria", response_model=list[CriterionResult])
def get_criteria(
    assessment_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[CriterionResult]:
    _require_assessment(session, assessment_id, user)
    return svc.load_criterion_results(session, assessment_id)


@router.get("/assessments/{assessment_id}/evidence", response_model=list[EvidenceInstance])
def get_evidence(
    assessment_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[EvidenceInstance]:
    _require_assessment(session, assessment_id, user)
    return svc.load_evidence(session, assessment_id)


@router.get("/assessments/{assessment_id}/findings", response_model=list[Finding])
def get_findings(
    assessment_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> list[Finding]:
    _require_assessment(session, assessment_id, user)
    results = svc.load_criterion_results(session, assessment_id)
    return derive_findings(methodology, results)


@router.get("/assessments/{assessment_id}/plans", response_model=list[Plan])
def get_plans(
    assessment_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[Plan]:
    _require_assessment(session, assessment_id, user)
    return svc.load_plans(session, assessment_id)


@router.post("/assessments/{assessment_id}/plans", response_model=list[Plan])
def create_plans(
    assessment_id: str,
    use_ai: bool = False,
    confirm_live_ai: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> list[Plan]:
    _require_assessment(session, assessment_id, user)
    guard_error = check_live_ai_guard(use_ai, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai)
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)
    client = build_default_client() if use_ai else None

    svc.generate_plans(session, methodology, assessment_id, ai_client=client)
    return svc.load_plans(session, assessment_id)


@router.patch("/assessments/{assessment_id}/plans/{plan_id}", response_model=Plan)
def update_plan_estado(
    assessment_id: str,
    plan_id: str,
    payload: PlanUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Plan:
    """Estado de *seguimiento* del plan (docs/05 §4.4): no toca el puntaje del criterio."""
    _require_assessment(session, assessment_id, user)
    if payload.estado not in PLAN_ESTADOS:
        raise HTTPException(
            status_code=422,
            detail=f"Estado {payload.estado!r} invalido. Validos: {', '.join(PLAN_ESTADOS)}.",
        )
    row = svc.set_plan_estado(session, assessment_id, plan_id, payload.estado)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No existe el plan {plan_id!r} en esta evaluación."
        )
    return row_to_plan(row)


@router.post(
    "/assessments/{assessment_id}/reevaluate", response_model=AssessmentAccepted, status_code=202
)
def reevaluate_assessment(
    assessment_id: str,
    ai_adjust: bool = False,
    context: str = "{}",
    confirm_live_ai: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
    redis_client: redis.Redis = Depends(get_redis),
) -> AssessmentAccepted:
    _require_assessment(session, assessment_id, user)
    guard_error = check_live_ai_guard(
        ai_adjust, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai
    )
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)

    new_assessment, job = svc.enqueue_reevaluation(
        session,
        methodology,
        redis_client,
        assessment_id,
        apply_ai_adjustment=ai_adjust,
        context=json.loads(context),
    )

    return AssessmentAccepted(
        assessment_id=new_assessment.id,
        org_id=new_assessment.org_id,
        org_nombre=new_assessment.organization.nombre,
        job_id=job.id,
    )


@router.get("/assessments/{assessment_id}/compare/{other_id}", response_model=ComparisonOut)
def compare_assessments(
    assessment_id: str,
    other_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> ComparisonOut:
    _require_assessment(session, assessment_id, user)
    _require_assessment(session, other_id, user)
    report = svc.compare(session, methodology, assessment_id, other_id)
    return ComparisonOut(
        assessment_id_a=report.assessment_id_a,
        assessment_id_b=report.assessment_id_b,
        diffs=[
            ComparisonDiffOut(
                criterion_id=d.criterion_id,
                titulo=d.titulo,
                estado_antes=d.estado_antes,
                estado_despues=d.estado_despues,
                score_antes=d.score_antes,
                score_despues=d.score_despues,
                cambio=d.cambio,
            )
            for d in report.diffs
        ],
        global_antes=report.global_antes,
        global_despues=report.global_despues,
    )
