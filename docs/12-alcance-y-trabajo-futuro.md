# 12 — Alcance, limitaciones y trabajo futuro

Registro de lo que el diseño describe pero el **prototipo descarta deliberadamente**, y que sí
tendría sentido a mayor escala. No es un backlog: `docs/11` lista lo pendiente del prototipo; este
documento es el **índice de decisiones de alcance**, con el motivo en una línea y el detalle en el
documento donde vive la explicación. La idea es no re-razonar cada vez que alguien se pregunte "¿por
qué no está esto?" ni mantener estos ítems como si fueran deuda del prototipo.

- Detalle de arquitectura: `docs/04 §1/§3`, `docs/09 §11`.
- Trabajo futuro de producto: `docs/07 §7`.
- Precedencia y contradicciones: `docs/02 §5`.

> **Criterio de promoción:** un ítem de esta lista vuelve al backlog (`docs/11`) cuando exista un
> escenario real que lo exija (no "por completitud"), o cuando el prototipo deje de ser local y de un
> solo proceso. Ejemplo ya promovido: **AMP-02 (PDF)**, ver `docs/11 §G`.

## 1. Arquitectura distribuida / continua

El prototipo usa **workers asíncronos** (un job por pipeline) que ejecutan cada etapa completa dentro
del proceso. El diseño de `docs/04 §5` imaginaba además un ciclo de vida con siete fases y tipos de
job separados; a esta escala no aporta.

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| FN-02 | `Job.progreso` incremental real (no solo 0→100) | El pipeline local termina en segundos; sería una barra 0→100 igual. Cosmético. | docs/11 §B (nota FN-02), `core/jobs.py` |
| OP-10 | Ciclo de vida completo (`creada→ingestando→…→completada`) y 7 tipos de job | La evaluación es atómica, inmutable y re-ejecutable; un fallo se ve por `job.error` y se reintenta entero. Fases = observabilidad, no función. | docs/04 §5 |
| OP-08 | Consumidores `log_ingest`/`log_aggregate` separados | Un solo job `event_ingest` ya corre normalizar→agregar→disparadores→incidentes. Partirlo solo escala por etapa. Simplificación deliberada. | docs/09 §11 |
| OP-07 | Ventanas deslizantes (stream continuo) | La ingesta es por lotes (JSONL); "una ventana = un lote" alcanza. El stream real es evolución. | docs/08 §11 |
| OP-06 | Cooldown / rate-limit real de incidentes (O4) | Idempotencia por `correlation_key` evita duplicados; el spam solo aparece en un stream continuo. | `ops/incidents.py` |
| API-01 | `POST /sources` + `/run` separados | El flujo es de un solo disparo desde la UI; las subidas ya quedan persistentes. | docs/09 §12/§16 |
| API-02 | `GET /assessments/{id}/scores` explícito | Redundante: los puntajes ya se pliegan en `GET /assessments/{id}` y ningún consumidor lo pide. | docs/04 §6 |
| OP-16 | Reintento automático de jobs huérfanos | `fail_if_stale` solo los marca `fallido`; reintentar automáticamente abre la puerta a duplicados y no hace falta en local. | docs/09 §20 |
| API-04 (parte) | Paginación por cursor y filtros en listados | Volúmenes mínimos y uso local. (`problem+json` y `methodology_version` siguen en docs/11.) | docs/04 §6 |
| TS-04 | Cobertura extra: handlers de la CLI, `test_methodology_loader`, ingesta con solape parcial | No protege ningún comportamiento crítico. | docs/09 §13/§25 |
| DEP-01 | Despliegue real (nginx + dominio, `VITE_API_BASE_URL`, `CORS_ORIGINS`) | El prototipo corre solo en local con Compose. | docs/09 §19 |

## 2. Persistencia de datos derivados

Todo se recalcula desde `criterion_results`, que es inmutable. Persistir crearía una segunda fuente
de verdad y bugs de invalidación.

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| OP-03 | Persistir `findings`/`score_aggregates`/`tier_estimates` | Recalcular es barato y siempre consistente; solo se justifica si el cálculo se vuelve costoso. | `recommendations/findings.py` |
| OP-02 | Tabla `ai_adjustments` (modelo, prompt_version, propuesta, justificación) | La justificación ya queda en `explanation` y los tests verifican las cotas; la tabla solo agrega consultabilidad. | `ai/adjustment.py` |
| OP-17 | Persistir `log.window` (hoy se recalcula desde `Event`) | Mismo patrón que OP-03: recálculo barato y sin segunda fuente de verdad. | docs/09 §11 |
| OP-18 | `Source` por archivo (hoy uno por adaptador) | Solo se necesita si se quiere trazabilidad por archivo individual. | docs/09 §11 |
| OP-13 (resto) | Tablas `evidence_definitions`/`criteria_catalog`, `incidents.pattern_ids`, `log_patterns.evidence_id` | La metodología es YAML-only por diseño (D5, criterios fijos); lo demás es pureza de modelo sin consumidor. (`schema_version` de la cola sigue en docs/11.) | docs/04 §3.1/§4 |

