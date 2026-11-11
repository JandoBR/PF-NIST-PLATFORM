# 08 — Motor Operativo (Eventos en Vivo)

El motor operativo es el consumidor continuo del stream de eventos. Genera **asesoría en vivo**
(diagnóstico + plan de respuesta/recovery) ante incidentes, y produce hechos que la evaluación de
madurez consume como evidencia. **No es un SIEM y nunca ejecuta acciones.**

## 1. Dos Flujos sobre un Mismo Stream

```text
eventos crudos
   └─► pipeline de logs (ingesta → normalización → filtro/dedup)
         ├─► [A] Ventanas → log.pattern → evidence → criterios → madurez
         └─► [B] Disparadores determinísticos → incidente operativo
                   ├─ dedup/correlación (un plan por incidente, no por evento)
                   ├─ plan de respuesta/recovery (IA, solo asesoría)
                   └─ emite hechos operativos (declarado, escalado, verificado)
                              └──────────► vuelven a [A] como evidencia
```

| Flujo | Pregunta | Ritmo | Salida | Alcance |
|---|---|---|---|---|
| **A. Madurez** | ¿La organización sabe detectar/responder/recuperar? | Periódico (snapshot) | Evidencia → criterios → score/Tier | Evaluación |
| **B. Operativo** | ¿Qué hacemos ahora ante esto? | Continuo | Incidente → plan | Organización/entorno |

La relación es de retroalimentación: el flujo operativo **produce los hechos que la madurez evalúa**.
“¿Se declaró el incidente? ¿Se escaló a tiempo? ¿Se verificó la restauración?” son a la vez guía
operativa (B) y evidencia de capacidad (A).

## 2. Alcance en el Prototipo (mínimo)

- Entidad `incident` con ciclo de vida y timeline.
- Disparadores **determinísticos** sobre los escenarios E1–E3 del doc 06.
- Un plan por incidente, con esquema fijo y condición de cierre.
- Retroalimentación: los hechos operativos de los escenarios alimentan criterios de DE/RS/RC.
- Sin streaming real ni correlación avanzada (el motor ya opera por organización + scope).

Fuera de alcance: motor de reglas configurable por el usuario, ML de detección, integración con SIEM,
notificaciones reales, ejecución de acciones.

## 3. Modelo Operativo

El alcance de los datos es la **organización/entorno**, no la evaluación.

```text
org / entorno
  ├─ events        (continuo, append-only; cada uno con su `source_id`)
  ├─ log_patterns  (ventanas derivadas)
  ├─ incidents     (incidentes operativos)
  └─ plans         (origen = incidente)
assessments consumen los eventos de los orígenes que se eligen al crearlas y derivan su propia
evidencia log.window/log.pattern de esos eventos (docs/09 §98).
```

Esquema completo de `events`, `log_patterns`, `incidents` y `plans` en `04-arquitectura-backend.md §4`
(fuente canónica).

**Selección de orígenes.** El evento identifica su origen en `source_id` (`fuente` declarada o el
archivo del que vino, docs/06 §2). `GET /orgs/{org_id}/event-sources` lista los orígenes disponibles
con su cantidad de eventos, rango y última ingesta. Al crear una evaluación se puede pasar
`event_source_ids` (array JSON): omitirlo significa **todos** los orígenes del `org`+`scope` (lo que
sigue haciendo el refresco automático), y `[]` significa **ninguno**. La evaluación recalcula los
patrones **en memoria** sobre los eventos seleccionados con el mismo código determinista de la
ingesta, en vez de leer `log_patterns`: así un log de otro escenario no se filtra en el cálculo, la
correlación entre fuentes seleccionadas sigue siendo correcta y una fila duplicada o vieja no decide
un criterio. La selección, el conteo, el rango y un `sha256` de los eventos canónicos quedan en
`reproducibility.eventos` de la evaluación.

## 4. Entidad `incident`

Estados:

```text
open ──► triaged ──► contained ──► recovering ──► closed
  └──────────────► closed (falso positivo)
```

| Campo | Descripción |
|---|---|
| `correlation_key` | Clave estable para agrupar eventos del mismo incidente (ej. `auth-burst:srv-app-01:2026-09-20T03:10`). |
| `severidad` | `baja` \| `media` \| `alta` \| `critica`. |
| `timeline` | Lista ordenada de hechos observados (evento, tiempo, transición). |
| `criterios` | Criterios de la matriz relacionados (para el plan y la evidencia futura). |
| `estado` | Estado del ciclo de vida. |

