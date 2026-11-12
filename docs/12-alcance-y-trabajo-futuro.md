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
| OP-16 | Reintento automático de jobs huérfanos | Promovido en parte (docs/09 §104): el worker re-ejecuta un job dado por perdido en la cola; no se reintenta el de un worker muerto. | docs/09 §104 |
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
| AMP-09 | Validar `valor_schema` de verdad | `evidence_types.yml` declara un `valor_schema` por tipo y `methodology/schemas.py` lo tipa como `dict`, pero **nunca se ejecuta**: no hay jsonschema y nada valida `EvidenceInstance.value` contra él. `modalidad_permitida` y `requiere_locator` tampoco se hacen cumplir. Con los **seis tipos nuevos** de la Oleada C el contrato de evidencia es hoy documentación, no garantía: un adaptador que emitiera una clave mal escrita no fallaría al arrancar, fallaría en una regla con un `KeyError` o, peor, con un `.get()` que devuelve `None` y baja un puntaje en silencio. Coste: una dependencia de jsonschema, validar en `loader.py` al cargar y en los adaptadores al emitir (o solo en los tests, que ya sería la mitad del valor). | docs/02, docs/09 §90-§94 |
| AMP-10 | Topología de red como señal (`aws_vpc`/`subnet`/`route_table`) para `ID.AM-03` | Alcanzable y del mismo tipo que lo que hizo la Oleada C, pero es otra familia de recursos y otra forma de evidencia (una representación de flujos, no un atributo por recurso). Se dejó fuera para no estirar la oleada. | docs/09 §90 |
| AMP-08 | `CRI-GV-05` en el cruce de privacidad (`PRIVACY_CRITERIA`) | `GV.OC-03` nombra explícitamente los requisitos de privacidad, pero eso es **Govern-P** del PF 1.0, y el alcance declarado del cruce (docs/00 §6, docs/03 §7) son Identify-P, Protect-P y los eventos. Añadirlo ensancha un límite de alcance que el informe también enuncia, así que es una decisión de alcance y no un detalle de UI. | docs/09 §73 |
| AMP-11 | Votación de U2/U3 y retención/limpieza de `ai_results` | U1 ya vota 3 corridas en un miss; U2 (ajuste, una llamada por criterio) y U3 (planes) siguen siendo una sola llamada, y votarlas triplicaría el costo de ~75 % de las llamadas para ganar precisión sobre una salida que J1–J7 ya acotan. `ai_results` crece sin TTL ni purga: es barato a esta escala, pero un despliegue largo necesita una política de retención (por antigüedad o por organización) y un job de limpieza. | docs/05 §7/§8, docs/09 §105 |

**Deuda medida del golden set:** con `extract_v7` la corrida real quedó en recall 85 % (50/59) y en
citas localizables 96 %; con `extract_v8` y el voto por presencia quedó en recall 95 % (56/59),
precisión 100 % y citas 99,7 % (docs/05 §8, docs/09 §115). Las tres afirmaciones no cubiertas siguen
siendo trabajo futuro: con 59 afirmaciones una pesa casi 2 pp.

**Límite conocido, sin resolver (docs/09 §114):** un mismo documento que afirma una práctica como
vigente y la niega en otro fragmento (misma faceta) sigue acreditando la afirmación más confiable
(§101). Solo se anota la contradicción de booleanos; la de existencia entre documentos distintos sí
excluye a ambos lados. Se dejó así porque un documento puede negar un aspecto concreto de una
práctica que sí tiene, y anular la práctica entera castigaría documentos legítimos; hacerlo visible
con un hallazgo es la mejora natural.

### Subcategorías que el mapeo no podía declarar: cerrado

La Oleada 0 (docs/09 §70) dejó aquí tres subcategorías que las reglas no evidenciaban —`ID.RA-04`,
`DE.AE-03` y `RS.MA-05`— con el coste de hacerlas honestas anotado, para no re-razonarlo. **Las tres
están hechas**: `DE.AE-03` en docs/09 §75 (`log.pattern@2` conserva los orígenes del patrón) y las
otras dos en §76 (campos nuevos de `process_defined`), junto con `ID.IM-04`, que la Oleada A había
dejado fuera por el mismo motivo.