## 3. Contexto y tailoring

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| OP-09 | `ctx.profile`/`ctx.exclusions` como evidencia (sector, tamaño, activos críticos, datos, nube, exclusiones → `no_aplicable`) | Pipeline de contexto completo con efecto en el puntaje: investigación. El prototipo **no** prioriza por criticidad: la prioridad de un plan sale de la severidad del hallazgo. | docs/02 §3.5, docs/05 §4.2 |
| OP-01 | Prioridad de planes por criticidad de activo (incluso la "versión fina" de un campo) | Necesita una fuente de datos de criticidad, es decir el pipeline `ctx.*` (OP-09); sin él sería un campo arbitrario. | docs/05 §4.2 |

## 4. Seguridad para despliegue real

El prototipo corre **solo en local** (Docker Compose) y **no se despliega a producción/Internet**;
estas medidas no tienen superficie real aquí.
(NO se mantienen en el backlog del prototipo.)

| ID | Qué es |
|---|---|
| SEC-01 | `SECRET_KEY` obligatoria (hoy default de demo) |
| SEC-02 | Cookie `HttpOnly`+`SameSite` en vez de token en `localStorage` (implica CSRF) |
| SEC-03 | Decidir visibilidad de `/docs`, `/redoc`, `/openapi.json` (en demo conviene visible) |
| SEC-04 | Rate limiting / bloqueo por intentos en `/auth/login` |
| SEC-05 | Alta/administración de cuentas fuera del seed (CLI o panel admin) |
| SEC-06 | Rotar/eliminar credenciales de demo antes de uso real |
| SEC-07 | Redacción de patrones de secretos antes de enviar a la IA (`docs/02:120`, `docs/04 §9`) |
| SEC-08 | Límite de tamaño por archivo/evaluación (`docs/04 §9`) |
| SEC-09 | Registro por el cliente, recuperación/cambio de contraseña, OAuth/SSO/MFA, roles granulares y refresh tokens (`docs/10 §1`) |

> El **path traversal** de las subidas (nombre de archivo crudo del cliente) **se corrigió** en el
> prototipo (`app/core/uploads.py`, docs/09 §35): no forma parte de esta lista.

## 5. Ampliaciones de investigación / producto

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| AMP-01 | Recuperación semántica (embeddings) sobre el catálogo NIST | El motor es determinístico y basado en reglas + evidencia estructurada; añade proveedor, índice, costo y no-determinismo. | docs/07 §2/§7 |
| AMP-06 | Niveles por función A/B/C/D (Consolidado/Gestionado/…) | El diseño lo marca opcional y no-NIST. | docs/01 §8.4 |
| AMP-08 | `CRI-GV-05` en el cruce de privacidad (`PRIVACY_CRITERIA`) | `GV.OC-03` nombra explícitamente los requisitos de privacidad, pero eso es **Govern-P** del PF 1.0, y el alcance declarado del cruce (docs/00 §6, docs/03 §7) son Identify-P, Protect-P y los eventos. Añadirlo ensancha un límite de alcance que el informe también enuncia, así que es una decisión de alcance y no un detalle de UI. | docs/09 §73 |
| AMP-07 | Procedencia de módulos y proveedores de Terraform (`tf.module.source`) como señal técnica de cadena de suministro (GV.SC-07, ID.RA-09) | El adaptador solo lee bloques `resource`; exige una ruta de parseo nueva, un tipo de evidencia y fixtures en los tres paquetes, para una subcategoría que GV.SC ya cubre por vía documental. | docs/04 §3 |

### Subcategorías que el mapeo no podía declarar: cerrado

La Oleada 0 (docs/09 §70) dejó aquí tres subcategorías que las reglas no evidenciaban —`ID.RA-04`,
`DE.AE-03` y `RS.MA-05`— con el coste de hacerlas honestas anotado, para no re-razonarlo. **Las tres
están hechas**: `DE.AE-03` en docs/09 §75 (`log.pattern@2` conserva los orígenes del patrón) y las
otras dos en §76 (campos nuevos de `process_defined`), junto con `ID.IM-04`, que la Oleada A había
dejado fuera por el mismo motivo.

Esta sección se mantiene vacía a propósito: si una oleada futura vuelve a descartar una
subcategoría, su motivo y su coste van aquí, no en la cabeza de nadie.

*(AMP-04, cobertura de implementación, se promovió al prototipo y está hecha: `methodology/csf_subcategories.yml`
con las 106 subcategorías, `app/methodology/coverage.py` y `GET /methodology` — ver docs/09 §68.)*

*(AMP-02, exportación PDF, se promovió al prototipo y está hecha: separa el acceso a la herramienta
del acceso a los resultados y da oficialidad al informe — ver `docs/11 §G`, docs/09 §44.)*

## 6. Obsoleto / no aplica

| ID | Motivo |
|---|---|
| FN-04 | El botón "Reevaluar" se eliminó (UI-10); no hay dónde exponer el toggle de IA. El endpoint sigue aceptando `ai_adjust`. |
| CAL-01 | Modelado de calendario aproximado (meses de 28–31 días): aproximación aceptada; no se necesita calendario real. |
