# 09 — Registro de Implementación

Bitácora técnica del código en `backend/`: qué se construyó, en qué orden, y qué decisiones o
simplificaciones se tomaron respecto a la especificación (docs 00–08). Los docs 00–08 son el
diseño; este documento es "qué existe realmente y por qué se ve así". Se actualiza a medida que
avanza la implementación — no es un changelog de commits, es una referencia para retomar el
trabajo sin releer todo el historial de git.

## 0. Cómo leer esto

Cada corte ("slice") es verticalmente completo: adaptador(es) + motor + (cuando aplica) IA +
persistencia + CLI + tests, no una capa horizontal a medio terminar. El orden se eligió para
tener algo demostrable lo antes posible y para que cada corte se apoye en el anterior sin
retrabajo. El plan completo y su razonamiento está en el historial de la conversación; aquí solo
quedan las decisiones que importan para seguir construyendo.

## 1. Estado actual (resumen)

| Corte | Qué hace | Estado |
|---|---|---|
| Entorno | `flake.nix` (Nix dev shell), `uv` (deps), `ruff` (lint) | Hecho |
| Núcleo determinista | Metodología YAML, contrato de evidencia, adaptador Terraform, motor de evaluación, agregación, Tier | Hecho |
| Documentos + IA (U1) | Chunking, cliente DeepSeek/Fake/Null, extracción con cita obligatoria, CRI-GV-01 | Hecho |
| Control de costo de IA | Cache en disco por hash de prompt, tope de chunks/documento, guard de arranque | Hecho |
| Persistencia | SQLAlchemy + Alembic + SQLite por defecto, `run`/`reevaluate`/`compare` | Hecho |
| Adaptador Ansible | Parser YAML, CRI-PR-04, CRI-PR-06 ahora Mixto de verdad | Hecho |
| Ajuste de IA (U2) | Fórmula B/A/D/α → S acotada, con todas las reglas J1–J7/R3–R6 | Hecho |
| Planes (U3) | Hallazgos → planes priorizados, alcance simplificado (sin criticidad de activo) | Hecho |
| Motor operativo (docs 06/08) | Eventos → patrones (flujo A) + disparadores → incidentes → planes (flujo B) | Hecho |
| Pruebas | 183 tests (`pytest`) + `ruff` limpio; E2E de documentos, guarda de migraciones, API | Hecho |
| API REST (doc 04 §6) | FastAPI sobre el mismo `assessment_service`; crear+subir+ejecutar fusionados (sin cola) | Hecho |
| Docker/Redis (doc 04 §11) | `docker compose up`: Postgres + Redis + migrate + api reales; sin `worker-core`/`worker-logs` todavía | Hecho |

Comando de referencia para ver todo esto funcionando:

```bash
cd backend
uv run python -m app.main run --terraform tests/fixtures/terraform/gaps --org "Empresa Demo"
uv run python -m app.main list
uv run python -m app.main plans <assessment_id>
uv run python -m app.main reevaluate <assessment_id>   # tras corregir el fixture
uv run python -m app.main compare <id_antes> <id_despues>
uv run python -m app.main events "Empresa Demo" tests/fixtures/scenarios/e1b_fallos_sin_alerta.jsonl
uv run python -m app.main incidents "Empresa Demo" --plans

# API HTTP (en otra terminal):
uv run uvicorn app.api.app:app --reload
curl -X POST http://127.0.0.1:8000/assessments \
  -F "org_name=Empresa Demo" -F "terraform_files=@tests/fixtures/terraform/gaps/main.tf"

# Todo el stack con Docker (Postgres + Redis reales, sin instalar nada localmente):
docker compose -f deploy/docker-compose.yml up
```

## 2. Entorno y estructura

- `flake.nix` en la raíz: `nix develop` da `python312`, `uv`, `ruff`, `docker-compose`. Se pidió
  explícitamente por ser NixOS — los binarios de PyPI (ruff, etc.) no corren ahí sin esto.
- `backend/` es un proyecto `uv` independiente (`pyproject.toml`, `uv.lock`, `.venv/`), con la
  estructura de carpetas de `04-arquitectura-backend.md §7` (no todas las carpetas existen aún —
  solo las que ya tienen código).
- `ruff` configurado (`E, F, I, UP, B`, line-length 100), `alembic/versions/` excluido del lint
  (código autogenerado).

## 3. Núcleo determinista