**AMP-07 también está cerrado** (docs/09 §90): el adaptador de Terraform leía solo bloques
`resource` aunque el parser ya le entregaba `module`, `provider` y `terraform`. La Oleada C añadió
esa segunda ruta de parseo, generalizó los rangos de línea a cualquier tipo de bloque y cubrió
`ID.RA-09` con `tf.module.source` y `tf.provider.version`. `GV.SC-07`, que la Oleada B cubrió por vía
documental, pasa a tener además respaldo determinístico.

### Las 25 subcategorías descubiertas, y por qué

El sistema cubre **81 de las 106** del CSF 2.0. Esta sección da el motivo de las **25 restantes**,
una por una, para que la afirmación del proyecto no sea un porcentaje sino algo más fuerte:
**cada subcategoría del marco tiene un criterio que la evalúa o un motivo escrito de por qué no lo
tiene.** `tests/test_csf_scope_documented.py` lo comprueba, así que la lista no puede quedarse atrás
de `criteria.yml`.

No son todas lo mismo, y meterlas en una sola lista de "fuera de alcance" sería tan flojo como no
decir nada. Van en tres grupos: las que el alcance declarado no puede evidenciar, las que **no se
deben** declarar aunque parezca que se puede, y las que sí son alcanzables y solo esperan su oleada.

#### (a) Fuera del alcance declarado: ninguna de las tres fuentes las evidencia

| Subcategoría | Por qué no |
|---|---|
| `PR.AA-02` (verificación y vinculación de identidad según el contexto) | Es un proceso de *identity proofing*. Nada en Terraform lo observa, y no hay campo de afirmación que lo evidencie sin volverse opinable. |
| `PR.AA-04` (aserciones de identidad protegidas, transmitidas y verificadas) | `aws_iam_saml_provider`/`aws_iam_openid_connect_provider` serían la señal, pero no hay federación en el alcance del prototipo: el fixture sería un adorno y el criterio mediría el fixture. |
| `PR.AA-06` (acceso físico) · `PR.IR-02` (amenazas ambientales) · `DE.CM-02` (entorno físico) · `DE.CM-03` (actividad del personal) · `PR.PS-03` (hardware) | **No alcanzables por diseño.** Son físicas o de personal, y este prototipo evalúa IaC, documentos y logs. Es un límite del alcance declarado (docs/00 §6), no una tarea pendiente. |
| `PR.PS-05` (impedir la instalación y ejecución de software no autorizado) | Pediría *allowlisting* (AppArmor, SELinux enforcing, firma de paquetes). Un `service: apparmor enabled` sería una señal muy fina para sostener la subcategoría entera. |
| `PR.PS-06` (prácticas de desarrollo seguro) | Pediría señal de CI/CD, que no es ninguna de las tres fuentes del prototipo. |
| `ID.RA-02` · `ID.RA-07` · `ID.RA-08` · `ID.RA-10` · `ID.AM-04` · `ID.AM-08` | Procesos de gobierno (inteligencia de amenazas, gestión de cambios, divulgación de vulnerabilidades, riesgo de proveedores, inventario de servicios de terceros, ciclo de vida de activos). Son documentales, no técnicos: una oleada futura podría cubrirlos con campos de afirmación, con el coste conocido de no estar medidos contra el modelo real. |
| `PR.DS-10` (datos **en uso**) | Pide *confidential computing*: enclaves o cifrado de memoria. No se expresa en el subconjunto de IaC que el adaptador lee, y tampoco es una afirmación documental — es una propiedad del tiempo de ejecución. Con ella, `PR.DS` queda en 3/4 y no puede completarse. |
| `DE.AE-07` (inteligencia de amenazas integrada al análisis) | Un *feed* de amenazas no es ninguna de las tres fuentes del prototipo. Misma familia que `ID.RA-02`, arriba. |
| `DE.CM-06` (monitoreo de actividades y servicios de proveedores externos) | El esquema de eventos tiene `fuente` (el sistema que emite el evento), pero **ningún concepto de tercero como actor**, y los seis escenarios no modelan proveedores. Declararla exigiría cambiar el modelo de eventos antes que añadir un criterio. |
| `RC.CO-04` (actualizaciones **públicas** sobre la recuperación) | Comunicación externa durante un incidente. No la registra el IaC, ni los logs de operación, ni los documentos del alcance. |

