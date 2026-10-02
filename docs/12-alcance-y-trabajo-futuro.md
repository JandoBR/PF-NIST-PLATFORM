# 12 — Alcance, limitaciones y trabajo futuro

Registro de lo que el diseño describe pero el **prototipo descarta deliberadamente**, y que sí
tendría sentido a mayor escala. No es un backlog: `docs/11` lista lo pendiente del prototipo; este
documento es el **índice de decisiones de alcance**, con el motivo en una línea y el detalle en el
documento donde vive la explicación. La idea es no re-razonar cada vez que alguien se pregunte "¿por
qué no está esto?" ni mantener estos ítems como si fueran deuda del prototipo.

- Detalle de arquitectura: `docs/04 §5`, `docs/09 §11`.
- Trabajo futuro de producto: `docs/07 §7`.
- Precedencia y contradicciones: `docs/02 §5`.

> **Criterio de promoción:** un ítem de esta lista vuelve al backlog (`docs/11`) cuando exista un
> escenario real que lo exija (no "por completitud"), o cuando el prototipo deje de ser local y de un
> solo proceso. Ejemplo ya promovido: **AMP-02 (PDF)**, ver `docs/11 §G`.

## 1. Arquitectura distribuida / continua

El prototipo es un proceso síncrono con colas Redis que ejecuta cada etapa completa. El diseño de
`docs/04 §5` imaginaba un motor de larga duración; a esta escala no aporta.

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| FN-02 | `Job.progreso` incremental real (no solo 0→100) | El pipeline local termina en segundos; sería una barra 0→100 igual. Cosmético. | docs/11 §B, `core/jobs.py` |
| OP-10 | Ciclo de vida completo (`creada→ingestando→…→completada`) y 7 tipos de job | La evaluación es atómica, inmutable y re-ejecutable; un fallo se ve por `job.error` y se reintenta entero. Fases = observabilidad, no función. | docs/04 §5 |
| OP-08 | Consumidores `log_ingest`/`log_aggregate` separados | Un solo job `event_ingest` ya corre normalizar→agregar→disparadores→incidentes. Partirlo solo escala por etapa. Simplificación deliberada. | docs/09 §11 |
| OP-07 | Ventanas deslizantes (stream continuo) | La ingesta es por lotes (JSONL); "una ventana = un lote" alcanza. El stream real es evolución. | docs/08 §11 |
| OP-06 | Cooldown / rate-limit real de incidentes (O4) | Idempotencia por `correlation_key` evita duplicados; el spam solo aparece en un stream continuo. | `ops/incidents.py` |
| API-01 | `POST /sources` + `/run` separados | El flujo es de un solo disparo desde la UI; las subidas ya quedan persistentes. | docs/09 §12 |

## 2. Persistencia de datos derivados

Todo se recalcula desde `criterion_results`, que es inmutable. Persistir crearía una segunda fuente
de verdad y bugs de invalidación.

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| OP-03 | Persistir `findings`/`score_aggregates`/`tier_estimates` | Recalcular es barato y siempre consistente; solo se justifica si el cálculo se vuelve costoso. | `recommendations/findings.py` |
| OP-02 | Tabla `ai_adjustments` (modelo, prompt_version, propuesta, justificación) | La justificación ya queda en `explanation` y los tests verifican las cotas; la tabla solo agrega consultabilidad. | `ai/adjustment.py` |

## 3. Contexto y tailoring

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| OP-09 | `ctx.profile`/`ctx.exclusions` como evidencia (sector, tamaño, activos críticos, datos, nube, exclusiones → `no_aplicable`) | Pipeline de contexto completo con efecto en el puntaje: investigación. El prototipo resuelve la prioridad de planes con un campo de criticidad (OP-01, versión fina), que es lo único con valor inmediato. | docs/02 §3.5, docs/05 §4.2 |

## 4. Seguridad para despliegue real

El prototipo corre **solo en local** y no se despliega; estas medidas no tienen superficie real aquí.
(NO se mantienen en el backlog del prototipo.)

| ID | Qué es |
|---|---|
| SEC-01 | `SECRET_KEY` obligatoria (hoy default de demo) |
| SEC-02 | Cookie `HttpOnly`+`SameSite` en vez de token en `localStorage` (implica CSRF) |
| SEC-03 | Decidir visibilidad de `/docs`, `/redoc`, `/openapi.json` (en demo conviene visible) |
| SEC-04 | Rate limiting / bloqueo por intentos en `/auth/login` |
| SEC-05 | Alta/administración de cuentas fuera del seed (CLI o panel admin) |
| SEC-06 | Rotar/eliminar credenciales de demo antes de uso real |

## 5. Ampliaciones de investigación / producto

| ID | Qué es | Por qué no en el prototipo | Detalle |
|---|---|---|---|
| AMP-01 | Recuperación semántica (embeddings) sobre el catálogo NIST | El motor es determinístico y basado en reglas + evidencia estructurada; añade proveedor, índice, costo y no-determinismo. | docs/07 §2/§7 |

*(AMP-02, exportación PDF, se promovió al prototipo: separa el acceso a la herramienta del acceso a
los resultados y da oficialidad al informe — ver `docs/11 §G`.)*

## 6. Obsoleto / no aplica

| ID | Motivo |
|---|---|
| FN-04 | El botón "Reevaluar" se eliminó (UI-10); no hay dónde exponer el toggle de IA. El endpoint sigue aceptando `ai_adjust`. |
