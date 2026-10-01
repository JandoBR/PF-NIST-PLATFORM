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
    tipo: Mapped[str] = mapped_column(String)  # 'terraform' | 'documents'
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
    """Un plan por hallazgo (docs/05 §4). `origen` e `incident_id` anticipan el motor
    operativo (docs/08): por ahora todo plan nace de un criterio, nunca de un incidente."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"))
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
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    assessment: Mapped[Assessment] = relationship(back_populates="plans")