#### (b) Alcanzables en apariencia, descartadas por circularidad

Este grupo es el que más merece estar escrito, porque la tentación de declararlas es real y el
atajo sería invisible en los números.

| Subcategoría | Por qué no |
|---|---|
| `DE.AE-04` (impacto y alcance estimados de los eventos adversos) · `RS.AN-08` (estimar y validar la magnitud del incidente) | La entidad `Incident` **ya tiene `severidad`** (`app/models/tables.py`), así que las dos parecen a un paso. No lo están: esa severidad **la asigna un disparador determinístico del propio sistema** (`app/ops/triggers.py`), no un analista estimando impacto. Declararlas sobre ese campo sería evaluar como práctica de la organización lo que la herramienta acaba de calcular sola: cobertura que sube sin una sola evidencia nueva. Para cubrirlas de verdad haría falta una afirmación documental sobre **cómo** la organización estima la magnitud, o un campo de magnitud puesto por quien vive el incidente. Es el mismo principio del silencio documental (docs/09 §60): para afirmar algo hay que observarlo, y la salida propia no es una observación. |

#### (c) Alcanzables: no son un límite, son coste anotado

| Subcategoría | Qué costaría |
|---|---|
| `ID.AM-03` (representación de la comunicación de red y del flujo de datos) | Alcanzable por vía técnica: ver **AMP-10**. |
| `RC.RP-06` (declarar el fin de la recuperación según criterios) | **La más cercana de las nueve.** El incidente ya se cierra con `motivo_cierre` obligatorio (docs/09 §52), pero eso es una acción del usuario sobre la API, no evidencia observada de la práctica. Haría falta un tipo de evento (`recovery_completed`) en `_EXISTENCE_PATTERNS` (`app/surveillance/patterns.py`) y que `CRI-RC-03` lo consuma: exactamente la forma de lo que hizo la Oleada A con `containment_done` (docs/09 §72). Completaría `RC.RP` salvo por `RC.RP-04`. |
| `RS.CO-03` (compartir información del incidente con las partes interesadas designadas) | `CRI-RS-03` cubre `RS.CO-02`, que es el **plan** de notificación, con `doc.claim`. Lo que falta es el **acto** de notificar durante la respuesta: un evento `stakeholders_notified`, hermano del `recovery_communicated` que ya existe para `RC.CO-03`. |
| `RC.RP-04` (considerar las funciones críticas y el riesgo al ejecutar la recuperación) | Un campo documental más en el proceso de recuperación, con el **coste conocido** de esa vía: sube la cobertura sin estar medido contra el modelo real, que es la deuda que la Oleada B dejó abierta y que sigue sin saldarse. |

Esta sección se mantiene al día a propósito, y ahora con un test detrás: si una oleada cubre una de
estas, hay que sacarla de aquí; si descarta otra, su motivo y su coste van aquí, no en la cabeza de
nadie.

*(AMP-04, cobertura de implementación, se promovió al prototipo y está hecha: `methodology/csf_subcategories.yml`
con las 106 subcategorías, `app/methodology/coverage.py` y `GET /methodology` — ver docs/09 §68.)*

*(AMP-02, exportación PDF, se promovió al prototipo y está hecha: separa el acceso a la herramienta
del acceso a los resultados y da oficialidad al informe — ver `docs/11 §G`, docs/09 §44.)*

## 6. Obsoleto / no aplica

| ID | Motivo |
|---|---|
| FN-04 | El botón "Reevaluar" se eliminó (UI-10); ya no hay toggle de IA que exponer: la UI envía siempre `use_ai`/`ai_adjust=true` y la IA corre si hay `DEEPSEEK_API_KEY`. El endpoint sigue aceptando `ai_adjust`. |
| CAL-01 | Modelado de calendario aproximado (meses de 28–31 días): aproximación aceptada; no se necesita calendario real. |
