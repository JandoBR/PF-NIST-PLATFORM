"""Vistas de una evaluacion y de una comparacion: lo que devuelve la API y lo que maqueta el informe
PDF. Viven aqui y no en `app/api` para que `app/reports` no dependa de la capa HTTP."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.evaluation.schemas import Aggregate, TierEstimate


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


class ComparisonDiffOut(BaseModel):
    criterion_id: str
    titulo: str
    estado_antes: str | None
    estado_despues: str | None
    score_antes: float | None
    score_despues: float | None
    cambio: bool
    #: mejora | retroceso | ahora_evaluado | dejo_de_evaluarse | cambio_de_estado | igual
    direccion: str = "igual"
    explicacion_antes: str | None = None
    explicacion_despues: str | None = None


class ComparisonOut(BaseModel):
    assessment_id_a: str
    assessment_id_b: str
    diffs: list[ComparisonDiffOut]
    global_antes: float | None
    global_despues: float | None
    #: False si las evaluaciones usaron reglas o alcances distintos: los cambios pueden no venir
    #: del entorno.
    misma_metodologia: bool = True
    mismo_scope: bool = True
    #: Ids de criterio con brecha solo antes (resueltos) o solo despues (nuevos).
    hallazgos_resueltos: list[str] = []
    hallazgos_nuevos: list[str] = []
