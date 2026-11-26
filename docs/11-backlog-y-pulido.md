# 11 — Backlog y Pulido

Lista de trabajo viva. No es un changelog: cuando algo se implementa, se registra en
`docs/09-registro-de-implementacion.md` y se marca aquí como hecho (o se borra).

Prioridades: **P0** bloquea valor central · **P1** importante · **P2** deseable.
IDs estables para referenciarlos en commits/PRs.

> Lo **descartado deliberadamente** para el prototipo (pero válido a mayor escala) no figura aquí:
> vive en `docs/12-alcance-y-trabajo-futuro.md`. Este backlog es solo trabajo que sí haremos.

## A. UI / UX (pulido)

### [x] UI-01 · Privacidad visible (P1)
Hoy la dimensión de privacidad (secundaria) casi no aparece en la UI, pese a estar en el diseño
(docs/00 §6, docs/03 §7). Objetivo: que se vea como parte del producto, con su aclaración de
alcance.
- Añadir una sección "Privacidad relacionada con ciberseguridad" en el Resumen de Madurez, armada
  con los criterios del cruce (`ID-04`, `PR-01/03/05`, `DE-02`, `RS-01/03`, `RC-01/02/03`).
- Marcar esos criterios con un badge "privacidad" en la tabla de criterios.
- Mostrar en el reporte la nota de alcance ("cubre eventos de ciberseguridad que afectan datos
  personales; no es una evaluación integral de privacidad", docs/00 §6).
- Depende de implementar `ID-04` y `RS-03` (ver CR-02/CR-03).
- **Hecho:** en vez de una tarjeta aparte, es una vista alternativa (**Criterios / Privacidad**) dentro
  de la sección de criterios; muestra relación PF/CSF, score/cobertura del cruce y la nota de alcance.
  Los criterios del cruce implementados aparecen solos; `ID-04` y `RS-03` se sumaron con CR-03.
- **Detalle desplegable:** cada fila se expande para ver la explicación completa (antes se truncaba
  sin forma de leer el resto) + score base/final y evidencias.

### [x] UI-02 · "Regenerar" en Recomendaciones (P2)
El botón de regenerar plantilla no tiene una función clara y hoy es redundante (los planes ya se
generan desde la plantilla). Decidir: quitarlo, o dejarlo solo cuando no hay planes, o renombrarlo
y explicar qué hace. Criterio: que ningún botón exista sin efecto perceptible.
- **Hecho:** los planes (plantilla) se generan **solos** al completar la evaluación
  (`run_pending_assessment`, docs/09 §25); se quitó el botón manual. En Recomendaciones solo queda
  "Regenerar con IA" (explícito, sujeto al guard de costo). Provisional: a futuro se generará
  directamente con IA y se eliminará la plantilla.
  Posterior (docs/09 §116): "Regenerar con IA" también se quitó de la UI.

### [x] UI-03 · Toggles de IA momentáneos (P1)
Los checkboxes de IA (U1/U2) son **por corrida**: existen para no gastar tokens, no son una
preferencia persistente. Hoy su estado sobrevive al cerrar/abrir el modal, lo que da a entender lo
contrario.
- Volver a `false` al cerrar/enviar el modal (o al completarse la corrida).
- Texto explícito: "solo aplica a esta evaluación; se resetea".
- (Opcional) tooltip con el costo estimado / que sin `DEEPSEEK_API_KEY` no tiene efecto.
- **Cambiado (superado):** ya no hay checkboxes ni confirmación en la UI. El frontend envía siempre
  `confirm_live_ai=true` y `use_ai`/`ai_adjust=true`; la IA corre solo si el backend tiene
  `DEEPSEEK_API_KEY` (sin key: `NullAIClient`, puntajes base y cero costo). La API directa sigue
  exigiendo `confirm_live_ai` cuando hay clave, como guard de costo.

### [x] UI-04 · Hallazgo → plan inline (P1)
En Recomendaciones, tocar un hallazgo debería **desplegar su plan de acción** en el lugar (como hace
Eventos e Incidentes con sus incidentes), en vez de tener un botón que salta a otra sección.
- Acordeón por hallazgo: pasos, verificación, prioridad, `generado_por`.
- Si no hay plan generado para el hallazgo, ofrecer "generar plan" desde ahí.
- **Hecho:** con esto se eliminó la pestaña "Plan de Acción" (era redundante); la lista de hallazgos
  pasó a ordenarse por prioridad y a llevar los filtros de prioridad.

### [x] UI-05 · Renombrar "Simulación de Amenazas" (P1)
No es una simulación: son **eventos/amenazas reales** ingestados. Renombrar la pestaña y sus textos
(p. ej. "Vigilancia Operativa" o "Eventos e Incidentes"), y quitar la palabra "simulación" de la UI
(el nombre del fixture puede quedar interno).

### [x] UI-06 · Incidentes: reemplazo/archivo e historial (P1)
Al ingerir otro log ("Con incidentes" → "Flujo correcto") los incidentes anteriores no desaparecen
ni se reemplazan; al marcar un incidente como completado tampoco sale de la lista. Objetivo: que la
pestaña refleje el estado actual y conserve un historial.
- Al ingerir un log nuevo, refrescar/reemplazar la vista según el resultado de esa ingesta.
- Cerrar un incidente ("completado") lo mueve a un **historial de incidentes** dentro de la misma
  pestaña (pestañas o filtro activos/historial).
- Requiere que el backend permita cambiar el estado de un incidente (hoy es de solo lectura desde la
  API): ver OP-04.
- **Hecho:** pestañas **Activos / Historial**; cerrar un incidente lo mueve al historial (usa el
  `PATCH /incidents/{id}` de OP-04, docs/09 §24).

### [x] UI-07 · Comparación más explícita + gráficos (P1)
La pestaña de comparación debería explicar *qué* cambió, no solo listarlo.
- Vista tipo Resumen de Madurez, enfocada en el diff: función/categoría con score y cobertura,
  delta (↑/↓), criterios que cambiaron y por qué (dirección del cambio).
- Gráfico de cambios: score global y cobertura global (barras antes/después), y selector para ver el
  cambio por función/categoría.
- (Opcional) exportar la comparación.

### [x] UI-08 · Seguimiento del plan (P1)
Que el usuario pueda marcar el avance de una recomendación (`pendiente` · `en_progreso` · `hecho`)
sin que eso finja que el criterio está implementado. Es **seguimiento**, no evaluación: el puntaje
sigue saliendo de la evidencia (docs/05 §4.4).
- **Hecho:** `plans.estado` persistido + `PATCH /assessments/{id}/plans/{plan_id}`; control por
  hallazgo y contador "X de Y hechos" en Recomendaciones. Se conserva al regenerar. Decidido en
  contra de un "implementado" que ajuste el puntaje (rompería determinismo/reproducibilidad).
- **Herencia:** hecho — al reevaluar **o volver a evaluar el mismo org+scope**, el seguimiento se
  hereda por `criterion_id` desde la evaluación completada inmediatamente anterior
  (`Assessment.previous_assessment_id`, autodetectado; docs/05 §4.4).

### [x] UI-09 · Eventos e incidentes sin depender de la evaluación (P1)
Antes la pestaña de eventos/incidentes usaba `org_id` de la evaluación activa y no se podía abrir
sin una evaluación. Deben funcionar con la organización de la **sesión**.
- **Hecho:** la pestaña usa `user.org_id`/`user.org_nombre` y se puede abrir sin evaluación. Backend
  ya era independiente (`/orgs/{id}/events`, `/orgs/{id}/incidents`).

### [x] UI-10 · Quitar el botón "Reevaluar" (P2)
Con el refresco automático (FN-05), reevaluar "porque sí" no aporta (mismo input ⇒ mismo resultado).
- **Hecho:** se quitó del Resumen de Madurez. El endpoint `POST /assessments/{id}/reevaluate` se
  conserva porque lo usa el refresco automático (y la CLI).

## B. Funcionalidad pendiente (lo que reportó Claude)

- [x] FN-01 · **Historial de jobs**. Hecho (docs/09 §45): `GET /jobs` y vista "Actividad" (botón en la cabecera, en lugar del indicador de la API).
- [x] FN-09 · **Reintentar un job fallido** (P1). Hecho (docs/09 §46): `POST /jobs/{id}/retry` y botón
  "Reintentar". Para poder hacerlo, los jobs ahora guardan sus entradas (`jobs.payload`).
- [x] FN-03 · **Ingesta "nuevos vs actualizados"**. Hecho (docs/09 §51): `jobs.resultado` con eventos nuevos vs
  ya existentes, patrones e incidentes; lo muestran la UI y la CLI.
- [~] FN-04 · **Toggle de IA en "Reevaluar"** (P2): **obsoleto** — el botón "Reevaluar" se eliminó
  (UI-10); ya no hay dónde preguntarlo. El endpoint sigue aceptando `ai_adjust`.
- [x] FN-05 · **Refresco automático de madurez al ingerir** (P1): `worker-logs` encola una
  reevaluación de la última evaluación completada del `org`+`scope` cuando la ingesta suma al menos
  `vigilancia.refresco_min_patrones_nuevos` patrones nuevos (default 3). No pide nada al usuario;
  no dispara sin evaluación previa, con evaluación en vuelo, ni bajo el umbral (docs/08 §8).
- [x] FN-06 · **Refresco selectivo** (P1): hecho. `run_surveillance_refresh` reusa evidencia,
  resultados y planes de los criterios no operativos (preserva IA: claims U1, ajuste U2, texto de
  planes) y recalcula solo los criterios de vigilancia con los patrones frescos; hereda el estado de
  seguimiento. El worker lo dispara con `selective_refresh=True` (docs/06 §6, docs/09 §29).
- [x] FN-07 · **Origen del evento**. Hecho (docs/09 §50): `fuente` → `events.source_id`, `log_patterns.fuentes` y
  el `source_id` de la evidencia operativa.
- [x] FN-08 · **Patrones sin consumidor**. Hecho (docs/09 §53): `incident_triaged` lo consume D2; `containment_done` queda
  como patrón de solo contexto, documentado.

> `FN-02` (progreso real del job) **descartado** para el prototipo: ver docs/12 §1.

## C. Cobertura de criterios y Tier (P0)

El catálogo implementa **31 de 31** criterios de docs/03 (`criteria.yml` v25). Cobertura por función:
GV 6/6 · ID 6/6 · PR 9/9 · DE 3/3 · RS 4/4 · RC 3/3.
- **Cobertura del marco (AMP-04):** **81 de 106 subcategorías (76,4 %), 22 de 22 categorías y 10
  completas**, calculada por el sistema (`GET /methodology`) y visible en el dashboard
  (docs/09 §70-§94). `categorias_sin_criterio` quedó vacía con la Oleada A, la Oleada B dejó la
  **función Gobernar completa (31/31)** y la Oleada C sacó a **Proteger de 8/22 a 14/22** con señal
  técnica nueva en los adaptadores (docs/09 §90-§94).
  Cobertura por función en subcategorías: GV 31/31 · RS 11/13 · ID 14/21 · PR 14/22 · RC 5/8 ·
  DE 6/11.
  Lo que falta se reparte así (`categorias_incompletas`): `ID.RA` (4), `ID.AM` (3), `PR.AA` (3),
  `PR.PS` (3), `DE.CM` (3), `DE.AE` (2), `RC.RP` (2), y una sola en `PR.DS`, `PR.IR`, `RS.AN`,
  `RS.CO` y `RC.CO`. **Las 25 tienen su motivo escrito en docs/12 §5** (docs/09 §96), repartidas en
  tres grupos: **13 fuera del alcance declarado** (5 físicas o de personal, 4 que pedirían *identity
  proofing*, federación, *allowlisting* o señal de CI, y `PR.DS-10`, `DE.AE-07`, `DE.CM-06` y
  `RC.CO-04`), **2 descartadas por circularidad** (`DE.AE-04` y `RS.AN-08`: el sistema no puede
  puntuarse con la severidad que él mismo asigna) y **10 alcanzables** con su coste anotado —de
  ellas `ID.AM-03`, `RC.RP-06` y `RS.CO-03` por vía técnica, y siete con campos documentales, con la
  deuda conocida de no estar medidos contra el modelo real.
  `tests/test_csf_scope_documented.py` impide que esa lista se quede atrás del catálogo.
- **UI (hecho):** la matriz muestra siempre las **6 funciones**; una sin criterios aparece como
  "Sin criterios" (borde punteado) en vez de desaparecer (docs/09 §30).

- [x] CR-01 · Implementar los **7 MVP faltantes** (P0): `GV-02`, `ID-03` (desbloquean Tier 2),
  `RC-01`, `DE-01`, `GV-03`, `ID-01`, `ID-02`. Hecho (docs/09 §31). `criteria.yml` v2.
- [x] CR-02 · Completar Tier 3/4: `GV-04`, `RS-02`. Hecho (docs/09 §32). `criteria.yml` v3.
- [x] CR-03 · `RS-03` (notificación) e `ID-04` (inventario de datos) para la privacidad (ver UI-01).
  Hecho (docs/09 §32); la vista de privacidad ya los muestra.
- [x] CR-04 · `DE-02` incorpora `doc.claim(process_defined)` y llega a 100 cuando hay criterios de
  declaración + evidencia operativa. Hecho (docs/09 §33).
- [x] CR-05 · Los criterios operativos restantes alcanzan 100 con `doc.claim`: `PR-02` (política de
  backups), `RS-01` (plan de respuesta + escalamiento), `RC-02` (verificación de integridad) y
  `RC-03` (notificación documentada). Hecho (docs/09 §34). `criteria.yml` v5. (`RS-02` ya lo hacía
  desde CR-03.)
- [x] CR-06 · **Evidencia declarada sin consumir**. Hecho (docs/09 §36), `criteria.yml` v6:
  `tf.expression.unresolved` se emite (RDS, S3, SG, CloudTrail) y las reglas lo declaran como
  limitación; `PR-02` exige cifrado confirmado para el 100; `PR-04` consume `an.file.permissions`;
  `PR-05` informa `tf.versioning.config`; `DE-01` cita `log.window`; `PR-01` cita `policy_exists`
  junto a una brecha sin elevar el puntaje.
- [x] CR-07 · **Tipos de evidencia sin productor**. Resuelto (docs/09 §57): `doc.source.info` se implementó; `tf.attr.value` y
  `log.event` se declararon fuera de alcance.

> Nota transversal: los criterios con componente **documental** (`GV-02/03/04`, `ID-02/03/04`,
> `RC-01`, `RS-02/03`) dependen de `doc.claim` extraído por U1; sin IA quedan
> `evidencia_insuficiente` (igual que `GV-01`). Los **mixtos** (`ID-01`, `DE-01`, `DE-02`, `DE-03`,
> `PR-02`, `RS-01`, `RS-02`, `RC-02`, `RC-03`) tienen además una parte determinística
> (Terraform/Ansible/logs) que puntúa sin IA, aunque su tope alto suele exigir el `doc.claim`.

## D. Simplificaciones activas (docs/09 §11) — pendientes del prototipo

- [x] OP-04 · **Transiciones de estado de incidente** (`PATCH /incidents/{id}`, docs/09 §24), **hallazgos
  `contradiccion`** (docs/09 §38) y **hallazgos `limitacion`** (docs/09 §56). Completo.
- [x] OP-05 · Trigger D2 (`alert_raised` sin `incident_triaged`). Hecho (docs/09 §53).
- [x] OP-11 · **Plan/incidente** (lo útil). Hecho (docs/09 §52): transiciones de estado validadas y motivo de cierre
  obligatorio. Quedan fuera, por opcionales, `brecha_ref` en el plan y la "condición de cierre".
- [x] OP-12 · **Contratos de IA**. Hecho (docs/09 §37): reintento con backoff exponencial (1 s, 2 s),
  registro JSON por llamada (`app.ai.calls`: paso, `prompt_version`, `criterion_id`/`doc_id`,
  resultado, intentos, duración, tokens), validación E5 de fechas/frecuencias/roles y
  `ia.max_criterios_ajustados_por_evaluacion` en `settings.yml` (desactivado por defecto).
- [x] OP-13 · **`schema_version` en el contrato de mensaje de la cola**. Hecho (docs/09 §49). El resto de OP-13
  (`evidence_definitions`/`criteria_catalog`, `incidents.pattern_ids`, `log_patterns.evidence_id`,
  `Source` por archivo) pasó a docs/12 §2.
- [x] OP-14 · **Reproducibilidad**. Hecho (docs/09 §37): `assessments.reproducibility` guarda
  versión de adaptador y parser por fuente y, si la IA participó, modelo y versión de prompt de
  extracción/ajuste/planes (docs/01 §10). Expuesto en `GET /assessments/{id}`.
- [x] OP-15 · **Contrato menor de evidencia**. Hecho (docs/09 §54): `line_start/line_end` en Terraform y Ansible, limitación
  de recursos no soportados y `created_by` alineado. `resuelto_por` se descartó (el adaptador no resuelve variables a propósito).

> Descartados para el prototipo (OP-02, OP-03, OP-06…OP-10): ver **docs/12**.

## E. API / contratos faltantes (docs/04 §6)

- [x] API-03 · `GET /jobs` (listado, filtrable por estado y tipo). Hecho (docs/09 §45).
- [x] API-04 · **Convenciones**. Hecho (docs/09 §55): todos los errores en `problem+json` y `X-Methodology-Version` en toda
  respuesta. (La paginación por cursor y los filtros en listados siguen en docs/12 §1.)

> Descartados para el prototipo (API-01 `sources`+`run` separados, API-02 `GET /scores`): ver **docs/12 §1**.

- [ ] API-05 · **Una evaluación no debe quedar `pendiente` si no se puede encolar su job** (P2).
  Encontrado al verificar la Oleada C en el navegador, con Redis apagado: `POST /assessments` crea
  la fila, falla al encolar con `ConnectionRefusedError` y devuelve 500, dejando la evaluación en
  `pendiente` para siempre y sin job. Es la **misma forma** del bug que `_parse_context`
  (`routes_assessments.py`) ya arregló para un `context` con JSON inválido —crear primero y validar
  después—, pero por la rama de infraestructura: ahí la validación se adelantó, aquí haría falta
  encolar antes de confirmar, o marcar la evaluación como `error` cuando el encolado falla. No es de
  la Oleada C y no la afecta: solo se ve sin Redis.

## F. Seguridad / endurecimiento

**Fuera de alcance:** el prototipo corre solo en local y no se despliega. `SEC-01`…`SEC-06` se
registran como trabajo futuro en **docs/12 §4**, no como pendientes del prototipo.

## G. Ampliaciones (docs/07)

- [x] AMP-02 · **Exportación PDF del informe ejecutivo** y de la comparación (UI-07). Hecho (docs/09 §44):
  `GET /assessments/{id}/report.pdf` y `GET /assessments/{id}/compare/{other_id}/report.pdf`, con botón
  en la UI. Separa el acceso a la herramienta del acceso a los resultados.
- [x] AMP-05 · **Puntaje "provisional" con cobertura baja**. Hecho (docs/09 §36): `Aggregate.provisional`
  cuando la cobertura < `cobertura.umbral_provisional` (0.5, `settings.yml`); la UI lo marca en el
  score global y por función.
- [x] AMP-03 · Último criterio no-MVP: `DE-03` (información de eventos a personal/herramientas).
  Hecho (docs/09 §33): catálogo completo 23/23.

> AMP-01 (embeddings): descartado para el prototipo, ver **docs/12 §5**.

## H. Testing / validación (docs/07 §3)

- [x] TS-01 · **Golden files** de Terraform/Ansible y del pipeline. Hecho (docs/09 §39,
  `tests/test_golden.py`, `tests/golden/`).
- [x] TS-02 · **Golden set de IA**. Hecho (docs/09 §43, `tests/golden_ai/`, `app/ai/golden_eval.py`,
  `python -m app.main eval-ai`). Corrida real: **aprobada** (recall 100 %, citas 100 %, 0 instrucciones obedecidas); ver docs/09 §43.
- [x] TS-03 · **Test de contradicción** técnico-vs-documental. Hecho (docs/09 §38,
  `test_contradictions.py`, incluye un E2E con Terraform real).

## Priorización sugerida

Criterio: primero lo que hace el motor más honesto y reproducible, luego la capa de IA, luego lo
demostrable.

1. ~~**CR-06** y **AMP-05**~~ (hechos, docs/09 §36).
2. ~~**OP-12** y **OP-14**~~ (hechos, docs/09 §37).
3. ~~**OP-04 (contradicciones) + TS-03**~~ (hechos, docs/09 §38); ~~**TS-01**~~ (hecho, docs/09 §39), ~~**TS-02**~~ (hecho, docs/09 §43) y **AMP-02**:
   lo más demostrable y lo que respalda las afirmaciones del diseño.
4. Pulido barato: ~~FN-03~~ (hecho, docs/09 §51), ~~FN-07~~ (hecho, docs/09 §50), ~~FN-01 + API-03~~ (hechos, docs/09 §45), ~~FN-09~~ (hecho, docs/09 §46), ~~OP-05 + FN-08~~ (hechos, docs/09 §53), ~~OP-11~~ (hecho, docs/09 §52), ~~OP-15~~ (hecho, docs/09 §54), ~~OP-13~~ (hecho, docs/09 §49), ~~API-04~~ (hecho, docs/09 §55) y
   ~~la decisión de CR-07~~ (hecha, docs/09 §57).

> **Estado:** de las secciones A–H no queda nada pendiente; lo señalado en la revisión del 2026-10-04 está en §I. Solo FN-04 sigue marcado `[~]` y está obsoleto (el botón
> "Reevaluar" se eliminó, UI-10). Lo hecho está en docs/09 §23–§107; el trabajo que se decidió dejar fuera, en docs/12.
> **Fuera de alcance del prototipo:** ver **docs/12** (no es deuda).

## I. Revisión de bugs y lógica (2026-10-04)

Hecha fuera del backlog, tras una auditoría del código (docs/09 §62–§67): 4 correcciones iniciales, 3 de lógica
de negocio, una segunda pasada de reglas que no tenían sentido, 10 bugs más con los pisos de severidad, los tres
paquetes de ejemplo y la vista y el PDF de Comparar.

Quedó señalado y **sin hacer**:

- [ ] La UI y el informe ejecutivo muestran solo el **número** de evidencias de un criterio; el archivo, las
  líneas y la cita verificada se guardan pero no se ven (`getEvidence` no se usa en el frontend).
  **La UI ya lo muestra** (docs/09 §118, «Ver evidencia» por criterio); el informe PDF sigue sin hacerlo.
- [ ] Un incidente no reacciona a hechos posteriores (ver docs/08 §4): las transiciones son manuales.
- [ ] `valor_schema`, `modalidad_permitida` y `requiere_locator` de `evidence_types.yml` no se validan.
- [ ] El scope no se puede elegir en la UI (fijo en `entorno:produccion`).
- [ ] Sin tests de frontend ni CI.
- [x] `pollJob` agotaba a los 180 s y culpaba a los workers aunque el job siguiera corriendo (corridas con
  IA) — ahora espera hasta 15 min y remite a la pestaña Actividad; el sondeo de la evaluación activa
  corta a los 20 min.
- [ ] Los puntajes documentales de los tres paquetes de ejemplo no se han confirmado con una corrida real con IA.

Decidido y **dejado como está**: `GV-01` elige la afirmación por confianza (conservador); el Tier usa el puntaje
final con ajuste de IA (docs/01 §8.3 T6); validar la extracción afirmación por afirmación (sin casos reales).

## J. Revisión de la evidencia por criterio y del silencio documental (2026-11-26)

Revisión de código de docs/09 §118–§119 antes del push. Sin bloqueantes; quedó **sin hacer**:

- [ ] **Alias de evidencia atados a una función privada.** `load_criterion_evidence`
  (`app/core/assessment_service.py`) recalcula `e1`, `e2`... en cada lectura con
  `app.ai.adjustment._canonical_evidence`, que no está versionada. Si cambia su orden (tipo + hash de
  valor y limitaciones) o `sha256_json`, las explicaciones guardadas apuntan a otra evidencia sin
  aviso, y el test actual no lo detecta porque calcula lo esperado con la misma función. Hacerla
  pública (p. ej. `app/ai/canonical.py`), anotar que no se cambia sin migrar explicaciones y añadir
  un test con alias → tipo/archivo fijos sobre un fixture. Es la de más valor.
- [ ] **Una fila de evidencia que falte desplaza los alias.** `_canonical_evidence` descarta ids ausentes
  y renumera desde 1, y la UI muestra el conteo de `evidence_ids`. Hoy no pasa (las filas no se
  borran); numerar por posición en `evidence_ids` o devolver 409.
- [ ] **Consulta del endpoint.** Cada despliegue carga todos los criterios y toda la evidencia de la
  evaluación; filtrar el `CriterionResultRow` y la evidencia por `id.in_(...)`. Irrelevante con 31
  criterios.
- [ ] **Registro de la acción de §119.** «aporta… vuelve a evaluar» y luego la recomendación en
  infinitivo («si no existe, clasificar…»); valorar «si no existe: <recomendacion>». Renombrar
  `que_hacer_si_calla` con `_` como el resto de helpers de `limitations.py`.
- [ ] **`EvidenceList`.** Sin «Reintentar» tras un error de carga (hay que cerrar y abrir); el valor
  completo solo está en un `title` (no accesible por teclado), falta `aria-controls`; el fallback de
  `MODALITY_META` es código muerto; solo se recorta la ruta `/uploads/<id>/`, cualquier otra ruta
  absoluta en `locator.file` se mostraría tal cual.
- [ ] Test de 404 entre organizaciones para la ruta nueva (el helper común ya está cubierto en otros
  tests).
