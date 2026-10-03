"""Esquemas de respuesta propios de la API. Los contratos de dominio ya son Pydantic y se
reusan tal cual como items de lista: `CriterionResult`, `Aggregate`, `TierEstimate`, `Plan`,
`Finding`, `EvidenceInstance` (ver `app/evaluation/schemas.py`, `app/recommendations/*`,
`app/schemas/evidence.py`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.evaluation.schemas import Aggregate, TierEstimate
from app.ops.incidents import allowed_transitions


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nombre: str


class AssessmentSummary(BaseModel):
    id: str
    org_id: str
    org_nombre: str
    estado: str
    scope: str
    methodology_version: str
    creado_en: datetime
    error: str | None = None
    score_global: float | None = None
    cobertura_global: float | None = None
    #: Score global con cobertura baja (docs/01 §7, AMP-05).
    provisional_global: bool = False


class AssessmentDetail(AssessmentSummary):
    agregados_categoria: list[Aggregate]
    agregados_funcion: list[Aggregate]
    tier: TierEstimate
    #: Versiones de adaptadores/parsers y, si participo, modelo y prompts de IA (OP-14).
    reproducibility: dict | None = None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    scope: str
    correlation_key: str
    titulo: str
    estado: str
    severidad: str
    first_event_time: datetime
    last_event_time: datetime
    event_ids: list[str]
    criterios: list[str]
    timeline: list[dict]
    motivo_cierre: str | None = None
    creado_en: datetime
    actualizado_en: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def transiciones(self) -> list[str]:
        """Estados a los que puede pasar ahora (docs/11 OP-11); vacio si esta cerrado."""

        return allowed_transitions(self.estado)


class IncidentUpdate(BaseModel):
    """`PATCH /incidents/{id}`: cambiar el estado (docs/11 UI-06/OP-04/OP-11). Solo el estado y, al
    cerrar, el motivo: el resto del incidente es observado, no editable desde la API."""

    estado: str
    #: Obligatorio al cerrar: como se verifico, o por que se descarta (falso positivo).
    motivo: str | None = None


class PlanUpdate(BaseModel):
    """`PATCH /assessments/{id}/plans/{plan_id}`: estado de seguimiento del plan (docs/05 §4.4).
    No afecta el puntaje del criterio (docs/11 UI-08)."""

    estado: str


class ComparisonDiffOut(BaseModel):
    criterion_id: str
    titulo: str
    estado_antes: str | None
    estado_despues: str | None
    score_antes: float | None
    score_despues: float | None
    cambio: bool


class ComparisonOut(BaseModel):
    assessment_id_a: str
    assessment_id_b: str
    diffs: list[ComparisonDiffOut]
    global_antes: float | None
    global_despues: float | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo: str
    estado: str
    progreso: int
    error: str | None
    assessment_id: str | None
    org_id: str | None
    creado_en: datetime
    tomado_en: datetime | None
    actualizado_en: datetime
    #: Que hizo el job al terminar, si lo reporta: la ingesta de eventos da nuevos vs existentes.
    resultado: dict | None = None
    #: Fallido y con las entradas guardadas (`POST /jobs/{id}/retry`, docs/11 FN-09).
    reintentable: bool = False
    #: El reintento volveria a llamar a la IA real (cuesta dinero).
    usa_ia: bool = False

    @classmethod
    def from_job(cls, job) -> JobOut:
        out = cls.model_validate(job)
        out.reintentable = job.estado == "fallido" and job.payload is not None
        out.usa_ia = bool((job.payload or {}).get("ai_requested"))
        return out


class AssessmentAccepted(BaseModel):
    """`POST /assessments` y `POST /assessments/{id}/reevaluate` ya no corren el pipeline en el
    request (docs/09 §16): devuelven esto con 202 y el cliente sondea `GET /jobs/{job_id}`."""

    assessment_id: str
    org_id: str
    org_nombre: str
    job_id: str


class EventsAccepted(BaseModel):
    """Igual que `AssessmentAccepted`, para `POST /orgs/{org_id}/events`."""

    org_id: str
    job_id: str
