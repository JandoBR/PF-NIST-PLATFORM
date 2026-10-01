"""Orquesta una evaluacion: adaptadores + motor + persistencia (docs/04 §5-§6).

Sin cola de trabajos todavia: cada evaluacion corre sincronicamente en un solo proceso
(docs/04 §10, "ejecucion sincrona de respaldo" sin Redis). `estado` solo distingue
`completada` de `fallida`; los estados intermedios del ciclo de vida completo llegan
cuando exista el worker.

`reevaluate` implementa "nueva evaluacion heredando fuentes" (docs/01 §10, docs/04 §5)
re-leyendo las mismas rutas registradas en la evaluacion anterior, por lo que una
correccion aplicada a esos mismos archivos se refleja en la siguiente evaluacion.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.documents.adapter import DocumentAdapter
from app.adapters.terraform.adapter import TerraformAdapter
from app.ai.client import AIClient, NullAIClient
from app.core.repository import evidence_to_row, result_to_row, row_to_result
from app.evaluation import aggregation, engine
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.models.tables import Assessment, CriterionResultRow, Organization, Source
from app.schemas.evidence import EvidenceInstance


class AssessmentNotFoundError(Exception):
    pass


def _hash_files(files: list[Path]) -> str:
    hasher = hashlib.sha256()
    for file_path in sorted(files):
        hasher.update(str(file_path).encode())
        hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def _get_or_create_organization(session: Session, nombre: str) -> Organization:
    org = session.query(Organization).filter_by(nombre=nombre).one_or_none()
    if org is None:
        org = Organization(nombre=nombre)
        session.add(org)
        session.flush()
    return org


def _collect_evidence_and_sources(
    methodology: Methodology,
    terraform_path: Path | None,
    documents_path: Path | None,
    scope: str,
    ai_client: AIClient | None,
) -> tuple[list[EvidenceInstance], list[Source]]:
    evidence: list[EvidenceInstance] = []
    sources: list[Source] = []

    if terraform_path is not None:
        files = TerraformAdapter.list_files(terraform_path)
        sha256 = _hash_files(files)
        sources.append(Source(tipo="terraform", ruta=str(terraform_path), sha256=sha256))
        adapter = TerraformAdapter(source_id=f"assessment:terraform:{terraform_path}", scope=scope)
        evidence.extend(adapter.parse_path(terraform_path))

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


def run_assessment(
    session: Session,
    methodology: Methodology,
    *,
    org_name: str,
    scope: str,
    terraform_path: Path | None = None,
    documents_path: Path | None = None,
    ai_client: AIClient | None = None,
) -> Assessment:
    org = _get_or_create_organization(session, org_name)
    assessment = Assessment(
        org_id=org.id,
        estado="creada",
        methodology_version=methodology.methodology_version,
        scope=scope,
    )
    session.add(assessment)
    session.flush()

    try:
        evidence, sources = _collect_evidence_and_sources(
            methodology, terraform_path, documents_path, scope, ai_client
        )
        results = engine.evaluate_all(methodology, evidence)

        for source in sources:
            source.assessment_id = assessment.id
            session.add(source)
        for item in evidence:
            session.add(evidence_to_row(assessment.id, item))
        for result in results:
            session.add(result_to_row(assessment.id, result))

        assessment.estado = "completada"
    except Exception as exc:
        assessment.estado = "fallida"
        assessment.error = str(exc)
        session.commit()
        raise

    session.commit()
    return assessment


def reevaluate(
    session: Session,
    methodology: Methodology,
    previous_assessment_id: str,
    *,
    ai_client: AIClient | None = None,
) -> Assessment:
    """Crea una nueva evaluacion re-leyendo las mismas rutas que la anterior."""

    previous = session.get(Assessment, previous_assessment_id)
    if previous is None:
        raise AssessmentNotFoundError(previous_assessment_id)

    terraform_path: Path | None = None
    documents_path: Path | None = None
    for source in previous.sources:
        if source.tipo == "terraform":
            terraform_path = Path(source.ruta)
        elif source.tipo == "documents":
            documents_path = Path(source.ruta)

    return run_assessment(
        session,
        methodology,
        org_name=previous.organization.nombre,
        scope=previous.scope,
        terraform_path=terraform_path,
        documents_path=documents_path,
        ai_client=ai_client,
    )


def load_criterion_results(session: Session, assessment_id: str) -> list[CriterionResult]:
    rows = session.query(CriterionResultRow).filter_by(assessment_id=assessment_id).all()
    return [row_to_result(row) for row in rows]


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
