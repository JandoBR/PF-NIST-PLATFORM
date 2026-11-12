"""Modelo de datos persistente (docs/04 §4), subconjunto minimo para este corte.

Deliberadamente NO se persisten `score_aggregates` ni `tier_estimates`: se recalculan en el
momento desde `criterion_results` con `app/evaluation` (deterministico y barato). Si mas adelante
pesa el costo de recalcular en cada lectura, ahi se justifica persistirlos.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
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
    #: Evaluacion anterior de la que se hereda el estado de seguimiento de los planes por criterio
    #: (docs/05 §4.4): la de la reevaluacion, o la ultima completada del mismo org+scope.
    previous_assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessments.id"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Con que se calculo (versiones de adaptadores/parsers y, si participo, modelo y prompts de
    #: IA); ver `app/core/reproducibility.py`. `None` en evaluaciones anteriores a OP-14.
    reproducibility: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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
    #: Estado de *seguimiento* del plan (docs/05 §4.4): pendiente | en_progreso | hecho. NUNCA
    #: afecta el puntaje de un criterio -- eso lo determina la evidencia, no una afirmacion del
    #: usuario (docs/00 §7, principios 1/3/4).
    estado: Mapped[str] = mapped_column(String, default="pendiente")
    diagnostico_observable: Mapped[str | None] = mapped_column(Text, nullable=True)
    hipotesis: Mapped[list[str]] = mapped_column(JSON, default=list)
    comprobaciones_seguras: Mapped[list[str]] = mapped_column(JSON, default=list)
    advertencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    assessment: Mapped[Assessment | None] = relationship(back_populates="plans")
    incident: Mapped[Incident | None] = relationship(back_populates="plans")


class EventIngest(Base):
    """Una ingesta: el archivo que se subio y lo que aporto (docs/09 §102).

    Es la identidad que elige una evaluacion (docs/08 §3): el mismo `fuente` puede venir en varios
    archivos, asi que el origen declarado por los eventos no sirve para separar un escenario de
    otro. Los eventos de un archivo reingerido conservan la ingesta que los guardo primero; esta
    fila queda como registro de la subida, con `eventos = 0` si no aporto ninguno nuevo.
    """

    __tablename__ = "event_ingests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    #: Nombre del archivo subido (solo el basename, `safe_filename`).
    archivo: Mapped[str] = mapped_column(String)
    ruta: Mapped[str] = mapped_column(String)
    ingerido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    #: Eventos que esta ingesta guardo de verdad (los duplicados cuentan en
    #: `eventos_existentes`, no aqui).
    eventos: Mapped[int] = mapped_column(default=0)
    eventos_leidos: Mapped[int] = mapped_column(default=0)
    eventos_existentes: Mapped[int] = mapped_column(default=0)
    desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fuentes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


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
    #: Ingesta que guardo el evento; `None` en los anteriores a la seleccion por ingesta, que se
    #: agrupan como la pseudo-ingesta `legacy` (docs/09 §102).
    ingest_id: Mapped[str | None] = mapped_column(ForeignKey("event_ingests.id"), nullable=True)
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
    #: Origenes (`fuente` del evento, o el archivo si no la declara; docs/06 §2) de los eventos que
    #: forman el patron; `None` en patrones anteriores a FN-07.
    fuentes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Incident(Base):
    """Ciclo de vida: open -> triaged -> contained -> recovering -> closed (docs/08 §4). Se
    crea por un disparador y se actualiza por hechos posteriores; el motor nunca los fabrica."""

    __tablename__ = "incidents"
    #: La clave de correlacion sale de los eventos (recurso + hora), no del entorno: es unica por
    #: organizacion **y scope**. Sin el scope, el mismo host/hora en produccion y staging se
    #: fusionaba en un incidente (docs/04 §4, docs/08 §3).
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "scope",
            "correlation_key",
            name="uq_incidents_org_scope_correlation_key",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    scope: Mapped[str] = mapped_column(String)
    correlation_key: Mapped[str] = mapped_column(String)
    titulo: Mapped[str] = mapped_column(String)
    estado: Mapped[str] = mapped_column(String, default="open")
    severidad: Mapped[str] = mapped_column(String)
    first_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    criterios: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    #: Como se verifico o por que se descarto, registrado al cerrar (docs/11 OP-11).
    motivo_cierre: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    organization: Mapped[Organization] = relationship(back_populates="incidents")
    plans: Mapped[list[PlanRow]] = relationship(back_populates="incident")


class AIResult(Base):
    """Resultado de una llamada de IA, por organizacion y por insumo canonico (docs/05 §7).

    Reemplaza la cache en disco de cada contenedor: el resultado sobrevive a recrear api/workers
    y dos contenedores con la misma BD reutilizan las mismas respuestas. La clave no incluye
    ids/uuids de evidencia: el insumo se canonicaliza en `app/ai/store.py`, y las referencias de
    U2 se remapean a la evaluacion actual al leer. `output` es el JSON crudo que devolvio el
    modelo (para U1, la afirmacion ya votada); `meta` guarda tokens/votos/resumen de corridas.
    """

    __tablename__ = "ai_results"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "kind",
            "model",
            "base_url",
            "params_hash",
            "prompt_version",
            "input_sha256",
            name="uq_ai_results_key",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String)  # 'U1' | 'U2' | 'U3'
    model: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String)
    params_hash: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    input_sha256: Mapped[str] = mapped_column(String)
    output: Mapped[Any] = mapped_column(JSON)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


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
    #: Mensaje de la cola sin `job_id` (rutas de archivos, flags de IA, contexto): lo que hace falta
    #: para reencolar un job fallido (docs/11 FN-09). `None` en jobs anteriores a FN-09.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: Resumen de lo que hizo el job al terminar (FN-03): hoy, la ingesta de eventos (nuevos vs ya
    #: existentes). `None` mientras corre, si falla o si el tipo de job no reporta resultado.
    resultado: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"), nullable=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    tomado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
