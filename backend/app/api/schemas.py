"""Esquemas de respuesta propios de la API. Los contratos de dominio ya son Pydantic y se
reusan tal cual como items de lista: `CriterionResult`, `Aggregate`, `TierEstimate`, `Plan`,
`Finding`, `EvidenceInstance` (ver `app/evaluation/schemas.py`, `app/recommendations/*`,
`app/schemas/evidence.py`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.ops.incidents import allowed_transitions
from app.schemas.assessment import (  # noqa: F401  (reexportados para las rutas)
    AssessmentDetail,
    AssessmentSummary,
    ComparisonDiffOut,
    ComparisonOut,
)


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nombre: str


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


class IngestJobResult(BaseModel):
    """Resumen de una ingesta (FN-03). Los campos ausentes quedan en 0, no en `undefined`."""

    eventos_leidos: int = 0
    eventos_nuevos: int = 0
    eventos_existentes: int = 0
    patrones_nuevos: int = 0
    incidentes_nuevos: int = 0
    incidentes_actualizados: int = 0


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
    resultado: IngestJobResult | None = None
    #: Fallido, con entradas guardadas y con la evaluacion aun fallida (`POST /jobs/{id}/retry`).
    reintentable: bool = False
    #: El reintento volveria a llamar a la IA real (cuesta dinero).
    usa_ia: bool = False

    @classmethod
    def from_job(cls, job, assessment_estado: str | None = None) -> JobOut:
        out = cls.model_validate(job)
        out.reintentable = job.estado == "fallido" and job.payload is not None
        if out.reintentable and job.assessment_id is not None:
            # Un reintento exitoso deja la evaluacion completada; el job viejo sigue `fallido`,
            # pero ya no se puede reintentar (dispatch responde 409). El campo debe reflejarlo.
            out.reintentable = assessment_estado == "fallida"
        out.usa_ia = bool((job.payload or {}).get("ai_requested"))
        return out


class AssessmentAccepted(BaseModel):
    """`POST /assessments` y `POST /assessments/{id}/reevaluate` ya no corren el pipeline en el
    request (docs/09 §16): devuelven esto con 202 y el cliente sondea `GET /jobs/{job_id}`."""

    assessment_id: str
    org_id: str
    org_nombre: str
    job_id: str


class EventsCleared(BaseModel):
    """`DELETE /orgs/{org_id}/events`: cuanto se borro."""

    eventos: int
    patrones: int
    incidentes: int
    planes: int


class EventsAccepted(BaseModel):
    """Igual que `AssessmentAccepted`, para `POST /orgs/{org_id}/events`."""

    org_id: str
    job_id: str