Reglas:

- Un `incident` se **crea** por un disparador y se **actualiza** por hechos posteriores. En el prototipo eso
  significa: los disparadores se evalúan sobre todos los eventos del org+scope, y una ingesta solo toca un
  incidente si aporta alguno de los eventos de su disparador (docs/09 §65). Un hecho posterior que resuelve la
  condición (p. ej. un `escalation_done` tardío) no avanza ni cierra el incidente: las transiciones son manuales.
- El motor **observa** hechos operativos; **no los fabrica** (no inventa un escalamiento porque exista un plan).
- Cerrar un incidente es una decisión basada en criterios; nunca automática por ausencia de eventos.
- Las transiciones se validan (docs/09 §52): se avanza un paso por vez y no se retrocede; `closed` es terminal y
  se alcanza desde cualquier estado abierto (falso positivo o resuelto), **siempre con un motivo** que queda en
  `motivo_cierre` y en la línea de tiempo.

## 5. Disparadores Determinísticos

La detección es por reglas; la IA solo sintetiza el plan. Sin disparador, el evento **solo** alimenta
la madurez.

| Disparador | Condición | Severidad | Acción | Criterios |
|---|---|---|---|---|
| D1 | `auth_failures_burst` ≥ N en ventana W y **sin** `alert_raised` posterior al inicio de la ráfaga | media | Crear incidente + plan de detección | CRI-DE-02, CRI-DE-03 |
| D2 | `alert_raised` sin `incident_triaged` posterior dentro de `plazo_triaje_minutos` (30) | media | Crear incidente + plan de triaje | CRI-RS-01 |
| D3 | `incident_declared` sin `escalation_done` posterior dentro del plazo documentado | alta | Crear/actualizar incidente + plan de escalamiento | CRI-RS-01 |
| D4 | `restore_exercise_run` con resultado `fail` | alta | Crear incidente + plan de recovery | CRI-RC-02, CRI-RC-03 |
| D5 | `restore_verified` sin `recovery_communicated` posterior | baja | Crear/actualizar incidente + plan de comunicación | CRI-RC-03 |

Los umbrales `N`, `W` y plazos provienen de la metodología versionada (`settings.yml`), no del modelo.

## 6. Anti-Ruido y Costo

| # | Regla |
|---|---|
| O1 | **Detección determinística primero**; la IA solo sintetiza el plan. |
| O2 | **Un plan por incidente** (clave de correlación), con actualizaciones; nunca un plan por evento. |
| O3 | **Disparadores explícitos**; sin disparador, solo evidencia para madurez. |
| O4 | **Cooldown** por `correlation_key` y **rate limit** por organización/criterio. |
| O5 | B **nunca** altera scores directamente; solo hechos que A convierte en evidencia de ventana. |
| O6 | Sigue sin ejecutar acciones: diagnóstico, pasos y condición de cierre, para un humano. |

## 7. Generación de Planes

Contrato de salida (esquema de plan de recovery, docs/05 §4.3):

```json
{
  "titulo": "Restablecer detección ante fuerza bruta SSH",
  "objetivo": "Asegurar que el patrón de accesos fallidos genere alerta.",
  "brecha_ref": "D1",
  "prioridad": "media",
  "diagnostico_observable": "auth_failures_burst en srv-app-01 sin alert_raised.",
  "hipotesis": ["Regla de detección ausente o umbral mal configurado."],
  "comprobaciones_seguras": ["Revisar reglas y umbrales sin modificar producción."],
  "pasos": ["Revisar la regla de detección", "Definir/probar umbral", "Registrar la prueba"],
  "verificacion": "Ejecutar un escenario con el mismo patrón y confirmar alert_raised.",
  "dependencias": [],
  "advertencia": "Asesoría. No se ejecuta ninguna acción automáticamente."
}
```

> En un plan de incidente, `brecha_ref` referencia el **disparador** (`D1`…); `prioridad` la fija el
> código (severidad del disparador), no la IA.

- El plan se **actualiza** si el incidente recibe nuevos hechos; al regenerarse conserva su estado de seguimiento.
- Al cerrar el incidente se registra cómo se verificó; el plan conserva su estado de seguimiento
  (`pendiente`/`en_progreso`/`hecho`, docs/05 §4.4).
- La IA **solo redacta** (diagnóstico, hipótesis, pasos, verificación) citando evidencia; la
  prioridad la fija el código (severidad del disparador).

## 8. Retroalimentación hacia Madurez

