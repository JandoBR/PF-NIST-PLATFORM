"""POST/GET /assessments y sub-recursos (docs/04 §6), fusionando crear+subir+ejecutar en un
solo endpoint sincronico — ver docs/09 §13 para la decision (sin Redis, no hay job_id real que
devolver todavia).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai.client import build_default_client
from app.ai.guard import check_live_ai_guard
from app.api.deps import get_methodology, get_session
from app.api.schemas import AssessmentDetail, ComparisonDiffOut, ComparisonOut
from app.core import assessment_service as svc
from app.evaluation import aggregation, tier
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import Assessment
from app.recommendations.findings import Finding, derive_findings
from app.recommendations.plans import Plan
from app.schemas.evidence import EvidenceInstance

router = APIRouter(tags=["assessments"])

#: Los archivos subidos se guardan aqui en vez de en un directorio temporal autolimpiado:
#: `reevaluate` re-lee la misma ruta mas tarde (docs/01 §10), asi que tiene que seguir existiendo
#: despues de que termine el request que la creo. Un directorio temporal con cleanup automatico
#: rompia `reevaluate` en produccion, no solo en los tests — se detecto con un test real.
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / ".data" / "uploads"


def _require_assessment(session: Session, assessment_id: str) -> Assessment:
    assessment = svc.get_assessment(session, assessment_id)
    if assessment is None:
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


@router.post("/assessments", response_model=AssessmentDetail)
async def create_assessment(
    org_name: str = Form(...),
    scope: str = Form("entorno:produccion"),
    ai_adjust: bool = Form(False),
    use_ai_for_documents: bool = Form(False),
    context: str = Form("{}"),
    confirm_live_ai: bool = Form(False),
    terraform_files: list[UploadFile] | None = File(None),
    ansible_files: list[UploadFile] | None = File(None),
    document_files: list[UploadFile] | None = File(None),
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> AssessmentDetail:
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
    client = build_default_client() if ai_requested else None

    terraform_path = await _save_uploads(terraform_files, "terraform")
    ansible_path = await _save_uploads(ansible_files, "ansible")
    documents_path = await _save_uploads(document_files, "documents")

    assessment = svc.run_assessment(
        session,
        methodology,
        org_name=org_name,
        scope=scope,
        terraform_path=terraform_path,
        ansible_path=ansible_path,
        documents_path=documents_path,
        ai_client=client,
        apply_ai_adjustment=ai_adjust,
        context=json.loads(context),
    )

    return _assessment_detail(session, methodology, assessment)


@router.get("/assessments", response_model=list[AssessmentDetail])
def list_assessments(
    session: Session = Depends(get_session), methodology: Methodology = Depends(get_methodology)
) -> list[AssessmentDetail]:
    return [
        _assessment_detail(session, methodology, a) for a in svc.list_assessments(session)
    ]


@router.get("/assessments/{assessment_id}", response_model=AssessmentDetail)
def get_assessment(
    assessment_id: str,
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> AssessmentDetail:
    assessment = _require_assessment(session, assessment_id)
    return _assessment_detail(session, methodology, assessment)


@router.get("/assessments/{assessment_id}/criteria", response_model=list[CriterionResult])
def get_criteria(
    assessment_id: str, session: Session = Depends(get_session)
) -> list[CriterionResult]:
    _require_assessment(session, assessment_id)
    return svc.load_criterion_results(session, assessment_id)


@router.get("/assessments/{assessment_id}/evidence", response_model=list[EvidenceInstance])
def get_evidence(
    assessment_id: str, session: Session = Depends(get_session)
) -> list[EvidenceInstance]:
    _require_assessment(session, assessment_id)
    return svc.load_evidence(session, assessment_id)


@router.get("/assessments/{assessment_id}/findings", response_model=list[Finding])
def get_findings(
    assessment_id: str,
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> list[Finding]:
    _require_assessment(session, assessment_id)
    results = svc.load_criterion_results(session, assessment_id)
    return derive_findings(methodology, results)


@router.get("/assessments/{assessment_id}/plans", response_model=list[Plan])
def get_plans(assessment_id: str, session: Session = Depends(get_session)) -> list[Plan]:
    _require_assessment(session, assessment_id)
    return svc.load_plans(session, assessment_id)


@router.post("/assessments/{assessment_id}/plans", response_model=list[Plan])
def create_plans(
    assessment_id: str,
    use_ai: bool = False,
    confirm_live_ai: bool = False,
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> list[Plan]:
    guard_error = check_live_ai_guard(use_ai, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai)
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)
    client = build_default_client() if use_ai else None

    svc.generate_plans(session, methodology, assessment_id, ai_client=client)
    return svc.load_plans(session, assessment_id)


@router.post("/assessments/{assessment_id}/reevaluate", response_model=AssessmentDetail)
def reevaluate_assessment(
    assessment_id: str,
    ai_adjust: bool = False,
    context: str = "{}",
    confirm_live_ai: bool = False,
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> AssessmentDetail:
    guard_error = check_live_ai_guard(
        ai_adjust, os.environ.get("DEEPSEEK_API_KEY"), confirm_live_ai
    )
    if guard_error:
        raise HTTPException(status_code=409, detail=guard_error)
    client = build_default_client() if ai_adjust else None

    new_assessment = svc.reevaluate(
        session,
        methodology,
        assessment_id,
        ai_client=client,
        apply_ai_adjustment=ai_adjust,
        context=json.loads(context),
    )
    return _assessment_detail(session, methodology, new_assessment)


@router.get("/assessments/{assessment_id}/compare/{other_id}", response_model=ComparisonOut)
def compare_assessments(
    assessment_id: str,
    other_id: str,
    session: Session = Depends(get_session),
    methodology: Methodology = Depends(get_methodology),
) -> ComparisonOut:
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
