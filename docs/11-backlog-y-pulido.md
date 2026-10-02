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

### [x] UI-03 · Toggles de IA momentáneos (P1)
Los checkboxes de IA (U1/U2) son **por corrida**: existen para no gastar tokens, no son una
preferencia persistente. Hoy su estado sobrevive al cerrar/abrir el modal, lo que da a entender lo
contrario.
- Volver a `false` al cerrar/enviar el modal (o al completarse la corrida).
- Texto explícito: "solo aplica a esta evaluación; se resetea".
- (Opcional) tooltip con el costo estimado / que sin `DEEPSEEK_API_KEY` no tiene efecto.

### [x] UI-04 · Hallazgo → plan inline (P1)
En Recomendaciones, tocar un hallazgo debería **desplegar su plan de acción** en el lugar (como hace
Simulación de Amenazas con sus incidentes), en vez de tener un botón que salta a otra sección.
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

- [ ] FN-01 · **Historial de jobs** (P1): no hay `GET /jobs` (listado) ni UI; hoy solo `GET /jobs/{id}`.
  Sin esto no se puede ver qué corrió ni reintentar un job fallido sin reenviar todo.
- [ ] FN-03 · **Ingesta "nuevos vs actualizados"** (P2): la conversión a async perdió ese detalle
  (la API devuelve solo `job_id`); recuperarlo en la respuesta o en el resultado del job.
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

> `FN-02` (progreso real del job) **descartado** para el prototipo: ver docs/12 §1.

## C. Cobertura de criterios y Tier (P0)

El catálogo implementa **23 de 23** criterios de docs/03 (`criteria.yml` v4). Cobertura por función:
GV 4/4 · ID 4/4 · PR 6/6 · DE 3/3 · RS 3/3 · RC 3/3.
- **UI (hecho):** la matriz muestra siempre las **6 funciones**; una sin criterios aparece como
  "Sin criterios" (borde punteado) en vez de desaparecer (docs/09 §30).

- [x] CR-01 · Implementar los **7 MVP faltantes** (P0): `GV-02`, `ID-03` (desbloquean Tier 2),
  `RC-01`, `DE-01`, `GV-03`, `ID-01`, `ID-02`. Hecho (docs/09 §31). `criteria.yml` v2.
- [x] CR-02 · Completar Tier 3/4: `GV-04`, `RS-02`. Hecho (docs/09 §32). `criteria.yml` v3.
- [x] CR-03 · `RS-03` (notificación) e `ID-04` (inventario de datos) para la privacidad (ver UI-01).
  Hecho (docs/09 §32); la vista de privacidad ya los muestra.
- [x] CR-04 · `DE-02` incorpora `doc.claim(process_defined)` y llega a 100 cuando hay criterios de
  declaración + evidencia operativa. Hecho (docs/09 §33).

> Nota transversal: los criterios con componente **documental** (`GV-02/03/04`, `ID-02/03/04`,
> `RC-01`, `RS-02/03`) dependen de `doc.claim` extraído por U1; sin IA quedan
> `evidencia_insuficiente` (igual que `GV-01`). Los **mixtos** (`ID-01`, `DE-01`, `DE-02`, `DE-03`)
> tienen además una parte determinística (Terraform/Ansible/logs) que puntúa sin IA, aunque su tope
> alto suele exigir el `doc.claim`.

## D. Simplificaciones activas (docs/09 §11) — pendientes del prototipo

- [ ] OP-01 · **Prioridad de planes por criticidad de activo** (versión fina, un campo): hoy
  `prioridad = finding.severidad` (`recommendations/plans.py`); la fórmula completa de docs/05 §4.2
  depende del pipeline `ctx.*` (OP-09, fuera de alcance, docs/12 §3).
- [~] OP-04 · **Transiciones de estado de incidente: hecho** (`PATCH /incidents/{id}`, ver docs/09
  §24; habilita UI-06). Siguen pendientes los hallazgos `contradiccion` (docs/02 §5) y `limitacion`
  además de `brecha`.
- [ ] OP-05 · Trigger D2 (`alert_raised` sin `incident_triaged`).

> Descartados para el prototipo (OP-02, OP-03, OP-06…OP-10): ver **docs/12**.

## E. API / contratos faltantes (docs/04 §6)

- [ ] API-03 · `GET /jobs` (listado, filtrable por estado/org) — habilita FN-01.

> Descartados para el prototipo (API-01 `sources`+`run` separados, API-02 `GET /scores`): ver **docs/12 §1**.

## F. Seguridad / endurecimiento

**Fuera de alcance:** el prototipo corre solo en local y no se despliega. `SEC-01`…`SEC-06` se
registran como trabajo futuro en **docs/12 §4**, no como pendientes del prototipo.

## G. Ampliaciones (docs/07)

- [ ] AMP-02 · **Exportación PDF del informe ejecutivo** (y de la comparación, UI-07). Se promueve al
  prototipo: da oficialidad al informe y **separa el acceso a la herramienta del acceso a los
  resultados** (común en entornos corporativos).
- [x] AMP-03 · Último criterio no-MVP: `DE-03` (información de eventos a personal/herramientas).
  Hecho (docs/09 §33): catálogo completo 23/23.

> AMP-01 (embeddings): descartado para el prototipo, ver **docs/12 §5**.

## Priorización sugerida

1. **FN-03 + OP-05** (baratos y con valor real): detalle de la ingesta y disparador D2.
2. **FN-01 + API-03** (`GET /jobs`): ver qué corrió y reintentar; hoy solo hay `GET /jobs/{id}`.
3. **OP-04** (hallazgos `contradiccion`/`limitacion`) y **AMP-02** (PDF), según tiempo.
4. **OP-01** (prioridad por criticidad, versión fina).

> **Hecho:** catálogo completo (CR-01…CR-04), UI-01…UI-10, FN-05, FN-06 y la parte de estado de
> incidente de OP-04. Ver docs/09 §23–§33.
> **Fuera de alcance del prototipo:** ver **docs/12** (no es deuda).
