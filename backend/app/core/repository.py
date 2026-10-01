"""Conversion entre los contratos Pydantic (app/schemas, app/evaluation) y las filas ORM."""

from __future__ import annotations

from app.evaluation.schemas import CriterionResult, Estado
from app.models.tables import CriterionResultRow, EvidenceRow
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def evidence_to_row(assessment_id: str, evidence: EvidenceInstance) -> EvidenceRow:
    return EvidenceRow(
        id=evidence.id,
        assessment_id=assessment_id,
        type_id=evidence.type_id,
        type_version=evidence.type_version,
        subject_type=evidence.subject_type,
        subject_ref=evidence.subject_ref,
        scope=evidence.scope,
        value=evidence.value,
        source_id=evidence.source_id,
        locator=evidence.locator.model_dump(),
        observed_at=evidence.observed_at,
        modality=evidence.modality.value,
        limitations=evidence.limitations,
        created_by=evidence.created_by,
    )


def row_to_evidence(row: EvidenceRow) -> EvidenceInstance:
    return EvidenceInstance(
        id=row.id,
        type_id=row.type_id,
        type_version=row.type_version,
        subject_type=row.subject_type,
        subject_ref=row.subject_ref,
        scope=row.scope,
        value=row.value,
        source_id=row.source_id,
        locator=Locator.model_validate(row.locator),
        observed_at=row.observed_at,
        modality=Modality(row.modality),
        limitations=row.limitations,
        created_by=row.created_by,
    )


def result_to_row(assessment_id: str, result: CriterionResult) -> CriterionResultRow:
    return CriterionResultRow(
        assessment_id=assessment_id,
        criterion_id=result.criterion_id,
        criterion_version=result.criterion_version,
        estado=result.estado.value,
        base_score=result.base_score,
        final_score=result.final_score,
        explanation=result.explanation,
        evidence_ids=result.evidence_ids,
    )


def row_to_result(row: CriterionResultRow) -> CriterionResult:
    return CriterionResult(
        criterion_id=row.criterion_id,
        criterion_version=row.criterion_version,
        estado=Estado(row.estado),
        base_score=row.base_score,
        final_score=row.final_score,
        explanation=row.explanation,
        evidence_ids=row.evidence_ids,
    )
