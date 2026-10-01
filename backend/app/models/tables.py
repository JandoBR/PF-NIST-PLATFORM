"""Modelo de datos persistente (docs/04 §4), subconjunto minimo para este corte.

Deliberadamente NO se persisten `score_aggregates` ni `tier_estimates`: se recalculan en el
momento desde `criterion_results` con `app/evaluation` (deterministico y barato). Si mas adelante
pesa el costo de recalcular en cada lectura, ahi se justifica persistirlos.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid4())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    nombre: Mapped[str] = mapped_column(String, unique=True)
    contexto: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    assessments: Mapped[list[Assessment]] = relationship(back_populates="organization")
    events: Mapped[list[Event]] = relationship(back_populates="organization")
    incidents: Mapped[list[Incident]] = relationship(back_populates="organization")
    users: Mapped[list[User]] = relationship(back_populates="organization")


class User(Base):
    """Cuenta con login (doc 10). Pertenece a una organizacion; el aislamiento de datos se hace
    por `org_id` en toda la API."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    username: Mapped[str] = mapped_column(String, unique=True)
    password_salt: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="client")
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    organization: Mapped[Organization] = relationship(back_populates="users")


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    estado: Mapped[str] = mapped_column(String, default="creada")
    methodology_version: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    organization: Mapped[Organization] = relationship(back_populates="assessments")
    sources: Mapped[list[Source]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[EvidenceRow]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    criterion_results: Mapped[list[CriterionResultRow]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    plans: Mapped[list[PlanRow]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class Source(Base):
    """Un `ruta` por adaptador invocado (archivo o directorio); doc04 lo modela por archivo,
    aqui se simplifica a uno por adaptador para no reimplementar el listado de archivos."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"))
    tipo: Mapped[str] = mapped_column(String)  # 'terraform' | 'ansible' | 'documents'
    ruta: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)

    assessment: Mapped[Assessment] = relationship(back_populates="sources")


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"))
    type_id: Mapped[str] = mapped_column(String)
    type_version: Mapped[int] = mapped_column()
    subject_type: Mapped[str] = mapped_column(String)
    subject_ref: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    value: Mapped[Any] = mapped_column(JSON)
    source_id: Mapped[str] = mapped_column(String)
    locator: Mapped[dict[str, Any]] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    modality: Mapped[str] = mapped_column(String)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String)

    assessment: Mapped[Assessment] = relationship(back_populates="evidence")


class CriterionResultRow(Base):
    __tablename__ = "criterion_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"))
    criterion_id: Mapped[str] = mapped_column(String)
    criterion_version: Mapped[int] = mapped_column()
    estado: Mapped[str] = mapped_column(String)
    base_score: Mapped[float | None] = mapped_column(nullable=True)
    final_score: Mapped[float | None] = mapped_column(nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    degradado: Mapped[bool] = mapped_column(default=False)

    assessment: Mapped[Assessment] = relationship(back_populates="criterion_results")


class PlanRow(Base):
    """Un plan por hallazgo (origen="criterio", docs/05 §4) o por incidente (origen="evento",
    docs/08 §7) — nunca ambos. `assessment_id`/`incident_id` son mutuamente excluyentes segun
    `origen`; no se impone a nivel de esquema porque SQLite no valida CHECK entre columnas
    nulas de forma portable con el resto del stack, pero `app/core`/`app/ops` nunca llenan los
    dos a la vez."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"), nullable=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    criterion_id: Mapped[str] = mapped_column(String)
    origen: Mapped[str] = mapped_column(String, default="criterio")
    titulo: Mapped[str] = mapped_column(String)
    prioridad: Mapped[str] = mapped_column(String)
    objetivo: Mapped[str] = mapped_column(Text)
    pasos: Mapped[list[str]] = mapped_column(JSON, default=list)
    verificacion: Mapped[str] = mapped_column(Text)
    dependencias: Mapped[list[str]] = mapped_column(JSON, default=list)
    generado_por: Mapped[str] = mapped_column(String)
    estado: Mapped[str] = mapped_column(String, default="abierto")
    diagnostico_observable: Mapped[str | None] = mapped_column(Text, nullable=True)
    hipotesis: Mapped[list[str]] = mapped_column(JSON, default=list)
    comprobaciones_seguras: Mapped[list[str]] = mapped_column(JSON, default=list)
    advertencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    assessment: Mapped[Assessment | None] = relationship(back_populates="plans")
    incident: Mapped[Incident | None] = relationship(back_populates="plans")


class Event(Base):
    """Evento operativo, append-only, a nivel organizacion/entorno (docs/06 §2, docs/08 §3) —
    no pertenece a una evaluacion."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    scope: Mapped[str] = mapped_column(String)
    event_id: Mapped[str] = mapped_column(String)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tipo: Mapped[str] = mapped_column(String)
    recurso: Mapped[str] = mapped_column(String)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    detalle: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_id: Mapped[str] = mapped_column(String)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    organization: Mapped[Organization] = relationship(back_populates="events")


class LogPatternRow(Base):
    """Patron detectado, a nivel organizacion/entorno (docs/06 §3, docs/08 §3). Una evaluacion
    lee estas filas para convertirlas en evidencia `log.pattern` (docs/01 §1)."""

    __tablename__ = "log_patterns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    scope: Mapped[str] = mapped_column(String)
    patron: Mapped[str] = mapped_column(String)
    resultado: Mapped[str] = mapped_column(String)
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    conteo: Mapped[int] = mapped_column()
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Incident(Base):
    """Ciclo de vida: open -> triaged -> contained -> recovering -> closed (docs/08 §4). Se
    crea por un disparador y se actualiza por hechos posteriores; el motor nunca los fabrica."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    scope: Mapped[str] = mapped_column(String)
    correlation_key: Mapped[str] = mapped_column(String, unique=True)
    titulo: Mapped[str] = mapped_column(String)
    estado: Mapped[str] = mapped_column(String, default="open")
    severidad: Mapped[str] = mapped_column(String)
    first_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    criterios: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    organization: Mapped[Organization] = relationship(back_populates="incidents")
    plans: Mapped[list[PlanRow]] = relationship(back_populates="incident")


class Job(Base):
    """Trabajo en cola (docs/04 §4, columnas `id, assessment_id?, org_id?, tipo, estado,
    progreso, error, creado_en, tomado_en`). `tipo` es `assessment_run` (pipeline completo de
    evaluacion, consumido por `app/workers/core.py`) o `event_ingest` (pipeline de eventos,
    consumido por `app/workers/logs.py`). El mensaje en Redis solo lleva el `id`; este registro
    es la fuente de verdad del estado, para que `GET /jobs/{id}` no dependa de que el mensaje
    siga en la cola."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tipo: Mapped[str] = mapped_column(String)
    estado: Mapped[str] = mapped_column(String, default="pendiente")
    progreso: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessments.id"), nullable=True
    )
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    tomado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