**Qué se construyó:** `app/schemas/evidence.py` (contrato `EvidenceInstance`, doc 01 §2.2),
`app/methodology/` (loader + validación Pydantic de `criteria.yml`/`evidence_types.yml`/
`settings.yml`, falla rápido si la metodología es inconsistente), `app/adapters/terraform/`
(parser HCL vía `python-hcl2`), `app/evaluation/` (un módulo de regla por criterio, motor que
despacha por id, agregación jerárquica con las reglas A1–A6, estimación de Tier con T1–T5).

**Decisiones:**

- `python-hcl2` necesita `SerializationOptions(strip_string_quotes=True)` explícito — sin eso,
  las claves y strings quedan con comillas literales incluidas (parece un cambio de
  comportamiento entre versiones de la librería).
- Las reglas de criterio están **hardcodeadas en Python**, no interpretadas desde el YAML
  (`regla:` en `criteria.yml` es metadata descriptiva, no un DSL ejecutable). Coherente con D5
  ("los criterios son fijos"): agregar un criterio implica agregar su módulo en
  `app/evaluation/rules/`, siempre juntos.
- Atributo ausente en Terraform → `unknown`, nunca se asume el default del proveedor (docs 02
  §4), incluso cuando ese default es público y conocido (ej. `storage_encrypted` de RDS es
  `false` por defecto, pero se reporta `unknown`, no `disabled`).
- `score_aggregates` y `tier_estimates` (tablas en doc 04 §4) **no se persisten**: se recalculan
  en cada lectura desde `criterion_results`, que es barato y evita mantenerlos sincronizados.
  Esta misma lógica de "no persistir lo que es barato recalcular" se repite más adelante con
  `findings`.
- Catálogo inicial: 5 criterios Terraform-only (`CRI-PR-01/02/03/05/06`). Tier queda
  "no estimable" hasta que existan criterios GV/ID (ninguno de los indicadores de Tier 2 existía
  todavía en este punto).

## 4. Documentos + extracción con IA (U1)

**Qué se construyó:** `app/adapters/documents/` (chunking por encabezado Markdown / por página
PDF), `app/ai/client.py` (`AIClient` protocolo; `DeepSeekClient` real vía SDK `openai`;
`FakeAIClient` para tests, indexado por palabra clave en el prompt; `NullAIClient` cuando no hay
API key), `app/ai/extraction.py` (U1 con las reglas E1–E7 de doc 05 §2.3), `CRI-GV-01` (primer
criterio puramente documental).

**Decisiones:**

- **`FakeAIClient` nunca pretende ser un extractor real** — es un doble de prueba determinista.
  La primera vez que el pipeline tocó la API real de DeepSeek fue sin querer (ver §5): quedó
  como la única prueba real end-to-end hasta que se agregó el guard explícito.
- `doc.claim` con `encontrado: false` no exige cita (no hay nada que citar); `encontrado: true`
  sin `cita.fragmento` se descarta (E2).
- Confianza baja (`< umbral_confianza_documental`) no descarta la evidencia: la conserva con
  `limitations` poblado, y los criterios la tratan como no usable para puntuar (E3). Decisión de
  diseño: "guardar con limitación" en vez de "descartar" preserva trazabilidad.
- `CRI-GV-01` resuelve la vigencia de la revisión con un mapeo simple de frecuencia → días
  (`anual: 366`, etc.) y comparación de fechas. No hay modelado de calendarios reales (meses de
  28–31 días); es una aproximación aceptada para el alcance actual.

## 5. Incidente real: llamada a la API sin querer, y controles de costo

Durante una verificación manual, un comando que debía ejercitar el modo degradado (sin IA) en
realidad tenía una `DEEPSEEK_API_KEY` real ya cargada en `backend/.env` (puesta ahí por el
usuario en un turno anterior) y disparó **3 llamadas reales y pagadas** a DeepSeek. El costo fue
mínimo (prompts pequeños contra un fixture de 3 líneas), pero expuso dos huecos:

1. No había caché: la misma llamada se repetiría en cada corrida de prueba.
2. No había ninguna verificación antes de llamar a la API real: `unset` en el shell no alcanza
   si `backend/.env` ya tiene la key.

