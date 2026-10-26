# 06 — Pipeline de Eventos

El pipeline convierte actividad operativa simulada en **evidencia evaluable** (flujo A) y alimenta el
**motor operativo** de incidentes y planes en vivo (flujo B). El motor operativo se especifica en
`08-motor-operativo.md`. No es un SIEM.

La ingesta, la agregación y las colas se implementan sobre **listas de Redis** (`RPUSH`/`BLPOP`);
**Redis Streams** con consumer groups es el diseño objetivo a mayor escala (docs/04 §3.1, docs/12 §1).

## 1. Objetivo

| Sí | No |
|---|---|
| Demostrar el flujo evento → patrón → evidencia → criterio | Vigilar sistemas reales |
| Alimentar dos consumidores: madurez (A) y operativo (B, doc 08) | Generar alertas en producción |
| Evaluar ventanas y tiempos con reproducibilidad | Sustituir un SOC |
| Producir evidencia operativa (`log.*`) para los criterios | Ejecutar acciones |

Los escenarios están diseñados para **coincidir con los criterios** de la matriz y con los disparadores
del motor operativo; no son logs decorativos.

## 2. Esquema de Evento

Formato JSONL, un evento por línea:

```json
{
  "event_id": "evt-0001",
  "event_time": "2026-09-20T03:14:05Z",
  "tipo": "auth_failure",
  "recurso": "srv-app-01",
  "scope": "entorno:produccion",
  "actor": "203.0.113.10",
  "detalle": { "usuario": "admin", "servicio": "ssh", "intentos": 5 },
  "fuente": "log:sshd"
}
```

> `fuente` es el campo del contrato JSONL; al normalizar se persiste como `source_id` en `events`
> (docs/04 §4). Los demás campos se conservan.

Campos obligatorios: `event_id`, `event_time`, `tipo`, `recurso`, `scope`.
`event_time` es el **tiempo del evento**, no el de reproducción.
Los eventos pertenecen a una **organización** (`org_id`): se cargan vía `/orgs/{org_id}/events` y el
`scope` identifica el entorno dentro de ella. No pertenecen a una evaluación.

Tipos de evento iniciales:

| tipo | Descripción |
|---|---|
| `auth_failure` | Intento de autenticación fallido. |
| `auth_success` | Autenticación exitosa (contexto). |
| `alert_raised` | Alerta generada por una regla de detección. |
| `incident_declared` | Incidente declarado según criterios. |
| `incident_triaged` | Triaje/categorización/priorización. |
| `escalation_done` | Escalamiento a un nivel definido. |
| `containment_done` | Contención aplicada. |
| `restore_exercise_started` | Inicio de ejercicio de restauración. |
| `restore_exercise_run` | Restauración ejecutada (resultado ok/fail). |
| `restore_verified` | Verificación de integridad/operación posterior. |
| `recovery_communicated` | Comunicación de recuperación a stakeholders. |
| `config_changed` | Cambio de configuración sensible (contexto). |

## 3. Patrones Operativos

La capa de vigilancia agrega eventos en `log.pattern`:

| Patrón | Condición | Alimenta |
|---|---|---|
| `auth_failures_burst` | ≥ N fallos del mismo actor/recurso dentro de algún tramo de duración W (ventana deslizante: otros fallos del mismo actor fuera de ese tramo no la ocultan) | CRI-DE-02 (contexto) |
| `alert_raised` | Existe `alert_raised` que referencia un evento previo | CRI-DE-02, CRI-DE-03 |
| `incident_triaged` | Existe `incident_triaged` (triaje de una alerta) | Disparador D2 (docs/08 §5) |
| `containment_done` | Existe `containment_done` | Solo contexto: ningún criterio ni disparador lo usa todavía |
| `incident_declared` | Existe `incident_declared` con criterio documentado aplicable | CRI-DE-02, CRI-RS-01 |
| `escalation_done` | Existe `escalation_done` dentro del plazo declarado | CRI-RS-01 |
| `restore_exercise_run` | Ejercicio completo con resultado | CRI-RC-02 |
| `restore_verified` | Verificación posterior con confirmación | CRI-RC-02, CRI-RC-03 |
| `recovery_communicated` | Comunicación de recuperación a stakeholders | CRI-RC-03 |

Cada patrón guarda `desde`, `hasta`, `conteo`, `resultado` y `fuentes[]` (el origen de los eventos,
FN-07). La evidencia `log.pattern` se genera por evaluación con un id nuevo; el patrón no referencia
un `evidence_id` (docs/12 §2, OP-13).

Los patrones se detectan sobre **todos los eventos guardados** de la organización y el scope, no solo sobre
el archivo recién ingerido: describen la misma ventana que `log.window`. Hay una fila por patrón y por scope,
que se reemplaza en cada ingesta; entre dos eventos con la misma hora cuenta como último el que se ingirió
después (docs/09 §65).

Los patrones alimentan el flujo A (evidencia para criterios) y son la entrada de los **disparadores
determinísticos** del flujo B, que decide si se abre un incidente y se genera un plan (doc 08 §5).
Un patrón sin disparador aplicable solo alimenta madurez.

## 4. Escenarios Simulados

### E1 — Actividad sospechosa y detección

```text
03:10  auth_failure (admin, srv-app-01) × 12 en 2 min
03:12  alert_raised   (regla: fuerza bruta SSH, severidad media)
03:13  incident_triaged (categoría: intento de acceso, prioridad: media)
```