```text
Hechos operativos (incident_declared, escalation_done, containment_done,
                   restore_verified, recovery_communicated)
   → eventos del stream
   → patrones por ventana (flujo A)
   → evidencia log.pattern
   → criterios CRI-DE-02/03, CRI-RS-01, CRI-RC-02/03
```

- El motor operativo no puntúa: **emite y observa hechos**.
- La evaluación consulta la ventana y aplica los criterios de la matriz.
- Un incidente abierto sin hechos de respuesta genera `evidencia_insuficiente` o falla según la regla
  de justicia (doc 06 §5), nunca un valor inventado.

**Refresco automático.** Como el motor no puntúa, la madurez solo cambia cuando se corre una
evaluación nueva. Para no exigirle al usuario ese paso, `worker-logs`, al terminar una ingesta,
dispara una reevaluación de la última evaluación completada del `org`+`scope` cuando la ingesta
sumó al menos `vigilancia.refresco_min_patrones_nuevos` patrones nuevos (default 3). No dispara si:
no hay evaluación previa, ya hay una evaluación en vuelo para ese `org`+`scope` (anti-apilamiento),
o el ingreso no alcanzó el umbral. La reevaluación corre sin IA (determinista) y hereda el
seguimiento de planes.

**Eventos e incidentes son independientes de la evaluación.** Pertenecen a la organización+scope, no
a una evaluación: se ingieren y se ven aunque no se haya evaluado nunca. El refresco es una
consecuencia *opcional* (solo si hay evaluación previa), no un requisito para operar el flujo
operativo.

**La reevaluación automática corre sin IA a propósito:** (1) el puntaje base es determinista y no la
necesita — la IA es aumento opcional (U1/U2), no requisito; y (2) no debe gastar créditos sin que el
usuario lo pida. La IA, cuando se usa, solo ve datos estructurados del criterio/disparador (nunca las
líneas de log) y solo para redactar el plan (docs/05 §4).

**La reevaluación automática hereda los orígenes de eventos de la evaluación anterior** (docs/09 §98).
Si esa evaluación usó una lista explícita, el refresco usa la misma lista: un log excluido no entra por
la puerta de atrás. Si usó todos (`todas: true` en `reproducibility.eventos`), sigue usando todos y una
ingesta de un origen nuevo cuenta. Una evaluación anterior a esta función no tiene la marca y también
usa todos.

**El refresco es selectivo (docs/06 §6, FN-06):** reusa evidencia, resultados y planes de los
criterios **no operativos** (incluido lo que produjo la IA) y **solo recalcula los criterios de
vigilancia** con los patrones nuevos. Por eso una evaluación previa con IA **no se degrada** al
refrescarse por eventos.

## 9. Escenarios Esperados

| Escenario | Disparador esperado | Incidente | Plan generado |
|---|---|---|---|
| E1 (con alerta y triaje) | ninguno (flujo correcto) | no se crea; solo evidencia positiva | ninguno |
| E1-b (fallos sin alerta) | D1 | `alta`/`media` | Plan de detección |
| E1-c (alerta sin triaje) | D2 | `media` | Plan de triaje |
| E2 (con escalamiento y contención) | ninguno | no se crea; evidencia positiva | ninguno |
| E2-b (declarado sin escalar) | D3 | `alta` | Plan de escalamiento |
| E3 (restauración ok y verificada) | ninguno; si falta comunicación, D5 | `baja` | Plan de comunicación |
| E3-b (restauración fallida) | D4 | `alta` | Plan de recovery |
| Respuesta parcial (log de ejemplo de la UI) | D3 (escalamiento a los 45 min) y D5 | `alta`, `baja` | Planes de escalamiento y de comunicación |

> Los escenarios con flujo correcto **no** deben crear incidentes: esto valida la regla anti-ruido.

## 10. Simulador y Determinismo

- Los escenarios viven en `tests/fixtures/scenarios/*.jsonl` con metadata de disparadores esperados.
- Replay respetando `event_time`; los cálculos usan tiempo de evento, no de reloj.
- Determinístico: sin aleatoriedad (o con semilla fija si se añade).
- El motor operativo se prueba con los mismos escenarios que alimentan la madurez.

## 11. Evolución Futura

- Cola/stream dedicado por organización y autoscaling por profundidad (doc 04 §3.1, P7).
- Correlación avanzada entre recursos y campañas.
- Umbrales y disparadores configurables por el usuario.
- Ventanas deslizantes e incidentes long-running con SLA observado.
- Integración con canales de notificación reales (solo aviso, nunca ejecución).
