# 04 — Arquitectura del Backend

## 1. Vista General

Monolito modular en Python, desplegable en contenedores. Los análisis largos y el pipeline de eventos
corren como trabajos en segundo plano; la cola/stream y la caché usan Redis, y el estado persistente
vive en PostgreSQL.

```text
                    ┌──────────────────────────────────────────────────┐
 Fuentes            │                    BACKEND                       │
 ┌───────────┐      │  ┌────────────┐   ┌───────────────────────────┐  │
 │ Terraform │──────┼─►│ Ingesta    │──►│ Adaptadores               │  │
 ├───────────┤      │  └────────────┘   │  tf / ansible / docs / logs│  │
 │ Ansible   │──────┼──────────────────►└─────────────┬─────────────┘  │
 ├───────────┤      │                                │                │
 │ Documentos│──────┼──► Extracción IA ──────────────┤                │
 ├───────────┤      │                                ▼                │
 │ Logs      │──────┼──► Vigilancia ──────────► Evidencias            │
 └───────────┘      │                            normalizadas         │
                    │                                │                │
                    │                                ▼                │
                    │                   ┌────────────────────────┐    │
                    │                   │ Motor de evaluación    │    │
                    │                   │ (criterios + rúbrica)  │    │
                    │                   └───────────┬────────────┘    │
                    │                               │                 │
                    │                   ┌───────────▼────────────┐    │
                    │                   │ Ajuste contextual IA   │    │
                    │                   │ (acotado y auditado)   │    │
                    │                   └───────────┬────────────┘    │
                    │                               │                 │
                    │        ┌──────────────────────┼──────────────┐  │
                    │        ▼                      ▼              ▼  │
                    │  Agregados/cobertura    Tier estimado   Planes  │
                    │        └──────────────────────┴──────────────┘  │
                    │                       API REST                  │
                    └──────────────────────────────────────────────────┘
```