Evalúa: ¿hay detección?, ¿la alerta referencia el patrón correcto?, ¿el triaje ocurre?

Variante E1-b (caso negativo, dispara D1):

```text
03:10  auth_failure (admin, srv-app-01) × 12 en 2 min
sin alert_raised
```

→ hay actividad que debía alertar y no lo hizo: abre incidente (D1) y alimenta CRI-DE-02 con fallo de
detección.

### E2 — Incidente escalado y contenido

```text
03:14  incident_declared (criterio: accesos fallidos + éxito anómalo)
03:20  escalation_done (nivel: responsable de seguridad)
03:35  containment_done (bloqueo de IP, rotación de credenciales)
```

Evalúa: ¿se declara según criterios?, ¿se escala dentro de plazos?, ¿se contiene?

Variante E2-b (caso negativo, dispara D3):

```text
03:14  incident_declared
sin escalation_done dentro del plazo
```

→ declarado sin escalar: abre incidente (D3) y alimenta CRI-RS-01 con fallo de respuesta.

### E3 — Ejercicio de recuperación

```text
10:00  restore_exercise_started (BD principal, backup diario)
10:25  restore_exercise_run (ok, RTO observado 25 min)
10:40  restore_verified (integridad ok, servicio operativo)
10:45  recovery_communicated (stakeholders internos)
```

Evalúa: ¿se prueba la restauración?, ¿se verifica integridad?, ¿se comunica?

Variante E3-b (caso negativo):

```text
10:25  restore_exercise_run (fail, backup corrupto)
sin restore_verified
```

→ evidencia de fallo real; alimenta CRI-RC-02/03 con puntaje bajo y genera plan de recovery.

## 5. Regla de Justicia (no penalizar sin oportunidad)

> La ausencia de una alerta solo cuenta como falla si el escenario contiene un evento que **debía**
> activar una regla conocida y existe una `log.window` completa.

| Situación | Tratamiento |
|---|---|
| No hay ventana de observación | `evidencia_insuficiente`; no se penaliza. |
| Hay ventana completa y no hay alerta esperada | Falla de detección → puntaje bajo. |
| No hay regla conocida aplicable al evento | No se penaliza; se registra limitación. |
| Ventana parcial (datos faltantes declarados) | `evidencia_insuficiente` con motivo. |

## 6. Re-evaluación al Cargar Eventos

```text
Cargar eventos (event_time en orden)
  → construir/actualizar ventanas por scope
  → detectar patrones
  → generar evidencias log.pattern / log.window
  → recalcular SOLO los criterios que referencian esos tipos de evidencia
  → nueva instantánea de evaluación + comparación con la anterior
```

- Nunca se sobrescribe una evaluación previa: se crea la nueva y se muestra el diff.
- El recálculo solo toca criterios afectados; el resto conserva su puntaje y versión.
- El diff responde: “¿qué cambió y por qué?” (evidencia nueva, patrón detectado, estado).

**Automático (docs/08 §8).** La nueva evaluación **no la pide el usuario**: al procesar una ingesta,
si agregó suficientes `log.pattern` **nuevos** para su scope (umbral
`vigilancia.refresco_min_patrones_nuevos`, default 3), el worker de logs encola una reevaluación de
la última evaluación completada del `org`+`scope`. Un patrón cuenta como nuevo si cambia su resultado, su
intervalo o su conteo; reingerir el mismo archivo agrega 0 patrones y no dispara. La evaluación hereda el estado de seguimiento (docs/05 §4.4).

**Independencia de la evaluación.** Los eventos y los incidentes son **organización+scope**, no
pertenecen a una evaluación: se ingieren y consultan aunque nunca se haya evaluado. Si no hay una
evaluación completada previa, simplemente no hay nada que refrescar.

**Refresco selectivo (implementado, FN-06).** El refresco **no** re-corre todo: reusa de la
evaluación anterior las fuentes, la evidencia **no operativa** (Terraform/Ansible/`doc.claim`), los
resultados y los planes de los criterios que **no** consumen vigilancia, y **recalcula solo los
criterios afectados** (`log.pattern`/`log.window`) con los patrones frescos — exactamente el
diagrama de arriba. Así se preserva lo derivado de IA (claims U1, ajuste U2, texto de planes) en los
criterios no afectados, sin gastar IA ni degradar el resto. El **estado de seguimiento** de los
planes afectados se conserva por `criterion_id` (docs/05 §4.4). Implementado en
`svc.run_surveillance_refresh`; el worker lo dispara con `selective_refresh=True`.

## 7. Recomendaciones Generadas por Eventos

El motor operativo (doc 08) convierte patrones anómalos o fallos en un **plan de asesoría por
incidente** (nunca ejecución). La tabla de disparadores (D1–D5), el esquema del plan, la entidad
`incident` y las reglas anti-ruido están en `08-motor-operativo.md §5–§7`; no se repiten aquí.

## 8. Simulador y Fixtures

- Los escenarios viven en `tests/fixtures/scenarios/*.jsonl` con su metadata (ventana esperada,
  resultado esperado y **disparadores esperados**).
- El simulador hace replay respetando `event_time`; publica en la cola de Redis y los consumidores
  (madurez y operativo) procesan los eventos.
- Cada ejecución de un escenario es determinística (sin aleatoriedad en el prototipo; si se agrega,
  con semilla fija).
- Los escenarios E1–E3 se usan tanto para la demo como para los tests golden del pipeline y del
  motor operativo (doc 08 §9: escenarios de flujo correcto no deben crear incidentes).