**Lo que se construyó en respuesta** (pedido explícito del usuario: *"minimiza el uso en
tests, un dólar máximo al inicio"*):

- `app/ai/cache.py`: `CachingAIClient` envuelve cualquier cliente real, cachea en disco por
  `sha256(system_prompt + user_prompt)`. Un resultado `None` (degradado) **nunca se cachea** —
  si se agrega una key más tarde, no debe quedar pegado repitiendo el resultado vacío de cuando
  no había IA.
- `DEFAULT_MAX_CHUNKS_PER_DOCUMENT = 20` en el adaptador de documentos (doc 05 §7 ya lo pedía,
  no estaba implementado).
- `check_live_ai_guard()` en `app/main.py`: bloqueo explícito con `SystemExit(1)` si hay una API
  key real configurada y no se pasó `--confirm-live-ai`. Se generalizó más adelante (§7) para
  cubrir también el ajuste de IA (U2), no solo la extracción documental — ambos llaman al mismo
  cliente, así que ambos deben pasar por el mismo guard.
- `backend/.env` (gitignored) + `python-dotenv`: `load_dotenv()` al arrancar `app.main`, para no
  depender de que la key esté exportada en el shell.

**Segundo incidente, mismo tema:** al probar el guard generalizado, un comando de limpieza
(`rm -f .env .data -r`) borró el `backend/.env` real del usuario *después* de sobreescribirlo con
un valor de prueba, sin leer su contenido antes. Se restauró textualmente desde un `cat` anterior
en la misma conversación. Lección operativa (no de código): **nunca sobreescribir/borrar un
archivo que no se creó en la sesión actual sin leerlo primero**, sin importar que parezca
desechable.

## 6. Persistencia: `run` / `reevaluate` / `compare`

**Qué se construyó:** `app/models/tables.py` (SQLAlchemy: `Organization`, `Assessment`,
`Source`, `EvidenceRow`, `CriterionResultRow`, y más adelante `PlanRow`), `app/core/db.py`
(SQLite por defecto en `backend/.data/`, `DATABASE_URL` apunta a Postgres cuando exista el stack
de Docker), Alembic real (`alembic/`, migraciones autogeneradas, `env.py` lee la URL desde
`app.core.db.get_database_url()`), `app/core/repository.py` (conversión Pydantic ↔ ORM),
`app/core/assessment_service.py` (`run_assessment`, `reevaluate`, `compare`).

**Decisiones:**

- **SQLite por defecto, no Postgres.** Mismo principio que todo lo anterior: no exigir Docker
  para ver el siguiente corte funcionando. `DATABASE_URL` cambia el motor sin tocar los modelos
  (tipos genéricos de SQLAlchemy, no `postgresql.JSONB` directo).
- `reevaluate` implementa "nueva evaluación heredando fuentes" (docs 01 §10) **re-leyendo las
  mismas rutas de archivo** registradas en `sources` de la evaluación anterior. Si el usuario
  corrigió ese archivo en disco, la correción se refleja automáticamente — no hay necesidad de
  un mecanismo de "diff de fuentes" más sofisticado todavía.
- `Source` es uno por adaptador invocado (con un hash sha256 de todos sus archivos), no uno por
  archivo individual como sugiere doc 04 §4. Simplificación: evita reimplementar el listado de
  archivos en la capa de persistencia cuando el adaptador ya lo hace (`TerraformAdapter.list_files`,
  etc., expuestos como `staticmethod` precisamente para esto).
- Probado end-to-end manualmente, no solo con tests: se corrió el fixture `gaps`, se corrigieron
  3 de 4 problemas a propósito dejando uno sin tocar, se reevaluó, y `compare` reportó exactamente
  esos 3 criterios cambiando y el cuarto (SSH/RDP abierto) sin cambios.

## 7. Adaptador Ansible, `CRI-PR-04`, `CRI-PR-06` como Mixto real

**Qué se construyó:** `app/adapters/ansible/` (YAML vía `PyYAML`, módulos soportados:
`lineinfile`, `copy`, `template`, `file`, `service`, `ufw`/`iptables`; cualquier otra cosa —
`command`, `shell`, módulos no reconocidos — produce `an.task.uninterpreted` con el motivo, nunca
se ejecuta nada), `CRI-PR-04` (endurecimiento SSH, puramente Ansible), reescritura de
`CRI-PR-06` para exigir Terraform **y** Ansible juntos en su rama de puntaje más alta.

**Decisiones:**

- `CRI-PR-06` originalmente daba 100 solo con CloudTrail multirregión (simplificación documentada
  porque no existía adaptador de Ansible). Al construirlo, se corrigió para que el 100 real
  exija `an.service.state` de un servicio de syslog corriendo (`rsyslog`/`journald`/`syslog-ng`)
  **además** de CloudTrail multirregión — así es como dice la regla en doc 03, no como se había
  simplificado antes. Es el primer criterio Mixto que de verdad fusiona evidencia de dos
  adaptadores distintos.
- Se eligió detectar "logs de sistema" vía el módulo `service` (¿está corriendo el servicio?) en
  vez de inspeccionar una tarea que edite `rsyslog.conf`, porque un servicio corriendo es una
  señal más directa y verificable que una tarea de configuración que podría no haberse aplicado.
- `CRI-PR-03` (exposición de puertos) **no** se extendió para usar evidencia de Ansible aunque la
  regla textual de doc 03 menciona "SSH con acceso restringido" — se decidió que eso ya está
  cubierto por el chequeo de security groups, y mezclar ahí la evidencia de endurecimiento de
  sshd (que es lo que mide `CRI-PR-04`) duplicaría responsabilidad entre dos criterios que la
  matriz separa a propósito (exposición de red vs. configuración del servidor).

## 8. Ajuste contextual de IA (U2)

**Qué se construyó:** `app/ai/adjustment.py` (`adjust()`: implementa la fórmula
`S = round(clamp((1-α)·B + α·clamp(A, B-D, B+D), 0, 100))` de doc 01 §5.1 exactamente),
`engine.apply_ai_adjustments()`, flag `--ai-adjust` en la CLI (independiente de `--documents`:
criterios como `CRI-PR-01/02` y `CRI-GV-01` son `ai_adjustable` y se pueden ajustar en una corrida
de solo Terraform).

**Decisiones:**

- `base_score` nunca se muta — el ajuste siempre produce un `CriterionResult` nuevo
  (`model_copy`), nunca modifica el original in-place.
- **Distinción importante:** un criterio no `ai_adjustable`, o en un estado que no admite ajuste
  (`evidencia_insuficiente`/`error`), simplemente **no se toca** — no se marca `degradado`. Solo
  se marca `degradado=True` cuando de verdad se intentó una llamada y esta falló, fue inválida, o
  citó evidencia inexistente (J4/J5/R5). Conflar "nunca se intentó" con "se intentó y falló"
  habría hecho que cada corrida sin IA pareciera estar fallando en seis criterios a la vez.
- `no_implementado` solo puede ajustarse hacia abajo, nunca hacia arriba (J2) — se fuerza
  recortando la propuesta de la IA a `base_score` antes de aplicar la fórmula, en vez de
  intentar parsear la justificación buscando una frase mágica.
- Un ajuste que no cambia el puntaje (`S == B`) **igual se registra** en `explanation` (J7: "el
  ajuste se guarda siempre, aun sin cambio neto"). No hay una tabla `ai_adjustments` separada
  todavía (ver §11) — el rastro de auditoría de este corte vive en el texto de `explanation`.
- El guard de costo (§5) se generalizó aquí: ahora cubre `--ai-adjust` sola, sin `--documents`,
  porque ambas rutas llaman al mismo cliente potencialmente real.

## 9. Generación de planes (U3), alcance simplificado

**Qué se construyó:** `app/recommendations/findings.py` (`derive_findings`: un hallazgo por
criterio puntuado por debajo de `planes.umbral_brecha`, severidad bandeada solo por score),
`app/ai/plan_generation.py` (`generate_plan_content`: nunca retorna `None`, degrada a la
plantilla `recomendacion` del criterio), `app/recommendations/plans.py` (une hallazgo + contenido
de IA, asigna prioridad), tabla `plans` + migración, `assessment_service.generate_plans()`
(idempotente: reemplaza en vez de duplicar), subcomando `plans` en la CLI.

**Decisión de alcance (pedida explícitamente):** la fórmula de prioridad de doc 05 §4.2
(`impacto(criticidad del activo) × severidad`) requiere `ctx.profile`/`activos_criticos`, que no
existen como pipeline todavía. Se simplificó a **prioridad = severidad del hallazgo**, sin
ponderar criticidad de activo. Cuando `ctx.profile` exista, esto es lo que habría que revisar
primero.

**Otras decisiones:**

- Dirección de dependencia respetada a propósito (doc 04 §3: `recommendations` depende de `ai`,
  nunca al revés): `app/ai/plan_generation.py` recibe `criterion`/`severidad`/`score`/
  `evidence_ids` como argumentos sueltos, no un objeto `Finding` — así `app/ai/` no necesita
  importar `app/recommendations/`.
- La prioridad **no** es parte del contrato de salida de la IA (`PlanContentResponse` no tiene
  campo `prioridad`): la IA redacta objetivo/pasos/verificación; el código decide la prioridad.
  Mantiene "determinismo primero" también en la capa de planes.
- `findings` no se persiste como tabla propia (mismo razonamiento que `score_aggregates`/
  `tier_estimates`: recalcular desde `criterion_results` es barato). Solo `plans` se persiste,
  porque es el artefacto con entidad propia que vale la pena guardar.
- La tabla `plans` ya tiene columnas `origen` (default `"criterio"`) y `estado` (default
  `"abierto"`) pensando en el motor operativo (doc 08): cuando existan incidentes, sus planes
  deberían caber en la misma tabla sin otra migración.

## 10. Motor operativo: vigilancia (flujo A) y disparadores/incidentes (flujo B)

**Qué se construyó:** `app/surveillance/` (`events.py`: parseo/validación de JSONL, falla rápido
con `archivo:línea`; `patterns.py`: `detect_patterns()` sobre 7 patrones; `evidence.py`: patrones
→ `EvidenceInstance`), 4 criterios nuevos (`CRI-DE-02`, `CRI-RS-01`, `CRI-RC-02`, `CRI-RC-03`)
que aplican la "regla de justicia" (docs 06 §5) literalmente, `app/ops/` (`triggers.py`: D1/D3/D4/D5;
`incidents.py`: upsert idempotente por `correlation_key`; `plans.py`: planes de incidente),
tablas `Event`/`LogPatternRow`/`Incident` (a nivel org/scope, no de evaluación — doc 08 §3),
`assessment_service.ingest_events()` (orquesta todo el flujo B) y el hecho de que `run_assessment`
ahora lee automáticamente lo que `ingest_events` dejó persistido para ese org/scope (flujo A
consumiendo flujo B, sin acoplarlos directamente).

**Decisión de alcance, otra vez explícita:** de los 6 escenarios de aceptación de doc 08 §9
(E1/E1-b/E2/E2-b/E3/E3-b), ninguno ejercita el disparador D2 (`alert_raised` sin
`incident_triaged`). Se implementaron D1/D3/D4/D5 — los cuatro que la tabla de aceptación
realmente prueba — y D2 quedó fuera, documentado como corte deliberado, no como omisión.

**Otras decisiones:**

- **Una ventana = un lote ingerido.** Cada llamada a `events <org> <archivo>` se trata como una
  ventana completa y autocontenida (`log.window.completo = True` siempre). Un stream continuo
  real con ventanas deslizantes e ingesta parcial es evolución futura (doc 08 §11); el contrato
  de evidencia ya distingue completo/incompleto para cuando eso exista.
- `recovery_communicated` se agregó como un séptimo patrón aunque doc 06 §3 no lo lista entre los
  "patrones iniciales": sin él, ni `CRI-RC-03` ni el disparador D5 tendrían señal operativa que
  leer. Se decidió agregar el patrón que falta en vez de dejar esa mitad del flujo sin probar.
- **Lectura cuidadosa, no aplicación uniforme de un tope:** los otros tres criterios nuevos
  (`CRI-DE-02`, `RS-01`, `RC-02`) tapan en 75 sin `doc.claim` (mismo patrón que `CRI-PR-02`,
  porque su regla textual exige documento **y** evidencia operativa para el 100). `CRI-RC-03` en
  cambio sí llega a 100 con evidencia puramente operativa, porque su regla dice comunicación
  "definida**/**evidenciada" — un *o*, no un *y* — así que `recovery_communicated` solo ya
  satisface esa rama. Aplicar el mismo tope a los cuatro sin leer cada regla por separado habría
  sido un error.
- **No se persiste una ventana por separado.** `log.window` se reconstruye en el momento desde la
  tabla `Event` (mínimo/máximo `event_time` del org+scope) en vez de guardarse como su propia fila
  — igual que `score_aggregates`/`tier_estimates`/`findings`, es barato de recalcular y evita un
  tercer lugar donde la completitud de la ventana pueda desincronizarse.
- **Ingesta repetida del mismo archivo es un no-op, no un duplicado.** `Event` se deduplica por
  `(org_id, scope, event_id)` y `LogPatternRow` por `(patron, desde, hasta, conteo)` antes de
  insertar. Esto expuso un bug real: comparar un `datetime` recién parseado (consciente de
  zona horaria) contra uno recuperado de SQLite (que descarta `tzinfo` al guardar
  `DateTime(timezone=True)`) fallaba en silencio — el `in` de un set nunca encontraba coincidencia
  porque el *hash* difería, sin lanzar excepción. Se corrigió normalizando ambos lados a naive
  antes de comparar (`_naive()` en `assessment_service.py`).
- **Cooldown real (O4) no implementado.** La idempotencia por `correlation_key` cubre "no
  duplicar el mismo incidente al reingerir", pero un cooldown por tiempo o un rate-limit por
  organización/criterio (p. ej. "no más de un incidente por hora para el mismo disparador") queda
  fuera de este corte — ninguno de los escenarios de aceptación lo necesita.
- Un plan nace de un criterio (`origen="criterio"`, ligado a `assessment_id`) o de un incidente
  (`origen="evento"`, ligado a `incident_id`), nunca ambos. `PlanRow.assessment_id` se volvió
  nullable en esta migración (requirió `render_as_batch=True` en `alembic/env.py`: SQLite no
  soporta `ALTER TABLE ... DROP NOT NULL` directo, solo reconstrucción de tabla).
- El diagnóstico de un plan de incidente es una plantilla determinista por disparador (`D1`→
  "regla de detección ausente...", etc., tomadas de la tabla disparador→plan de docs 06 §7/08 §7),
  no texto generado por IA: solo objetivo/pasos/verificación vienen de `generate_plan_content`
  (U3), reutilizado tal cual en vez de duplicado.
- Probado end-to-end manualmente: `events` sobre el fixture E1-b abrió un incidente cuyo plan de
  plantilla coincide casi palabra por palabra con el ejemplo trabajado de doc 08 §7; una corrida
  de `run` completamente separada para el mismo org/scope calificó `CRI-DE-02 = 0` a partir de esa
  misma evidencia persistida, sin ningún acoplamiento directo entre los dos comandos; y el
  fixture de flujo correcto (E1) confirmó cero incidentes abiertos, probando la regla anti-ruido
  en código real, no solo en un test.

## 11. Simplificaciones activas (consolidado)

Lista única de lo que la especificación describe pero el código todavía no implementa por
completo, para no tener que releer cada sección arriba:

| Simplificación | Dónde | Qué falta para cerrarla |
|---|---|---|
| Sin `ctx.profile` / criticidad de activo | Prioridad de planes (§9) | Modelar `ctx.*` como evidencia y ponderar la fórmula completa de doc 05 §4.2 |
| Sin tabla `ai_adjustments` | Ajuste de IA (§8) | Persistir modelo/prompt_version/propuesta/justificación por separado si el texto en `explanation` deja de ser suficiente |
| `findings` no persistido | Planes (§9) | Solo si recalcular se vuelve costoso |
| `score_aggregates`/`tier_estimates` no persistidos | Núcleo (§3) | Idem |
| Solo hallazgos tipo `brecha` | Planes (§9) | `contradiccion` (doc 02 §5) y `limitacion` quedan para una ampliación |
| `CRI-PR-03` no usa evidencia de Ansible | Ansible (§7) | Decisión deliberada, no pendiente — ver §7 |
| Un `Source` por adaptador, no por archivo | Persistencia (§6) | Solo si se necesita trazabilidad por archivo individual |
| Disparador D2 no implementado | Motor operativo (§10) | Ningún escenario de aceptación (doc 08 §9) lo ejercita; agregar su patron `incident_triaged` cuando haga falta |
| Sin cooldown/rate-limit real (O4) | Motor operativo (§10) | Solo idempotencia por `correlation_key`; falta ventana de tiempo / límite por org-criterio |
| Una ventana = un lote ingerido, sin ventanas deslizantes | Motor operativo (§10) | Stream continuo real es evolución futura (doc 08 §11) |
| `log.window` no persistido (se recalcula desde `Event`) | Motor operativo (§10) | Mismo patrón que `score_aggregates`/`tier_estimates`/`findings` |
| Sin `POST /assessments/{id}/sources`, `/run` ni `/jobs/{id}` | API (§12) | Fusionados en un solo `POST /assessments` síncrono; separarlos exige una cola de trabajos real (doc 04 §11) |
| `app/api/app.py` en vez de `app/main.py` (doc 04 §7 asumía este último) | API (§12) | `app/main.py` ya es la CLI; no se desplaza |
| Sin `worker-core`/`worker-logs`; Redis levantado pero no consumido | Docker (§14) | Requiere `app/workers/` real consumiendo colas; ver §15 |
| Pipeline sigue síncrono incluso en Docker | Docker (§14) | Mismo "respaldo sin Redis" de doc 04 §10/doc 07 §5, ahora reproducible con Postgres real |

## 12. API REST (FastAPI)

**Qué se construyó:** `app/api/` — `app.py` (instancia de FastAPI + routers), `deps.py`
(sesion de BD por request, metodologia cacheada con `lru_cache`), `errors.py` (handlers que
convierten `AssessmentNotFoundError`/`SurveillanceError` a `application/problem+json`, doc 04
§6), `schemas.py` (envoltorios Pydantic propios para lo que no ya era Pydantic: `Assessment`,
`Incident`, comparaciones), `routes_methodology.py`, `routes_orgs.py`, `routes_incidents.py`,
`routes_assessments.py`. Todo delega en `assessment_service` ya existente — la API es una capa
delgada de HTTP sobre lo mismo que usa la CLI, sin logica propia de negocio.

**Decision de alcance (confirmada explicitamente antes de empezar):** doc 04 §6 asume una cola de
trabajos (`POST /assessments/{id}/run` devuelve `job_id`, se consulta en `GET /jobs/{id}`) porque
el pipeline correria en workers de Redis. Sin Redis todavia, `POST /assessments` fusiona
crear + subir archivos + ejecutar en un solo endpoint sincronico que devuelve el resultado
completo de una vez — no existen `POST /assessments/{id}/sources`, `POST .../run` ni
`GET /jobs/{id}`. Documentado como simplificacion deliberada, no como omision.

**Otras decisiones:**

- **`app/api/app.py`, no `app/main.py`.** `app/main.py` ya es la CLI (un entregable real,
  probado, documentado) — doc 04 §7 lo imaginaba como el entrypoint de FastAPI porque en su
  bosquejo no existia una CLI aparte. Se desvia la estructura de carpetas antes que renombrar o
  mover la CLI.
- **`check_live_ai_guard` se movio de `app/main.py` a `app/ai/guard.py`.** Dejo de ser
  "logica de la CLI" el momento en que la API necesito el mismo chequeo antes de cualquier
  llamada real a DeepSeek (extraccion, ajuste, o redaccion de planes de incidente) — ambas
  entradas llaman al mismo cliente, asi que ambas pasan por el mismo guard, ahora vive donde
  ninguna de las dos lo tiene que importar "de prestado" de la otra.
- **Segundo bug real encontrado por un test, no en revision manual:** `_save_uploads` guardaba
  los archivos subidos en un `tempfile.TemporaryDirectory()` que se autoborraba al terminar el
  request. `reevaluate` vuelve a leer esa misma ruta mas tarde (docs/01 §10) — asi que **todo**
  assessment creado por la API quedaria imposible de reevaluar en producción, no solo en tests.
  Se encontro porque el test de reevaluate+compare fallo con `FileNotFoundError` en la primera
  corrida, no por inspeccion de codigo. Arreglado guardando las subidas en
  `backend/.data/uploads/<uuid>/<tipo>/`, persistente (gitignored, igual que `.data/pf.db`), y se
  agrego un test que edita el archivo subido en esa ruta y confirma que `reevaluate` refleja el
  cambio — prueba directa del bug, no solo de que el endpoint "no truene".
- `POST /orgs/{org_id}/events` acepta el JSONL completo como un solo archivo multipart (no un
  body JSON crudo): mismo contrato que `app.main events`, reusando `load_events_jsonl` sin
  cambios — se escribe a un archivo temporal *si* se borra al terminar, porque a diferencia de
  los uploads de evaluacion, los eventos ya quedan persistidos como filas `Event`/`LogPatternRow`
  antes de que el archivo temporal se borre; no hay nada que releer despues desde el disco.
- `GET /assessments/{id}` (y el listado) siempre incluyen los agregados por categoria/funcion y
  el Tier calculados en el momento, no solo el resumen — igual que la CLI, "puntaje y cobertura
  siempre juntos" (doc 04 §6, convenciones).
- Los contratos de dominio que ya eran Pydantic (`CriterionResult`, `Aggregate`, `TierEstimate`,
  `Plan`, `Finding`, `EvidenceInstance`) se devuelven directo como `response_model`, sin
  duplicar un esquema de API paralelo — solo se definieron esquemas nuevos para lo que es
  genuinamente de la capa HTTP (resumen de assessment, incidente, comparacion).
- `ruff`/flake8-bugbear marca `Depends(...)`/`File(...)`/`Form(...)` en defaults como B008 (el
  antipatron clasico de "default mutable"). Es el patron documentado y correcto de FastAPI, asi
  que se añadio a `extend-immutable-calls` en `pyproject.toml` en vez de reescribir cada ruta.
- Probado con `TestClient` (todas las rutas, incluido el guard de IA con una key falsa via
  `monkeypatch`) **y** manualmente con `uvicorn` real + `curl`: subida multipart de Terraform,
  generacion de planes, ingesta de eventos, y — la prueba que realmente importa — una evaluacion
  de madurez completamente separada para el mismo org/scope recogiendo la evidencia de vigilancia
  que dejo la ingesta de eventos, sobre HTTP real, no solo contra la base de datos en memoria de
  los tests.

## 13. Pruebas: gaps cerrados

Revisión de la suite (159 casos en ese momento) hecha antes de seguir con la API. Los dos huecos
de mayor riesgo no eran bugs sino cobertura, y ya están cerrados:

- **E2E de documentos** (`tests/test_assessment_service_documents.py`): `run_assessment` con
  `documents_path` + `FakeAIClient` recorre extracción U1 → evidencia `doc.claim` persistida
  (con `locator.file`) → `CRI-GV-01 = 100`; y con `NullAIClient` degrada a
  `evidencia_insuficiente` sin fallar. Antes solo se probaban `extract_claims` y la regla por
  separado, nunca el cableado.
- **Guarda de migraciones** (`tests/test_migrations.py`): corre `alembic upgrade head` sobre una
  BD SQLite efímera y verifica las tablas del esquema y que `plans.assessment_id` es nullable con
  `incident_id` presente. El resto de los tests usan `create_all`, así que un error de migración
  no se detectaba en CI — fue justo el caso de `render_as_batch` (§10).

Suite tras agregar la API (§12): **183 tests**, `ruff` limpio — incluye 20 tests de API con
`TestClient` (todas las rutas, errores 404/422/409, y el bug real de persistencia de uploads de
§12 probado directamente, no solo evitado). Queda como cobertura opcional, sin urgencia: handlers
de la CLI (`app/main.py`, más allá del guard compartido), `test_methodology_loader` (solo 2
casos pese a que el loader promete fallar rápido) e ingesta con solape parcial (eventos nuevos +
repetidos en el mismo lote).

## 14. Docker Compose + Redis real

**Qué se construyó:** `deploy/docker-compose.yml` (Postgres 16, Redis 7, `migrate` como job de
una sola corrida, `api` sirviendo FastAPI — los 4 servicios ya levantan, se saludan via
healthcheck, y `api` depende de que `migrate` termine bien antes de arrancar), reescritura de
`backend/docker/Dockerfile.api` para usar `uv sync` en vez de `pip install -e` (el proyecto nunca
tuvo `[build-system]`: es una app plana, no un paquete instalable — `pip install -e` nunca
funcionó, solo nadie lo había probado hasta ahora), `.dockerignore` en la raíz.

**Decisión de alcance, la última de esta lista:** `deploy/docker-compose.yml` ya traía escrito
`worker-core`/`worker-logs` apuntando a `python -m app.workers.core`/`app.workers.logs` — módulos
que nunca se construyeron, porque todo el pipeline (evaluación, extracción, ingesta de eventos,
motor operativo) corre síncrono dentro de `api` o de la CLI desde el primer corte (§3) y nunca
dejó de ser así. Mantener esos dos servicios en el compose los habría dejado crasheando al
arrancar (`ModuleNotFoundError`), que es peor que no tenerlos. Se quitaron del compose. Redis
igual se levanta, sano, para no tener que tocar esto de nuevo el día que exista un consumidor
real — pero `api` todavía no lo usa para nada.

Dicho de otro modo: el contenedor final todavía corre exactamente la misma "ejecución síncrona
de respaldo" que docs/04 §10 y docs/07 §5 ya daban por aceptable sin Redis — ponerlo en Docker no
cambió esa decisión, solo la hizo reproducible con Postgres real en vez de SQLite.

**Verificado de verdad, no solo "docker build" sin correr nada:**

- `docker compose build` — ambas imágenes (`api`, `migrate`) construyen limpio.
- `docker compose up` — las 4 migraciones de Alembic corren contra Postgres real (antes solo se
  habían probado contra SQLite efímero, tests incluidos); las 10 tablas esperadas existen
  (`\dt` directo contra el contenedor de `db`).
- Un `POST /assessments` real contra la API en Docker, apuntando a Postgres real, con los datos
  confirmados `select`eando la tabla `assessments` dentro del contenedor — no solo "la API
  respondió 200", sino "el dato está en la base de datos real".
- `docker compose down` + `up` de nuevo: Alembic no vuelve a aplicar nada (ya está en head, lo
  reporta vacío) y el assessment anterior sigue ahí — el volumen de Postgres persiste como debe.
- `docker compose down -v` al final para no dejar nada corriendo ni volúmenes de prueba sueltos.

## 15. Qué sigue

Nada pendiente de los 10 cortes planeados. Lo que sigue, si se retoma este proyecto, es evolución
real: `app/workers/` consumiendo colas de Redis (`log_ingest`, `log_aggregate`, `ops_evaluate`,
los tipos de `job` ya definidos en docs/04 §5) para que `POST /assessments/{id}/run` deje de ser
síncrono — y recién ahí tendría sentido reintroducir `worker-core`/`worker-logs` al compose. El
resto de las simplificaciones del §11 (criticidad de activo, tabla `ai_adjustments`, cooldown real
del motor operativo, etc.) son ampliaciones independientes, ninguna bloquea a otra.
