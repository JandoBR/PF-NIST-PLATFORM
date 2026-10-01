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

## Stack previsto

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy + PostgreSQL.
- **Mensajería / caché:** Redis (Streams + colas de trabajos).
- **Análisis:** parsers HCL (`python-hcl2`), parsing YAML de Ansible (`PyYAML`), validación con Pydantic.
- **IA:** API de DeepSeek (compatible con SDK de OpenAI), salida JSON validada.
- **Despliegue:** Docker + docker-compose (ver [docs/04 §11](docs/04-arquitectura-backend.md)).
- **Frontend:** React (fuera del foco inicial; la API se diseña para soportarlo después).

## Estado

Especificación completa. Sin código implementado todavía. Los artefactos de despliegue en
`deploy/` y `backend/docker/` son el objetivo a completar cuando exista el código de la aplicación.

## Referencias externas

- NIST CSF 2.0 — https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf
- NIST CSF 2.0 Quick-Start Guide for Using the CSF Tiers (SP 1302) — https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1302.pdf
- NIST Privacy Framework 1.0 — https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.01162020.pdf
- Referencia navegable de CSF 2.0 — https://csf.tools/reference/nist-cybersecurity-framework/v2-0/
- Terraform Language: Expressions — https://developer.hashicorp.com/terraform/language/expressions
- Amazon S3 default encryption — https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html
- DeepSeek API: JSON Output — https://api-docs.deepseek.com/guides/json_mode
