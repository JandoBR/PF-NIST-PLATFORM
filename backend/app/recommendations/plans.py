"""Hallazgos -> planes priorizados (docs/05 §4, docs/04 §3: `recommendations` depende de
`evaluation` y `ai`, nunca al reves).

Simplificado a proposito: la prioridad viene solo de la severidad del hallazgo (score), sin
ponderar criticidad de activo todavia (eso exige `ctx.profile`, que no existe como pipeline
aun) -- por eso `prioridad` es literalmente `finding.severidad`. La IA nunca decide la
prioridad, solo redacta objetivo/pasos/verificacion (U3, docs/05 §4.1).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ai.client import AIClient, NullAIClient
from app.ai.plan_generation import generate_plan_content
from app.evaluation.schemas import CriterionResult
from app.methodology.loader import Methodology
from app.recommendations.findings import Finding, derive_findings

#: Estado de seguimiento de un plan (docs/05 §4.4, docs/11 UI-08). Es puramente informativo para el
#: usuario y NO afecta el puntaje: un criterio se considera implementado por su evidencia.
PLAN_ESTADOS = ("pendiente", "en_progreso", "hecho")


class Plan(BaseModel):
    #: `id`/`estado` solo existen una vez persistido el plan; `None`/"pendiente" para uno recien
    #: generado en memoria (docs/05 §4.4).
    id: str | None = None
    criterion_id: str
    titulo: str
    prioridad: str
    objetivo: str
    pasos: list[str]
    verificacion: str
    dependencias: list[str]
    generado_por: str
    estado: str = "pendiente"
    #: Solo presentes en planes de incidente (docs/08 §7); vacios/None en planes de criterio.
    origen: str = "criterio"
    diagnostico_observable: str | None = None
    hipotesis: list[str] = Field(default_factory=list)
    comprobaciones_seguras: list[str] = Field(default_factory=list)
    advertencia: str | None = None


def _build_plan(methodology: Methodology, client: AIClient, finding: Finding) -> Plan:
    criterion = methodology.criterios[finding.criterion_id]
    content = generate_plan_content(
        client,
        criterion,
        severidad=finding.severidad,
        score=finding.score,
        evidence_ids=finding.evidence_ids,
    )
    return Plan(
        criterion_id=finding.criterion_id,
        titulo=content.titulo,
        prioridad=finding.severidad,
        objetivo=content.objetivo,
        pasos=content.pasos,
        verificacion=content.verificacion,
        dependencias=content.dependencias,
        generado_por=content.generado_por,
    )


def generate_plans(
    methodology: Methodology, results: list[CriterionResult], client: AIClient | None = None
) -> list[Plan]:
    """Un plan por hallazgo (docs/05 §4: un plan por criterio en este corte, sin incidentes)."""

    active_client = client or NullAIClient()
    findings = derive_findings(methodology, results)
    return [_build_plan(methodology, active_client, finding) for finding in findings]
