# Plataforma de Evaluación de Madurez de Ciberseguridad

> Proyecto final académico. Prototipo de una plataforma que analiza evidencia técnica y documental,
> estima la madurez de una organización frente a NIST CSF 2.0, y genera una hoja de ruta priorizada
> con asistencia de IA.

## Qué es

- Un sistema que **recolecta evidencia** de Terraform, Ansible, documentos de políticas y eventos operativos.
- Un **motor determinístico** que evalúa esa evidencia contra criterios propios mapeados a NIST CSF 2.0.
- Un **índice de madurez propio**: puntaje por función, cobertura de evidencia y Tier estimado.
- Un **motor operativo** que convierte eventos en incidentes y planes de respuesta/recovery en vivo.
- Un **asesor**: explica hallazgos y genera planes de mejora y de recuperación. Nunca ejecuta acciones.

## Qué no es

- No es un certificador de cumplimiento. Las prácticas documentadas se asumen como ciertas dentro del modelo.
- No evalúa todo NIST: el prototipo cubre un subconjunto declarado de criterios.
- No mide privacidad integral: la privacidad es una dimensión secundaria ligada a incidentes de ciberseguridad.
- No inspecciona la infraestructura real: analiza configuración declarada (Terraform, Ansible) y documentos.

## Documentación

| Documento | Contenido |
|---|---|
| [docs/00-vision-y-contexto.md](docs/00-vision-y-contexto.md) | Problema, propuesta, alcance, decisiones de diseño y glosario. |
| [docs/01-modelo-de-evaluacion.md](docs/01-modelo-de-evaluacion.md) | Evidencias, criterios, puntajes, agregación, cobertura y Tier estimado. |
| [docs/02-catalogo-de-evidencias.md](docs/02-catalogo-de-evidencias.md) | Tipos de evidencia, contratos, adaptadores y precedencia de fuentes. |
| [docs/03-matriz-de-criterios.md](docs/03-matriz-de-criterios.md) | Catálogo inicial de criterios por función/categoría/subcategoría NIST. |
| [docs/04-arquitectura-backend.md](docs/04-arquitectura-backend.md) | Módulos, modelo de datos, API, trabajos y estructura de carpetas. |
| [docs/05-integracion-ia.md](docs/05-integracion-ia.md) | Extracción documental, ajuste contextual acotado, planes y DeepSeek. |
| [docs/06-vigilancia-y-eventos.md](docs/06-vigilancia-y-eventos.md) | Pipeline de eventos, escenarios y su conversión en evidencia evaluable. |
| [docs/07-plan-de-desarrollo.md](docs/07-plan-de-desarrollo.md) | Plan de 5 semanas, validación, riesgos y guion de demo. |
| [docs/08-motor-operativo.md](docs/08-motor-operativo.md) | Incidentes en vivo, disparadores determinísticos y planes de respuesta/recovery. |
| [docs/09-registro-de-implementacion.md](docs/09-registro-de-implementacion.md) | Qué existe en `backend/` hoy, en qué orden se construyó y qué se simplificó respecto a los docs 00–08. |
| [docs/10-multitenancy-y-autenticacion.md](docs/10-multitenancy-y-autenticacion.md) | Multitenancy, login con token y aislamiento de datos por organización. |
| [docs/11-backlog-y-pulido.md](docs/11-backlog-y-pulido.md) | Lista de trabajo viva: pulido de UI, funciones pendientes y gaps vs. el diseño. |
| [docs/12-alcance-y-trabajo-futuro.md](docs/12-alcance-y-trabajo-futuro.md) | Registro de lo descartado para el prototipo (válido a mayor escala) y trabajo futuro. |

## Stack

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy + PostgreSQL.
- **Mensajería / caché:** Redis (colas de trabajos reales vía `worker-core`/`worker-logs`; caché de extracción IA aparte, en disco).
- **Análisis:** parsers HCL (`python-hcl2`), parsing YAML de Ansible (`PyYAML`), validación con Pydantic.
- **IA:** API de DeepSeek (compatible con SDK de OpenAI), salida JSON validada.
- **Informes:** PDF con `reportlab`.
- **Despliegue:** Docker + docker-compose (ver [docs/04 §11](docs/04-arquitectura-backend.md)).
- **Frontend:** React + Vite + TypeScript + Tailwind, consumiendo la API REST directamente.

## Estado

Prototipo completo para su alcance declarado:

- **Evaluación:** núcleo determinista con los 23 criterios del catálogo (`criteria.yml` v12, doc 03),
  adaptadores de Terraform, Ansible y documentos, agregación por función, cobertura de evidencia y Tier
  estimado (doc 01).
- **IA (opcional):** extracción documental con cita (U1), ajuste contextual acotado (U2) y redacción de
  planes (U3), con un golden set que mide la extracción contra el modelo real (doc 05, docs/09 §43).
- **Motor operativo:** eventos, patrones, disparadores D1–D5, incidentes con transiciones validadas y planes
  de respuesta (docs 06/08).
- **Plataforma:** API REST con login y aislamiento por organización (doc 10), workers sobre Redis con
  historial y reintento de trabajos, informes en PDF, y despliegue completo con Docker Compose.
- **Frontend:** los paneles de Resumen de Madurez, Recomendaciones, Eventos e Incidentes y Comparar, más la
  vista de Actividad, todos sobre la API real.

Lo que queda pendiente está en [docs/11 §I](docs/11-backlog-y-pulido.md); lo descartado a propósito está en
[docs/12](docs/12-alcance-y-trabajo-futuro.md). El detalle de cómo se construyó cada parte está en
[docs/09](docs/09-registro-de-implementacion.md).

## Cómo probarlo

- **Todo el stack:** `docker compose -f deploy/docker-compose.yml up` (API, workers, Postgres, Redis y
  frontend).
- **Solo el backend, sin Docker:** `cd backend && uv run python -m app.main run --terraform
  tests/fixtures/terraform/gaps --org "Empresa Demo"` para la CLI, o `uv run uvicorn app.api.app:app --reload`
  para la API.
- **Solo el frontend:** `cd frontend && cp .env.example .env && npm install && npm run dev`, con la API
  corriendo aparte.
- **Datos de ejemplo:** el diálogo "Nueva Evaluación" trae tres paquetes (entorno con brechas, en mejora y
  conforme). Sus documentos solo se leen con la opción de IA activada (requiere `DEEPSEEK_API_KEY`); sin
  ella, Gobernar e Identificar quedan sin evidencia. Los logs de ejemplo de Eventos e Incidentes empiezan de
  cero cada vez.

## Desarrollo

Antes de confirmar cambios en el backend: `uv run pytest`, `ruff check app tests` y
`ruff format --check app tests` (en NixOS, `ruff` lo provee `nix develop`). En el frontend:
`npm run typecheck`, `npm run lint` y `npm run build`. Si cambia una regla de criterio, se actualiza
doc 03 en el mismo commit.

## Referencias externas

- NIST CSF 2.0 — https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf
- NIST CSF 2.0 Quick-Start Guide for Using the CSF Tiers (SP 1302) — https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1302.pdf
- NIST Privacy Framework 1.0 — https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.01162020.pdf
- Referencia navegable de CSF 2.0 — https://csf.tools/reference/nist-cybersecurity-framework/v2-0/
- Terraform Language: Expressions — https://developer.hashicorp.com/terraform/language/expressions
- Amazon S3 default encryption — https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html
- DeepSeek API: JSON Output — https://api-docs.deepseek.com/guides/json_mode