La ingesta de logs corre por su propio pipeline con colas dedicadas (`log_ingest`, `log_aggregate`) y
una frontera extraíble a contenedor independiente — ver [§3.1](#31-frontera-del-pipeline-de-logs-extraíble).
De ese mismo stream cuelgan dos consumidores: **madurez** (evidencia por ventana) y **operativo**
(incidentes y planes en vivo, módulo `ops`); ver `08-motor-operativo.md`.

## 2. Stack

| Componente | Elección | Nota |
|---|---|---|
| Lenguaje | Python 3.12 | Equipo con experiencia. |
| API | FastAPI + Pydantic v2 | Validación de entrada/salida y OpenAPI gratis. |
| ORM | SQLAlchemy 2.x | Con migraciones Alembic. |
| Migraciones | Alembic | Job `migrate` en docker-compose antes de API/workers (§11). |
| BD | PostgreSQL | JSONB para `value`, `locator`, metadatos. |
| Cola | Redis (listas `RPUSH`/`BLPOP`) | Dos colas: trabajos del core (`assessment_run`) y del pipeline de logs (`event_ingest`). Streams con consumer groups es el diseño objetivo a mayor escala (docs/12 §1). |
| Trabajos | Workers propios leyendo de Redis | Sin Celery; un worker por tipo de trabajo. |
| Caché | Disco | Caché de extracción IA por hash de prompt (`app/ai/cache.py`); no usa Redis. |
| Contenedores | Docker + docker-compose | API, workers, Postgres y Redis; ver §11. |
| Parsing TF | `python-hcl2` | Solo bloques y valores; expresiones → unknown. |
| Parsing Ansible | `PyYAML` + inspección de estructura | Sin ejecutar nada. |
| PDF/texto | `pypdf` + `markdown` | Solo documentos con capa de texto. |
| Informes PDF | `reportlab` | Informe ejecutivo y comparación (`app/reports/pdf.py`, docs/09 §44); fuentes estándar, sin dependencias del sistema. |
| IA | SDK `openai` apuntando a DeepSeek | Ver doc 05. |
| Tests | pytest + fixtures/golden | Ver doc 07. |

## 3. Módulos

| Módulo | Responsabilidad | Depende de |
|---|---|---|
| `methodology` | Cargar y versionar criterios, evidencias, pesos, umbrales, prompts. Inmutable por versión. | — |
| `ingestion` | Recibir y registrar fuentes (archivos/eventos), checksum, deduplicación. | BD |
| `adapters.terraform` | HCL → evidencias `tf.*`. | methodology, ingestion |
| `adapters.ansible` | YAML → evidencias `an.*`. | methodology, ingestion |
| `adapters.documents` | Chunks de documentos → IA → evidencias `doc.*` validadas. | ai.extraction |
| `adapters.logs` | Eventos → patrones → evidencias `log.*`. Consume mensajes del pipeline. | surveillance |
| `evaluation` | Evaluar criterios, aplicar rúbricas, agregar, calcular cobertura y Tier. | methodology, evidencias |
| `ai` | Cliente, extracción, ajuste contextual, generación de planes, prompts. | methodology |
| `recommendations` | Hallazgos → planes priorizados con plantillas + IA. | evaluation, ai |
| `surveillance` | Pipeline de logs **extraíble**: filtro/dedup, ventanas, patrones operativos. Stateless e idempotente. | ingestion (colas) |
| `ops` | Motor operativo: disparadores determinísticos, incidentes y planes en vivo (consumidor B). | surveillance, ai, recommendations |
| `api` | Endpoints REST, validación, serialización. | todos |
| `workers` | Ejecutar pipelines por trabajo. | todos |

Regla de dependencias: `adapters` **no** conocen criterios; producen solo evidencias.
`evaluation` **no** conoce fuentes; consume solo evidencias.

### 3.1 Frontera del Pipeline de Logs (extraíble)

El pipeline de logs se diseña como una **frontera explícita** dentro del monolito, de modo que
extraerlo a un contenedor independiente sea un cambio de despliegue y no una reescritura.

```text
logs crudos ──► ingesta ──► normalización ──► filtro/dedup
   (stateless)                                    │
                    ┌──────────────────────────────┴───────────────────────────┐
                    ▼ [A] madurez                                              ▼ [B] operativo
        agregación a patrones (ventanas)                     disparadores determinísticos
                    │                                                  │
                    ▼                                                  ▼
        log.pattern / log.window                              incidents + planes
                    │                                                  │
                    ▼                                                  ▼
        core: persiste evidencia                      hechos operativos → stream
        y re-evalúa criterios                         (vuelven a [A] como evidencia)
        (la IA nunca recibe logs crudos, solo patrones)
```

Reglas de diseño:

| # | Regla |
|---|---|
| P1 | El pipeline es **stateless e idempotente**: se puede reiniciar sin perder evidencia. |
| P2 | Tiene **cola propia** (`event_ingest`); hoy sobre una lista de Redis (`RPUSH`/`BLPOP`), sin consumer groups. Streams es el diseño objetivo a mayor escala. |
| P3 | La comunicación con el core usa un **contrato de mensaje versionado** (`log.pattern@1`, `log.window@1`) con `desde`, `hasta`, `conteo`, `scope` y `schema_version`. |
| P4 | El **core es el único escritor de `evidence`**; el pipeline publica, el core persiste y evalúa. |
| P5 | Solo patrones y anomalías llegan a la IA; el volumen crudo se filtra con reglas determinísticas. |
| P6 | Un fallo del pipeline no bloquea la evaluación: se registra y las ventanas incompletas producen `evidencia_insuficiente`, nunca `no_implementado`. |
| P7 | En producción, el mismo contrato puede moverse a un stream mayor (Kafka) y a un contenedor independiente con autoscaling por profundidad de cola. |
| P8 | El flujo operativo (B) es un consumidor separado (`ops`): disparadores determinísticos → incidentes → planes. Detalle en `08-motor-operativo.md`. |

Candidatos a seguir por la misma frontera si el volumen crece: ingesta de logs por lotes y
preclasificación determinística. La lógica de criterios y agregación **permanece en el core**,
porque toca el modelo de evidencias.

## 4. Modelo de Datos (tablas principales)

| Tabla | Campos clave |
|---|---|
| `organizations` | `id`, `nombre`, `contexto jsonb` |
| `users` | `id`, `org_id`, `username`, `password_salt`, `password_hash`, `role`, `creado_en` (doc 10) |
| `assessments` | `id`, `org_id`, `estado`, `methodology_version`, `scope`, `previous_assessment_id?` (auto-referencia a la evaluación anterior del mismo org+scope, para heredar seguimiento — docs/05 §4.4), `error?`, `creado_en` |
| `sources` | `id`, `assessment_id`, `tipo` (`terraform`\|`ansible`\|`documents`), `ruta`, `sha256` (un `Source` por adaptador, no por archivo — docs/09 §11) |
| `evidence_definitions` | `id`, `version`, `descripcion`, `schema jsonb`, `estado`, `publicado_en` (catálogo, no por evaluación) |
| `evidence` | `id`, `assessment_id`, `type_id`, `type_version`, `subject_type`, `subject_ref`, `scope`, `value jsonb`, `source_id`, `locator jsonb`, `observed_at`, `modality`, `limitations`, `created_by` |
| `criteria_catalog` | `id`, `version`, `titulo`, `tipo`, `funcion`, `categorias[]`, `subcategorias[]`, `peso`, `ai_adjustable`, `regla jsonb`, `recomendacion`, `estado` |
| `criterion_results` | `id`, `assessment_id`, `criterion_id`, `criterion_version`, `estado`, `base_score`, `final_score`, `explanation`, `evidence_ids[]`, `computed_en` |
| `ai_adjustments` | `id`, `assessment_id`, `criterion_id`, `modelo`, `prompt_version`, `propuesta`, `justificacion`, `evidence_refs[]`, `clamped`, `aplicado bool`, `degradado bool`, `creado_en` |
| `score_aggregates` | `id`, `assessment_id`, `nivel` (`subcategoria`\|`categoria`\|`funcion`\|`global`), `ref`, `score`, `base_score`, `cobertura`, `conteo_estados jsonb` |
| `tier_estimates` | `id`, `assessment_id`, `tier`, `provisional bool`, `justificacion`, `faltantes jsonb` |
| `findings` | `id`, `assessment_id`, `criterion_id`, `tipo` (`brecha`\|`contradiccion`\|`limitacion`), `titulo`, `detalle`, `severidad`, `evidence_ids[]` |
| `plans` | `id`, `incident_id?`, `assessment_id?`, `criterion_id`, `origen` (`criterio`\|`evento`), `titulo`, `prioridad`, `pasos jsonb`, `verificacion`, `estado` (`pendiente`\|`en_progreso`\|`hecho`, **seguimiento, no puntaje** — docs/05 §4.4), `generado_por` |
| `events` | `id`, `org_id`, `scope`, `event_id`, `event_time`, `tipo`, `recurso`, `actor`, `detalle jsonb`, `source_id` |
| `log_patterns` | `id`, `org_id`, `scope`, `patron`, `resultado`, `desde`, `hasta`, `conteo`, `evidence_id` |
| `incidents` | `id`, `org_id`, `scope`, `correlation_key`, `titulo`, `estado`, `severidad`, `first_event_time`, `last_event_time`, `event_ids[]`, `pattern_ids[]`, `criterios[]`, `timeline jsonb`, `creado_en`, `actualizado_en`. Único por (`org_id`, `correlation_key`): la clave sale de los eventos y dos organizaciones pueden compartirla (docs/09 §62) |
| `jobs` | `id`, `assessment_id?`, `org_id?`, `tipo`, `estado`, `progreso`, `error`, `payload?` (entradas para reintentar, docs/09 §46), `creado_en`, `tomado_en`, `actualizado_en` |

### Reglas de integridad

- `evidence` es **append-only** (sin UPDATE/DELETE salvo borrado en cascada de la evaluación).
- `criterion_results` referencia la versión exacta del criterio usada.
- Los catálogos (`evidence_definitions`, `criteria_catalog`) se cargan desde YAML versionado.
- `events`, `log_patterns` e `incidents` tienen alcance **organización/entorno** (`org_id` + `scope`), no evaluación; una evaluación consume ventanas de ellos.

## 5. Ciclo de Vida de una Evaluación

```text
creada ──► ingestando ──► analizando ──► evaluando ──► ajustando_ia ──► completada
                                              │
                                              └──► fallida (parcial o total, con detalle)
```

- Cada transición corresponde a un `job`.
- Una evaluación completada es **inmutable**; “reevaluar” crea una evaluación nueva que hereda fuentes.
- Si el ajuste de IA falla, la evaluación igual completa con `base_score = final_score` y marca `degradado`.

Estados de `job`: `pendiente`, `en_progreso`, `completado`, `fallido`, con `progreso` (0–100) y `error`.

Tipos de `job`:

| Tipo | Pertenece a | Descripción |
|---|---|---|
| `assessment_run` | core | Pipeline de evaluación completo (crear/reevaluar). |
| `event_ingest` | pipeline de logs + motor operativo | Normalizar eventos, agregar patrones y disparar incidentes. |

El diseño contemplaba una granularidad mayor (`assess`/`reevaluate`/`compare`/`log_ingest`/
`log_aggregate`/`ops_evaluate`/`plan_generate`); el prototipo la resolvió con dos jobs porque el
pipeline completo ya corre de una vez (docs/09 §11, docs/12 §1).

Las colas y el stream se implementan sobre Redis; el core consume sus mensajes para persistir
evidencia y recalcular solo los criterios afectados.

## 6. API REST (borrador)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/auth/login` | Login (usuario/contraseña) → token + usuario. Público. |
| `GET` | `/auth/me` | Usuario de la sesión actual. |
| `POST` | `/assessments` | Crea evaluación (contexto de la organización del usuario), sube archivos y encola el pipeline. Devuelve `job_id` (202). Un `context` que no sea un objeto JSON da 422 antes de crear nada. |
| `GET` | `/assessments` | Lista de evaluaciones de la organización (cada una con su resumen/Tier). |
| `GET` | `/assessments/{id}` | Resumen: estado, puntaje global, cobertura, Tier. |
| `GET` | `/jobs` | Historial de jobs de la organización, del más reciente al más antiguo. Filtros `estado`, `tipo` y `limit` (1–200, por defecto 50). Marca `fallido` los jobs activos que se quedaron colgados antes de listar (docs/09 §45). |
| `POST` | `/jobs/{job_id}/retry` | Reencola un job `fallido` con las mismas entradas (202, devuelve el job nuevo). 409 si no está fallido, no tiene entradas guardadas, faltan los archivos o la evaluación ya se reintentó; si usaba IA real, exige `confirm_live_ai` otra vez (docs/09 §46). |
| `GET` | `/jobs/{job_id}` | Estado y progreso de cualquier trabajo (`assessment_run`/`event_ingest`). |
| `GET` | `/assessments/{id}/criteria` | Resultados por criterio con explicación y evidencias. |
| `GET` | `/assessments/{id}/evidence` | Evidencias con procedencia y limitaciones (filtrable). |
| `GET` | `/assessments/{id}/findings` | Hallazgos. Tipos `brecha`, `contradiccion` (docs/09 §38) y `limitacion` (docs/09 §56). Los hallazgos no se persisten: se derivan al consultar, con la evidencia. |
| `GET` | `/assessments/{id}/report.pdf` | Informe ejecutivo en PDF (AMP-02): resumen, madurez por función, hallazgos, plan y criterios. 409 si la evaluación no está `completada`. |
| `GET` | `/assessments/{id}/compare/{other_id}/report.pdf` | Comparación de dos evaluaciones en PDF. |
| `GET` | `/assessments/{id}/plans` | Planes con pasos, prioridad, verificación y estado de seguimiento. |
| `POST` | `/assessments/{id}/plans` | Genera/recalcula los planes (`?use_ai=true` para U3, sujeto al guard de costo). |
| `PATCH` | `/assessments/{id}/plans/{plan_id}` | Cambia el estado de seguimiento del plan (`pendiente`\|`en_progreso`\|`hecho`). No afecta el puntaje (docs/05 §4.4). |
| `GET` | `/orgs` | Organización de la sesión (solo la propia). |
| `POST` | `/orgs/{org_id}/events` | Carga eventos al stream de la organización (JSONL); encola `event_ingest`. |
| `DELETE` | `/orgs/{id}/events` | Borra eventos, patrones e incidentes (con sus planes) de la organización. Lo usan los logs de ejemplo de la UI para empezar de cero; las evaluaciones ya hechas no cambian. 409 si hay una ingesta en curso (docs/09 §59). |
| `GET` | `/orgs/{org_id}/incidents` | Lista incidentes operativos (filtrable por estado/severidad). |
| `GET` | `/incidents/{id}` | Detalle, timeline y hechos del incidente. |
| `GET` | `/incidents/{id}/plans` | Planes asociados al incidente. |
| `PATCH` | `/incidents/{id}` | Cambia el estado del incidente (`open`…`closed`). Un paso por vez, sin retroceder; `closed` (terminal, desde cualquier estado abierto) exige `motivo` y lo mueve al historial. Transición inválida o sin motivo → 409 (docs/08 §4, docs/09 §52). |
| `POST` | `/assessments/{id}/reevaluate` | Crea nueva evaluación heredando fuentes. |
| `GET` | `/assessments/{id}/compare/{other_id}` | Por criterio: estado, puntaje, `direccion` del cambio y la explicación de antes y de después. Además el puntaje global, si ambas usan la misma metodología y alcance, y los hallazgos que ya no aparecen o son nuevos (docs/09 §67). |
| `GET` | `/methodology` | Catálogo de criterios y tipos de evidencia vigentes. |
| `GET` | `/health` | Liveness/readiness. |

> Descartados para el prototipo (docs/12 §1): API-01 (`POST /sources` + `/run` separados) y API-02
> (`GET /assessments/{id}/scores`, hoy plegado en `GET /assessments/{id}`).

Convenciones:

- Autenticación por token (doc 10): todas las rutas de datos exigen
  `Authorization: Bearer <token>`; un recurso de otra organización responde **404**, no 403.
- Respuestas siempre incluyen `puntaje` **y** `cobertura` juntos.
- Paginación por cursor en listados grandes: fuera del prototipo (docs/12 §1); `GET /jobs` usa `limit`.
- Toda respuesta lleva la cabecera `X-Methodology-Version` (la `methodology_version` con la que se calcula) para trazabilidad; las evaluaciones además la traen en el cuerpo. Las respuestas 500 que genera el servidor antes del middleware no la llevan.
- Todo error es `application/problem+json` (`type`, `title`, `status`, `detail`, `instance`); `detail` es siempre un texto y la validación (422) agrega `errors` por campo (docs/09 §55).

## 7. Estructura de Carpetas

Estructura real del código (revisada el 2026-10-02):

```text
backend/
├── app/
│   ├── main.py              # CLI (el entrypoint HTTP es app/api/app.py)
│   ├── api/                 # FastAPI: app, dependencias, errores problem+json, esquemas y rutas
│   │   ├── app.py
│   │   ├── deps.py
│   │   ├── errors.py
│   │   ├── schemas.py
│   │   └── routes_{assessments,auth,incidents,jobs,methodology,orgs}.py
│   ├── core/                # orquestación y servicios (sin HTTP)
│   │   ├── assessment_service.py  # crear/correr/reevaluar evaluaciones, planes, consultas
│   │   ├── operations.py          # flujo B: ingesta de eventos e incidentes
│   │   ├── refresh.py             # refresco de madurez tras una ingesta (selectivo)
│   │   ├── comparison.py          # comparación entre dos evaluaciones
│   │   ├── jobs.py · dispatch.py · queue.py   # jobs en BD, encolado y Redis
│   │   ├── db.py · repository.py · reproducibility.py
│   │   └── auth.py · seed.py · uploads.py
│   ├── models/              # SQLAlchemy (tables.py)
│   ├── schemas/             # Pydantic compartido: evidencia y vistas de evaluación/comparación
│   ├── methodology/         # loader + validación de los YAML
│   ├── adapters/            # terraform/, ansible/, documents/
│   ├── evaluation/          # engine, aggregation, tier, contradictions, rules/
│   ├── ai/                  # client, cache, extraction, adjustment, plan_generation, golden_eval, prompts/
│   ├── recommendations/     # findings (brecha/contradicción/limitación), plans
│   ├── surveillance/        # eventos y patrones (pipeline de logs, ver §3.1)
│   ├── ops/                 # motor operativo: disparadores, incidentes, planes de incidente (doc 08)
│   ├── reports/             # informes PDF
│   └── workers/             # consumidores de Redis: core.py (evaluaciones) y logs.py (eventos)
├── methodology/             # criteria.yml, evidence_types.yml, settings.yml
├── tests/
│   ├── fixtures/            # Terraform, Ansible, documentos y escenarios de eventos
│   ├── golden/              # salida esperada de adaptadores y pipeline (TS-01)
│   └── golden_ai/           # golden set de la extracción con IA (TS-02)
├── alembic/
├── pyproject.toml
└── docker/                  # Dockerfile.api, Dockerfile.worker

frontend/                    # React + Vite (Dockerfile propio; datos de ejemplo en public/demo)
```

En la raíz del proyecto: `deploy/docker-compose.yml` y `deploy/.env.example` (ver §11).

## 8. Metodología Versionada en YAML

`methodology/criteria.yml` (extracto):

```yaml
version: 1
criterios:
  - id: CRI-PR-01
    version: 1
    titulo: "Cifrado de datos en reposo"
    tipo: tecnico
    funcion: PR
    categorias: [PR.DS]
    subcategorias: [PR.DS-01]
    peso: 5
    ai_adjustable: true
    evidencias: [tf.encryption.config@1, doc.claim@1]
    recomendacion: "Habilitar cifrado gestionado por KMS en RDS y S3."
    regla:
      tipo: umbral_por_recurso
      estados: { all_enabled: 100, any_disabled: 25, any_unknown: insuficiente }
```

`methodology/settings.yml` — **fuente canónica** de los umbrales de Tier (α, D y umbrales de confianza
incluidos). Las tablas de `01-modelo-de-evaluacion.md §8.2` y `03-matriz-de-criterios.md §9` son copias
ilustrativas de este archivo para lectura humana; en caso de discrepancia, manda el YAML:

```yaml
version: 1
ia:
  alpha: 0.25
  divergencia_maxima: 20
  umbral_confianza_documental: 0.6
tier:
  t2: { CRI-GV-01: 50, CRI-GV-02: 50, CRI-ID-03: 50 }
  t3: { CRI-GV-01: 75, CRI-GV-03: 75, CRI-GV-04: 75, CRI-DE-01: 75,
        CRI-RS-01: 75, CRI-RC-01: 75, CRI-RC-02: 75 }
  t4: { CRI-GV-04: 100, CRI-RS-02: 75, CRI-RC-03: 75, CRI-ID-04: 75 }
funciones: { GV: 1, ID: 1, PR: 1, DE: 1, RS: 1, RC: 1 }
```

Reglas:

- El cargador valida el YAML contra esquema Pydantic al arrancar; un error impide iniciar (fallo rápido).
- Cambiar cualquier valor en `methodology/` genera `methodology_version` nueva.
- Las evaluaciones guardan la versión; nunca se recalculan con la versión actual.

## 9. Manejo de Archivos y Datos No Confiables

| Riesgo | Medida |
|---|---|
| Playbooks maliciosos | **Nunca** se ejecutan; solo se parsean como datos. |
| HCL/YAML con payloads | Parsers en modo datos; sin eval, sin templates, sin include remoto. |
| PDFs con macros/contenido activo | Solo extracción de texto; sin renderizado. |
| Prompt injection en documentos | El contenido va delimitado y etiquetado como datos; ver doc 05 §7. |
| Secretos en archivos | Detección básica de patrones (claves, tokens) y redacción antes de enviar a IA. |
| Tamaño de archivos | Límites por fuente y por evaluación; rechazo explícito con error. |
| Traversal / archivos comprimidos | Lista blanca de extensiones; sin descompresión recursiva. |

## 10. Decisiones Diferidas

| Tema | Decisión para el prototipo |
|---|---|
| Cola dedicada | Sí, Redis para la cola de trabajos (la caché de extracción IA es en disco); sin Celery (workers propios). |
| Orquestación | Docker + docker-compose; sin Kubernetes en el prototipo. |
| Motor operativo (incidentes/planes) | Sí, mínimo: consumidor `ops` con disparadores determinísticos (doc 08). |
| Base vectorial | No; recuperación por IDs y búsqueda textual sobre el catálogo NIST. |
| Microservicios | No; monolito modular. |
| Pipeline de logs como servicio independiente | No en el prototipo: módulo extraíble con cola propia (§3.1). Evolución: stream + contenedor con autoscaling por profundidad de cola. |
| AI gateway centralizado | No; el módulo `ai` aplica límites y caché. Se evalúa extraerlo si el costo/volumen lo justifica. |
| Autenticación | Login usuario/contraseña con token firmado (doc 10); OAuth/SSO fuera de alcance. |
| Multi-tenant | Sí: varias organizaciones por despliegue, aisladas por usuario (doc 10); el registro lo hace el proveedor por seed/CLI. |
| Frontend | React implementado (`frontend/`, 7º servicio del compose); la API expone todo lo necesario. |

## 11. Despliegue en Docker

Todo el prototipo debe ser desplegable con `docker compose up`. Redis entra como dependencia del
prototipo (cola de trabajos) sin añadir complejidad de orquestación.

### 11.1 Servicios

| Servicio | Imagen / build | Rol | Depende de |
|---|---|---|---|
| `db` | `postgres:16` | Estado persistente. | — |
| `redis` | `redis:7` | Cola de trabajos (listas). | — |
| `api` | `docker/Dockerfile.api` | FastAPI; encola trabajos y sirve lecturas. | db, redis |
| `worker-core` | `docker/Dockerfile.worker` | Evaluación, adaptadores, IA. | db, redis |
| `worker-logs` | `docker/Dockerfile.worker` | Pipeline de logs (`log_ingest`, `log_aggregate`) y `ops`. | db, redis |
| `migrate` | `docker/Dockerfile.api` | Job de una sola ejecución: `alembic upgrade head`. | db |
| `frontend` | `docker/Dockerfile.frontend` | React/Vite servido por Nginx. | api |

Notas:

- `worker-logs` es el contenedor que se extrae/escala primero si el volumen crece (§3.1, P7).
- Sin autoscaling en el prototipo: se puede escalar a mano con `--scale worker-logs=N`.
- Persistencia con volúmenes nombrados para `db` y `redis`; healthchecks y `depends_on` con condición.

### 11.2 `deploy/docker-compose.yml` (referencia)

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-pf}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-pf}
      POSTGRES_DB: ${POSTGRES_DB:-pf}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7
    command: ["redis-server", "--appendonly", "yes"]
    volumes: ["redisdata:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10

  migrate:
    build: { context: .., dockerfile: backend/docker/Dockerfile.api }
    command: ["alembic", "upgrade", "head"]
    environment: { DATABASE_URL: "postgresql+psycopg://pf:pf@db:5432/pf" }
    depends_on:
      db: { condition: service_healthy }

  api:
    build: { context: .., dockerfile: backend/docker/Dockerfile.api }
    environment:
      DATABASE_URL: "postgresql+psycopg://pf:pf@db:5432/pf"
      REDIS_URL: "redis://redis:6379/0"
      DEEPSEEK_API_KEY: "${DEEPSEEK_API_KEY}"
    ports: ["8000:8000"]
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }

  worker-core:
    build: { context: .., dockerfile: backend/docker/Dockerfile.worker }
    command: ["python", "-m", "app.workers.core"]
    environment: &worker_env
      DATABASE_URL: "postgresql+psycopg://pf:pf@db:5432/pf"
      REDIS_URL: "redis://redis:6379/0"
      DEEPSEEK_API_KEY: "${DEEPSEEK_API_KEY}"
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }

  worker-logs:
    build: { context: .., dockerfile: backend/docker/Dockerfile.worker }
    command: ["python", "-m", "app.workers.logs"]
    environment: *worker_env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }

  frontend:
    build: { context: .., dockerfile: backend/docker/Dockerfile.frontend }
    ports: ["5173:80"]
    depends_on:
      api: { condition: service_started }

volumes:
  pgdata:
  redisdata:
```

### 11.3 Reglas de despliegue

| # | Regla |
|---|---|
| C1 | Sin secretos en la imagen: todo por variables de entorno (`deploy/.env`, fuera de git). |
| C2 | Migraciones como job separado (`migrate`) antes de arrancar API y workers. En Postgres, Alembic es la **única** fuente de verdad del esquema: `create_all` solo corre en SQLite (dev/CLI/tests) — ver `ensure_schema` en `app/core/db.py` y docs/09 §22. |
| C3 | Workers idempotentes: reiniciar un contenedor no duplica evidencia ni planes. |
| C4 | La API no depende de la IA para responder; si Redis o el proveedor IA caen, degrada sin tumbar lecturas. |
| C5 | Un solo `docker-compose.yml` para demo; la extracción a servicios independientes no cambia el contrato. |
