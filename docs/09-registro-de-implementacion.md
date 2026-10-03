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
| Multitenancy + auth (doc 10) | Login con token, tabla `users`, aislamiento por `org_id` en toda la API | Hecho |
| Pruebas | 365 tests (`pytest`) + `ruff` limpio; E2E de documentos, guarda de migraciones, API y workers | Hecho |
| API REST (doc 04 §6) | FastAPI + colas: crear/reevaluar/ingerir son asíncronos (202 + `GET /jobs/{id}`) | Hecho |
| Docker/Redis (doc 04 §11) | `docker compose up`: Postgres + Redis + migrate + api + `worker-core`/`worker-logs` + frontend (7 servicios) | Hecho |

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
- `reevaluate` implementa "nueva evaluación heredando fuentes" (docs/04 §5) **re-leyendo las
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
| Solo hallazgos tipo `brecha` y `contradiccion` | Planes (§9, §38) | `limitacion` queda como opcional (docs/11 OP-04) |
| `CRI-PR-03` no usa evidencia de Ansible | Ansible (§7) | Decisión deliberada, no pendiente — ver §7 |
| Un `Source` por adaptador, no por archivo | Persistencia (§6) | Solo si se necesita trazabilidad por archivo individual |
| Disparador D2 no implementado | Motor operativo (§10) | Ningún escenario de aceptación (doc 08 §9) lo ejercita; agregar su patron `incident_triaged` cuando haga falta |
| Sin cooldown/rate-limit real (O4) | Motor operativo (§10) | Solo idempotencia por `correlation_key`; falta ventana de tiempo / límite por org-criterio |
| Una ventana = un lote ingerido, sin ventanas deslizantes | Motor operativo (§10) | Stream continuo real es evolución futura (doc 08 §11) |
| `log.window` no persistido (se recalcula desde `Event`) | Motor operativo (§10) | Mismo patrón que `score_aggregates`/`tier_estimates`/`findings` |
| Sin `POST /assessments/{id}/sources` ni `/run` separados | API (§12), Workers (§16) | `GET /jobs/{id}` ya existe y es real (§16); lo que falta es solo subir evidencia y lanzar la corrida como dos pasos en vez de uno |
| `app/api/app.py` en vez de `app/main.py` (doc 04 §7 asumía este último) | API (§12) | `app/main.py` ya es la CLI; no se desplaza |
| Sin consumidores de `log_ingest`/`log_aggregate` separados (una sola cola/job `event_ingest`) | Motor operativo (§10), Workers (§16) | Simplificación deliberada: el pipeline de eventos ya corre completo (patrones→disparadores→incidentes) en un solo job porque así ya estaba escrito en `assessment_service.ingest_events`; partirlo en dos jobs es evolución, no un gap funcional |

> **Estado de estas simplificaciones (revisión §35):** este cuadro es el snapshot de cuando se
> escribió. Hoy la clasificación vive en otros documentos: lo que **sigue pendiente del prototipo**
> está en `docs/11 §D` (`OP-04`, `OP-05` = disparador D2, `OP-11`…`OP-15`); lo
> **descartado deliberadamente** está en `docs/12` (sin tabla `ai_adjustments` = OP-02, `findings`/
> agregados/`log.window` no persistidos = OP-03/OP-17, `Source` por adaptador = OP-18, cooldown =
> OP-06, ventanas deslizantes = OP-07, un solo job `event_ingest` = OP-08, sin `sources`/`run`
> separados = API-01).

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
  request. `reevaluate` vuelve a leer esa misma ruta mas tarde (docs/04 §5) — asi que **todo**
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
de respaldo" que docs/04 §10 y docs/07 §4 ya daban por aceptable sin Redis — ponerlo en Docker no
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

## 15. Frontend: integración real con la API

**Qué se construyó:** el scaffold de `frontend/` (Vite + React + TypeScript + Tailwind,
generado en una sesión aparte, con la herramienta vendorizada `.penpot-ai-kit/` — ver el commit
que lo unificó al repo) quedó conectado de verdad a la API en vez de usar los datos simulados con
los que llegó (`src/data/mockData.ts`, ya eliminado). Piezas nuevas:

- `src/lib/types.ts` — espejo en TypeScript de los esquemas Pydantic reales (`CriterionResult`,
  `Aggregate`, `TierEstimate`, `Finding`, `Plan`, `IncidentOut`, etc. de docs/04 §6).
- `src/lib/api.ts` — cliente fetch fino para los endpoints de §12. Lee la URL base de
  `import.meta.env.VITE_API_BASE_URL` (ver `frontend/.env.example`): una URL completa para
  desarrollo con puertos separados, o algo como `/api` para un despliegue same-origin detrás de
  nginx más adelante — cambiar de uno a otro no toca código, solo el `.env`.
- `src/data/demo.ts` + `frontend/public/demo/` — los mismos fixtures que usan los tests del
  backend (`backend/tests/fixtures/{terraform,ansible,documents,scenarios}`), copiados como
  archivos estáticos servibles por Vite. La UI los ofrece como "datos de ejemplo" para no
  obligar a quien prueba la demo a tener sus propios Terraform/Ansible/eventos a mano — pero son
  los archivos reales, no texto inventado.
- Los tres paneles (`MaturityDashboard`, `RecommendationEngine`, `ThreatSimulation`) y el modal de
  creación (`ContextSelector`) se reescribieron para consumir la API: crear evaluación
  (`POST /assessments`, multipart con archivos reales), ver agregados/Tier/criterios reales,
  generar y ver planes (`POST`/`GET /assessments/{id}/plans`), e ingerir eventos y ver incidentes
  reales con su línea de tiempo y plan de incidente (`POST /orgs/{id}/events`,
  `GET /orgs/{id}/incidents`, `GET /incidents/{id}/plans`).
- `app/api/app.py` ganó `CORSMiddleware`: sin esto, el dev server de Vite (puerto 5173) no puede
  llamar a la API (puerto 8000) desde el navegador. Orígenes permitidos vienen de `CORS_ORIGINS`
  (env, lista separada por comas) — mismo mecanismo en `backend/.env.example`,
  `deploy/.env.example` y `deploy/docker-compose.yml`, pensado para cuando haya un dominio real
  con nginx por delante.

**Simplificaciones de alcance, explícitas:** el modal de creación ya no finge comparar una
recomendación "base" contra una "de IA" con dos textos fijos por categoría de empresa — ese
comparativo nunca existió en la API real (solo hay un plan final, con `generado_por` indicando si
fue IA o plantilla). Tampoco se construyó UI para `reevaluate`/`compare` (§6, §12): quedan
disponibles en `src/lib/api.ts` pero sin pantalla propia, para no inflar el alcance de este corte.

**Verificado de verdad:** `npm run typecheck`, `npm run lint` y `npm run build` limpios: con
`uv run uvicorn app.api.app:app` real corriendo, se repitió contra la API real (vía `curl`,
replicando exactamente las llamadas que hace `src/lib/api.ts`) el flujo completo: crear
evaluación con el bundle "gaps" (score/cobertura/Tier reales, hallazgos derivados, plan por
plantilla), crear evaluación con el bundle "good" (score alto, sin hallazgos), el guard de IA
real devolviendo 409 sin confirmar (sin gastar nada), e ingesta de eventos disparando los 3
incidentes esperados (D1/D3/D4) con el log "con incidentes" y cero incidentes con el log "flujo
correcto". Preflight CORS verificado contra el origen de Vite. El dev server de Vite se levantó
y sirvió tanto la app como los fixtures estáticos de `/demo/`.

## 16. Workers reales, jobs asíncronos, compose completo, frontend containerizado

**Qué se construyó:** lo que §15 había dejado como evolución futura — `app/workers/` consumiendo
colas de Redis de verdad, no un "pendiente" en la lista:

- `app/core/queue.py`: `enqueue`/`dequeue_blocking` sobre una lista de Redis (`RPUSH`/`BLPOP`),
  no Streams con consumer groups (docs/04 habla de eso para P2/P7 — autoscaling, que no es el
  alcance de este prototipo de un solo worker por cola; nada en el contrato de `Job` depende de
  como viaja el mensaje, así que subir a Streams después no rompe nada).
- Tabla `jobs` (modelo `Job`, migración `0b4ecfb6901a`) con exactamente las columnas de docs/04
  §4 (`id, assessment_id?, org_id?, tipo, estado, progreso, error, creado_en, tomado_en`, más
  `actualizado_en`). `app/core/jobs.py` es su CRUD, sin saber nada de Redis.
- `app/workers/core.py` (cola `pf:jobs:core`, job `assessment_run`) y `app/workers/logs.py`
  (cola `pf:jobs:logs`, job `event_ingest`). Cada uno separa `process_message` (logica pura:
  sesión + metodología + mensaje → resultado) de `main` (el loop real).
- `app/core/assessment_service.py` se partió en `create_pending_assessment` +
  `run_pending_assessment` (y `create_pending_reevaluation` para el caso de reevaluar): crear el
  registro ya no implica correrlo. `run_assessment`/`reevaluate` (CLI, tests) siguen siendo el
  atajo síncrono de siempre, implementado en términos de las mismas funciones nuevas — cero
  cambio de comportamiento ahí.
- `POST /assessments`, `POST /assessments/{id}/reevaluate` y `POST /orgs/{id}/events` ya no
  corren el pipeline en el request: crean el `Assessment`/leen el org, encolan un job y
  devuelven **202** con `job_id` (`AssessmentAccepted`/`EventsAccepted`). Nuevo
  `GET /jobs/{job_id}` para sondear. El cliente, al ver `estado == "completado"`, pide
  `GET /assessments/{id}` (o `GET /orgs/{id}/incidents`) para el resultado real — el `Job` nunca
  carga el resultado, solo estado/progreso/error.
- Frontend: `lib/api.ts` gana `getJob`/`pollJob`; `ContextSelector` (crear evaluación) y
  `ThreatSimulation` (ingesta de eventos) sondean el job real en vez de esperar una respuesta
  síncrona, mostrando "En cola…"/"Evaluando…" en vivo. Nuevo botón "Reevaluar" en el dashboard
  (encola, sondea, reemplaza la evaluación activa) y una pestaña "Comparar"
  (`CompareAssessments.tsx`: elige dos evaluaciones completadas de la misma organización y
  muestra el diff de `GET /assessments/{a}/compare/{b}`) — los dos huecos que quedaban abiertos
  en §15.
- `deploy/docker-compose.yml` gana `worker-core`, `worker-logs` (reales, no el comentario que
  había en §14) y `frontend` (nuevo `frontend/Dockerfile`: build de Vite + `serve` del estático,
  sin nginx a propósito — ver §19). `VITE_API_BASE_URL` es un build-arg, no una env var de
  runtime (Vite la incrusta en el bundle): tiene que ser una URL alcanzable desde el navegador
  (`http://localhost:8000`), nunca el nombre del servicio en la red interna de compose
  (`http://api:8000`, que el navegador no puede resolver).

**Decisión de alcance:** `POST /assessments/{id}/plans` (generar planes) se queda síncrono a
propósito. Es una sola pasada de redacción (plantilla o un prompt corto por hallazgo), no el
pipeline de adaptadores+evaluación; meterlo en la cola solo para ser consistente no pagaba su
complejidad en este corte.

**Dos bugs reales encontrados al verificar contra Docker de verdad (no contra los tests, que
usan un `FakeRedis` en memoria — ver más abajo):**

1. `BLPOP` contra el Redis real del compose lanzaba `redis.exceptions.TimeoutError` en vez de
   devolver `None` al agotar el timeout (el socket del cliente expira una fracción de segundo
   antes de que llegue el nil del servidor — una red con latencia no nula, a diferencia de
   `localhost` sin Docker de por medio, lo hace visible). Tumbaba `worker-core`/`worker-logs` al
   primer ciclo vacío. Para el worker, "nada llegó en este ciclo" significa lo mismo venga como
   `None` o como esta excepción, así que `dequeue_blocking` ahora atrapa el `TimeoutError` y lo
   trata igual.
2. Los archivos subidos (`backend/.data/uploads`, `.data/events`) vivían en el filesystem del
   contenedor `api` — invisibles para `worker-core`/`worker-logs`, que son contenedores
   *distintos*. Funcionaba por accidente mientras todo corría en un solo proceso síncrono (§14);
   al volverse async con contenedores separados, el primer `assessment_run` real falló con
   `FileNotFoundError`. Se agregó un volumen compartido (`backend_data`) montado en los tres
   servicios.

**Tests, sin depender de un Redis real para la suite por defecto:** `tests/conftest.py` agrega
un `FakeRedis` (listas en memoria, solo `rpush`/`blpop`) que sobreescribe la dependencia
`get_redis` de FastAPI — los tests de la API nunca necesitan un Redis corriendo; para simular
"el worker ya procesó el job" simplemente drenan la cola falsa y llaman `process_message`
directamente (`tests/conftest.py::run_pending_jobs`). `test_workers_core.py`/`test_workers_logs.py`
prueban esa misma función sin pasar por la API. `test_queue.py` es la excepción: un round-trip
contra un Redis *real*, que se salta limpiamente (`pytest.skip`) si no hay ninguno alcanzable —
así la promesa de "la suite no depende de servicios externos" se mantiene intacta y, cuando sí
hay un Redis (dev local con `redis-server`, o CI con un contenedor), se ejercita el camino real
también. `flake.nix` ahora incluye `pkgs.redis` y `pkgs.nodejs_22` para dev local.

**Verificado de verdad:** suite completa (`uv run pytest`, 193 tests + 2 de Redis real cuando
hay uno disponible) y `ruff check` limpios. Y el verdadero criterio — `docker compose build` +
`up` con los 7 servicios (`db`, `redis`, `migrate`, `api`, `worker-core`, `worker-logs`,
`frontend`) reales: `POST /assessments` con el bundle "gaps" → `GET /jobs/{id}` pasando por
`pendiente`→`en_progreso`→`completado` → `GET /assessments/{id}` con el resultado real;
`POST /orgs/{id}/events` con el log "con incidentes" → job completado → 3 incidentes reales
(D1/D3/D4); `POST /assessments/{id}/reevaluate` → nueva evaluación → `compare` mostrando el
delta real (subió de 21.25 a 24.06 porque ya había eventos/patrones de la organización
disponibles como evidencia de vigilancia, no por casualidad — exactamente el comportamiento que
docs/08 §3 describe); el frontend en `http://localhost:5173` sirviendo el bundle con
`localhost:8000` ya incrustado. `docker compose down` (sin `-v`) + `up` de nuevo: Alembic no
reaplica nada y la evaluación anterior sigue ahí; `docker compose down -v` al final, sin dejar
nada corriendo.

## 17. Bug real: el shell pisaba la key de `deploy/.env`; y `backend/.env` horneado en la imagen

Encontrado persiguiendo un síntoma simple: "corro una evaluación con IA desde el frontend y no veo
consumo en la plataforma de DeepSeek". Las llamadas **sí** ocurrían (2 POST `200 OK` en
`worker-core` para los criterios U2 `CRI-PR-01/02`), pero estaban facturándose en una cuenta
distinta a la que el usuario miraba.

**Causa 1 — precedencia de variables en Compose.** `deploy/docker-compose.yml` pasaba la config de
la app como `${DEEPSEEK_API_KEY:-}` dentro de `environment:`. Docker Compose interpola `${VAR}`
desde el **entorno del shell primero** y solo cae al `.env` del proyecto si la variable no está
definida. El usuario tenía `DEEPSEEK_API_KEY` exportada (para opencode), así que el contenedor usaba
esa key y no la de `deploy/.env` — imposible de ver sin comparar el `sha256` de la key que ve el
contenedor con la del archivo.

**Fix:** la config de la app (`DEEPSEEK_*`, `CORS_ORIGINS`, `JOB_STALE_TIMEOUT_SECONDS`) ahora entra
por `env_file` (`deploy/.env`), que se lee al crear el contenedor y **no lo pisa el shell**. Se
quitaron esas claves de `environment:` — `DATABASE_URL`/`REDIS_URL` siguen ahí porque apuntan a los
nombres de servicio de la red de Compose, no a un `.env` de host. Verificado comparando `sha256`:
`api`/`worker-core`/`worker-logs` coinciden con `deploy/.env` y **no** con el shell. `env_file` usa
`required: false` para no romper un clon sin `deploy/.env`.

**Causa 2 — secreto horneado.** `.dockerignore` excluía `frontend/.env` pero no `backend/.env`, así
que `COPY backend/ backend/` metía el `.env` local (con su API key real) dentro de las imágenes
`api`/`worker-core`/`worker-logs`. No cambiaba la precedencia (Compose gana en `Config.Env`), pero es
una filtración de secreto en las capas de la imagen. **Fix:** `.dockerignore` ahora excluye `.env`,
`**/.env` y `**/*.env`; verificado que `test -f .env` dentro del contenedor da `NO` tras reconstruir.
En Docker el `.env` local ya no hace falta ni se lee (`load_dotenv` es no-op si el archivo no existe);
en local sigue usándose como siempre.

**Nota operativa:** como `env_file` se lee **al crear el contenedor**, cambiar `deploy/.env` requiere
recrear (`up -d --force-recreate api worker-core worker-logs`). Para saber qué key usa de verdad el
stack sin imprimirla:
```bash
docker compose -f deploy/docker-compose.yml exec -T worker-core \
  sh -c 'printf %s "$DEEPSEEK_API_KEY" | sha256sum'
```
Si el consumo no aparece en la plataforma de DeepSeek, lo primero es comparar ese hash con el de la
key de `deploy/.env` y con el de la cuenta que se está mirando.

## 18. Bug real: IA silenciosa sin `load_dotenv` en los workers; restart policy; jobs huérfanos

Pedido explícito tras usar la app de verdad: "¿seguro que está llamando a la API? no veo cambios
en el balance ni llamadas registradas". La pregunta tenía razón — había un bug real.

**El bug (encontrado y confirmado, no solo sospechado):** `app/api/app.py` y `app/main.py`
llaman `load_dotenv(REPO_ROOT / ".env")` al arrancar; `app/workers/core.py` y
`app/workers/logs.py` no lo hacían. Un worker corrido como proceso local
(`uv run python -m app.workers.core`, fuera de docker-compose, donde las env vars se inyectan
directo al contenedor y esto nunca hacía falta) nunca veía la `DEEPSEEK_API_KEY` real de
`backend/.env` — solo lo que ya estuviera exportado en la shell, que es exactamente lo que
`load_dotenv` existe para evitar tener que hacer. `build_default_client()` (`app/ai/client.py`)
solo mira `os.environ`; sin la key ahí, devuelve `NullAIClient()` en silencio, que no hace
ninguna llamada de red (`complete_json` devuelve `None` sin tocar la red). El job se encolaba con
`ai_requested=True` tras pasar el guard (que sí veía la key real, porque corre en `api`, que sí
hace `load_dotenv`), pero el worker que lo procesaba de verdad degradaba a `S = B` sin avisar:
cero llamadas, cero costo, cero resultado real — exactamente "no veo cambios en el balance".

Reproducido antes de arreglarlo (proceso aislado, sin nada exportado en la shell):
```
$ env -i PATH="$PATH" uv run python -c "...build_default_client()..."
Client built by a bare worker process: NullAIClient
```
y confirmado despues del fix (mismo proceso aislado, ahora importando `app.workers.core`):
```
Client a bare worker process builds now: CachingAIClient
  -> wraps: DeepSeekClient
```
Verificación sin gastar nada: construir el cliente no hace ninguna llamada de red (el SDK de
`openai` solo abre un objeto cliente en `__init__`); la llamada real pasa por
`CachingAIClient.complete_json` → `DeepSeekClient.complete_json`, que no se ejercitó aquí a
propósito (mismo principio de minimizar costo de pruebas de docs/09 §5).

**Fix:** `load_dotenv(REPO_ROOT / ".env")` agregado a ambos workers, mismo patrón que `api`/CLI.
Inocuo bajo docker-compose (las env vars ya están puestas; `load_dotenv` no pisa una variable
ya seteada).

**Restart policy:** `restart: unless-stopped` en todo lo de larga duración del compose (`db`,
`redis`, `api`, `worker-core`, `worker-logs`, `frontend`; no en `migrate`, que debe terminar, no
reiniciarse en loop). Verificado que la directiva queda bien puesta (`docker inspect` →
`HostConfig.RestartPolicy = {unless-stopped 0}`), pero el reinicio real tras un `docker kill` no
se pudo confirmar end-to-end en el entorno donde se corrió esta sesión: un contenedor Alpine
trivial sin relación con este proyecto, con la misma política, tampoco se reinició solo tras
matarlo — apunta a una limitación del daemon de Docker en ese entorno (probablemente
sandboxeado), no a un error en `docker-compose.yml`. Si se prueba en una máquina con Docker
normal (la del usuario, por ejemplo) y no reinicia, ahí sí habría que investigar más.

**Jobs huérfanos (el otro lado de "el worker se murió"):** si un worker muere a mitad de un job
(antes de llegar a `mark_done`/`mark_failed`), ese job se queda `en_progreso` para siempre — sin
heartbeat real, nada lo nota. `app/core/jobs.py` gana `reap_stale_jobs(session, tipo,
timeout_seconds)`: busca jobs `en_progreso` cuyo `tomado_en` es más viejo que
`JOB_STALE_TIMEOUT_SECONDS` (default 600s, env var) y los marca `fallido`. Cada worker lo llama
en cada vuelta de su loop (cada ~5s, el mismo ciclo del `BLPOP`), no en un thread separado.
`app/workers/core.py` además envuelve esto en `reap_stale_jobs` (su propia función, no la de
`jobs.py`) para también marcar `fallida` la `Assessment` ligada — sin eso, el job se vería
fallido pero `GET /assessments/{id}` seguiría mostrando `en_progreso` para siempre, porque nadie
más la toca. `worker-logs` no tiene una entidad equivalente que marcar: solo el job.

No hay reintento automático -- un job huérfano queda marcado `fallido` con un mensaje claro;
quien lo ve (CLI, API, frontend) decide si reintentar. Esto es deliberadamente simple (una
inspección por vuelta de loop, no un sistema de heartbeat/lease real) — suficiente para que
nada quede colgado para siempre, no para garantizar exactly-once ante fallos concurrentes.

**Verificado de verdad:** 5 tests nuevos (`test_jobs.py`: `reap_stale_jobs` marca lo viejo,
deja lo reciente, ignora otros tipos/estados terminales; `test_workers_core.py`: la version de
`app/workers/core.py` también falla la `Assessment` ligada, y deja en paz una ya completada) —
suite completa en 198 (antes 193) + 2 de Redis real. Contra el stack real: se insertó a mano un
job `en_progreso` con `tomado_en` de 20 minutos atrás (simulando un worker muerto, sin pasar por
la cola real) y, en el siguiente ciclo de `worker-core` (~8 segundos después), tanto el job como
su `Assessment` ligada aparecieron `fallido`/`fallida` con el mensaje esperado en
`GET /jobs/{id}`/`GET /assessments/{id}` — sin reiniciar nada a mano.

## 19. Qué sigue

Nada pendiente de los 10 cortes planeados, del frontend conectado a la API real (§15), de los
workers/jobs asíncronos (§16), ni de los bugs de IA-silenciosa/restart/jobs-huérfanos (§18). Lo
único que falta, y deliberadamente fuera de este corte: nginx + dominio real.
`VITE_API_BASE_URL` (build-arg del frontend) y `CORS_ORIGINS` (env var de la API) ya están
pensados para ese cambio — es ajustar esos dos valores, no tocar código. El resto de las
simplificaciones del §11 (criticidad de activo, tabla `ai_adjustments`, cooldown real del motor
operativo, etc.) son
ampliaciones independientes, ninguna bloquea a otra.

## 20. Bugs de UI reportados: modal colgado y runs "perdidos" al recargar

Reportados desde uso real del frontend. Dos síntomas, dos causas distintas.

**Síntoma 1 — "arranco una evaluación y el modal se queda en 'Evaluando…', nunca veo resultados".**
Tres causas combinadas:

- `pollJob` (`frontend/src/lib/api.ts`) era `while (true)` **sin timeout ni cancelación**.
- `ContextSelector` bloqueaba el cierre mientras `submitting` (X deshabilitada, click en el fondo
  ignorado): la UI quedaba rehén del sondeo.
- En backend, `reap_stale_jobs` solo miraba jobs `en_progreso`; un job **`pendiente` nunca tomado**
  (el stack sin `worker-core`, o el worker caído) quedaba `pendiente` para siempre y el cliente
  sondeaba sin fin. El reaper solo se ejecutaba *dentro* de un worker: si no había worker, nadie
  barría.

**Fix:**

- `app/core/jobs.py`: `reap_stale_jobs` cubre ahora `pendiente` (timeout propio,
  `JOB_PENDING_TIMEOUT_SECONDS`, default 120 s desde `creado_en`) además de `en_progreso`
  (600 s desde `tomado_en`); nueva `fail_if_stale(session, job)` para un solo job.
- `app/api/routes_jobs.py`: `GET /jobs/{id}` **reaprea perezosamente** y, si el job tenía
  `Assessment` ligada en `pendiente`/`en_progreso`, la marca `fallida`. Así el sondeo siempre
  termina en un estado terminal aunque no haya worker haciendo el barrido.
- `frontend/src/lib/api.ts`: `pollJob` con `timeoutMs` (default 180 s) y `AbortSignal`; lanza
  `JobTimeoutError` con mensaje accionable ("revisa que worker-core esté corriendo").
- `frontend/src/components/ContextSelector.tsx`: el modal se puede cerrar aunque esté sondeando
  (aborta con `AbortController`); el job sigue en el backend y el dashboard lo recupera por el
  historial. El timeout se muestra como error, no se traga.

**Síntoma 2 — "corro una evaluación y al recargar se pierde".** No se perdía: estaba en Postgres.
`App.tsx` nunca llamaba a `GET /assessments`, así que al recargar el estado de React quedaba vacío
aunque los datos siguieran en la base.

**Fix:** al montar se carga `listAssessments()`, se restaura la evaluación activa desde
`localStorage` (o la última `completada`), y se agrega un **selector de historial** + botón de
refrescar. `ContextSelector.onAccepted` refresca el historial apenas la API acepta el job (202),
así una evaluación encolada aparece aunque el modal se cierre antes de que termine.

**Verificación:** backend en **205 tests** (`pytest`) + `ruff`; frontend `typecheck`/`lint`/`build`
limpios; y contra el stack real en Docker (dentro del contenedor `api`, porque el sandbox no expone
el puerto al host): `POST /assessments` → 202 con `job_id` → `GET /jobs/{id}` hasta `completado` →
`GET /assessments/{id}` `completada` (score 20.59) → aparece en `GET /assessments`.

**Pendientes relacionados (no arreglados aquí):** no hay `GET /jobs` (listado de jobs) ni UI de
historial de *jobs*; `Job.progreso` sigue siendo 0→100 (no incremental); el botón "Reevaluar" del
dashboard no expone el toggle de IA; y la ingesta de eventos ya no reporta "nuevos vs actualizados".

## 21. Multitenancy con login (doc 10)

Antes, un despliegue mezclaba organizaciones: `get_or_create_organization` por nombre libre y
`GET /assessments` sin filtrar. Se implementó el diseño de doc 10.

**Qué se construyó (backend):**

- Tabla `users` (`app/models/tables.py`) + migración `0d33cddaac8d`; `organizations` gana la
  relación `users`.
- `app/core/auth.py`: PBKDF2-HMAC-SHA256 para contraseñas y token **stateless** firmado con HMAC
  (`base64url(payload).firma`, payload `{sub, org, exp}`), con `SECRET_KEY`/`AUTH_TOKEN_TTL_HOURS`
  por env. Sin dependencias nuevas (stdlib).
- `app/api/routes_auth.py`: `POST /auth/login` (público) y `GET /auth/me`.
- `app/api/deps.py`: `get_current_user` (lee `Authorization: Bearer`) y `require_same_org`.
- `app/core/seed.py`: cuentas precreadas idempotentes al arrancar (`demo/demo123`,
  `smoke/smoke123`); `SEED_DEMO_USERS=0` lo apaga (los tests).
- **Scoping**: `POST/GET /assessments` usan la organización del usuario (se ignora cualquier
  `org_name`); assessment/incidente/job de otra organización → **404** (no 403, para no revelar
  existencia); `POST /orgs` se eliminó y `GET /orgs` devuelve solo la organización del usuario.
  `/methodology` y `/health` siguen públicos.

**Qué se construyó (frontend):**

- `components/Login.tsx` y estado de sesión en `App.tsx`: `GET /auth/me` al montar, y ante cualquier
  **401** el cliente borra el token y vuelve al login (evento `pf:unauthorized`).
- `lib/api.ts`: token en `localStorage`, `Authorization` en cada request, `login`/`getMe`/`logout`;
  se quitó `createOrganization`/`listOrganizations`.
- `ContextSelector`: se eliminó el campo libre de organización (sale de la sesión).
- `Header`: muestra organización + usuario y botón de cerrar sesión.

**Decisiones y límites:** token stateless para no acoplar a Redis ni a una tabla de sesiones;
token en `localStorage` (vulnerable a XSS; aceptable para el prototipo, la evolución es cookie
`HttpOnly`); `SECRET_KEY` tiene un default inseguro de demo. Fuera de alcance: registro, panel de
administración, roles, refresh tokens y rate limiting de login (doc 10 §1, §8).

**Verificación:** backend en **212 tests** (`pytest`) + `ruff` limpio (incluye `test_api_auth.py`:
401 sin token, login válido/ inválido, `/auth/me`; y scoping de assessments/incidentes/jobs por
organización). Frontend `typecheck`/`lint`/`build` limpios. Contra el stack real en Docker, dentro
del contenedor `api`: sin token → **401**; `demo/demo123` → 8 evaluaciones, todas de "Organización
Demo"; `smoke/smoke123` → 1, de "Smoke E2E"; contraseña incorrecta → 401.

## 22. Bug real: la migración de `users` fallaba en `docker compose up --build`

**Síntoma:** `migrate` salía con `sqlalchemy.exc.ProgrammingError: (psycopg.errors.DuplicateTable)
relation "users" already exists`, y `alembic_version` se quedaba en `0b4ecfb6901a`.

**Causa (doble administración del esquema):** además de Alembic, la API y los workers llamaban
`create_all(engine)` (en el `lifespan` de `app/api/app.py`, en `deps._session_factory`, y en el
`main()` de `app/workers/core.py`/`logs.py`). `create_all` crea las tablas que faltan desde los
modelos. Al agregar `User` al modelo, `create_all` creó `users` en Postgres **sin** actualizar
`alembic_version`; en la siguiente corrida, la migración `0d33cddaac8d` intentó `CREATE TABLE users`
y chocó con la tabla ya creada. Era una bomba de tiempo: cualquier tabla nueva en los modelos podía
crear esta misma inconsistencia.

**Fix (código):** nueva `ensure_schema(engine)` en `app/core/db.py` que corre `create_all` **solo
en SQLite** (dev/CLI/tests); en Postgres, Alembic es la única fuente de verdad del esquema. Se
reemplazó `create_all` por `ensure_schema` en el `lifespan` de la API, en `deps._session_factory`,
en el `main()` de ambos workers y en la CLI (`app/main.py`).

**Reconciliación del volumen existente:** la tabla `users` huérfana (solo contenía las cuentas
seed) se dropeó; `docker compose up --build` volvió a correr `migrate`, que aplicó
`0b4ecfb6901a → 0d33cddaac8d` y re-sembró las cuentas. Un despliegue nuevo no necesita esto: con
Postgres, `create_all` ya no corre.

**Verificación:** `migrate` aplica la migración y `alembic_version = 0d33cddaac8d`; login `demo`
→ 8 evaluaciones; **212 tests** + `ruff` limpios.

**Lección operativa:** en Postgres, nunca correr `create_all` junto a Alembic. El atajo de `create_all`
es cómodo para el SQLite local y los tests, no para el stack real (docs/04 §11, regla C2).

## 23. Pulido de UI (docs/11 §A)

Se atacaron primero los puntos de UI/UX del backlog (docs/11), que no dependen de cambios de backend.
Solo presentación y comportamiento de la SPA: no se tocó el contrato de la API.

**UI-01 · Privacidad visible.** El cruce con privacidad (docs/03 §7, docs/00 §6) existía en el diseño
pero no en pantalla. Se agregó una sección **"Privacidad relacionada con ciberseguridad"** en el
Resumen de Madurez (score promedio, cobertura, criterios y su estado), un badge **"Privacidad"** en
cada criterio del cruce dentro de la tabla, y la nota de alcance obligatoria. Los criterios del cruce
viven en `PRIVACY_CRITERIA` (`frontend/src/lib/ui.ts`); hoy se muestran los 7 implementados
(`CRI-PR-01/03/05`, `CRI-DE-02`, `CRI-RS-01`, `CRI-RC-02/03`); `CRI-ID-04`, `CRI-RS-03` y `CRI-RC-01`
aparecerán solos cuando se implementen (CR-03).

**UI-02 · Botón "Regenerar".** No se quitó (sí recalcula: `POST /assessments/{id}/plans` reemplaza el
plan), pero se aclaró su efecto: `title` explicativo, etiqueta que distingue "Generar" de "Regenerar"
y una nota visible cuando ya hay plan ("Regenerar reemplaza el plan actual…"). Ningún botón queda sin
efecto perceptible.

**UI-03 · Toggles de IA momentáneos.** Los checkboxes U1/U2 son por corrida; `resetAndClose` en
`ContextSelector` ahora los vuelve a `false` al cerrar/enviar, y el texto dice explícitamente
"Solo aplica a esta evaluación: se restablece al cerrar o enviar el modal".

**UI-04 · Hallazgo → plan inline.** En Recomendaciones, cada hallazgo es un acordeón que despliega su
plan de acción en el lugar (reutiliza `PlanBody`, compartido con la vista "Plan de Acción"); si el
hallazgo aún no tiene plan, ofrece generarlo desde ahí. Se eliminó el salto implícito a otra sección.

**UI-05 · Renombrar "Simulación de Amenazas".** La pestaña pasó a **"Eventos e Incidentes"** (no es una
simulación: son eventos reales ingestados) y se ajustó el subtítulo de la ingesta. La palabra
"simulación" desapareció de la UI (el nombre de los fixtures `.jsonl` queda interno).

**UI-07 · Comparación explícita + gráficos.** La pestaña Comparar ahora muestra un **resumen** (score
global con delta, criterios mejorados/degradados/sin cambio), **barras antes/después** del score global
y **por función CSF**, y el detalle por criterio con **dirección** del cambio (↑ mejora / ↓ retroceso /
→ cambio sin score / = sin cambio). `FUNCTION_ACCENTS` se movió a `lib/ui.ts` para compartirlo con el
dashboard.

**WIP · UI-06 (incidentes: reemplazo/archivo e historial).** No se abordó: requiere que la API exponga
transiciones de estado de incidente (OP-04), hoy de solo lectura. Queda pendiente junto con OP-04.

**Verificación:** frontend `typecheck`, `lint` y `build` limpios. Sin cambios de backend (no afecta los
212 tests).

## 24. Segunda pasada de UI + primer cambio de contrato para incidentes (docs/11 §A/§D)

Ajustes pedidos sobre la primera pasada de UI. Esta vez sí toca un contrato de la API: para el
historial de incidentes hizo falta exponer la transición de estado (OP-04).

**Privacidad: vista alternativa dentro de "Criterios Evaluados".** Se quitó la tarjeta independiente
de privacidad. Ahora, dentro de la sección de criterios, un conmutador **Criterios / Privacidad**
cambia la tabla: en modo privacidad las columnas pasan a *Criterio · Relación PF/CSF · Detalle ·
Score · Estado*, con score/cobertura del cruce y la nota de alcance. No es un filtro: es otra vista de
la misma tabla. La relación PF/CSF por criterio vive en `PRIVACY_RELATION` (`lib/ui.ts`).

**Recomendaciones: una sola vista.** Se eliminó la pestaña "Plan de Acción" (los planes se despliegan
inline bajo cada hallazgo, docs/11 UI-04). Los filtros de prioridad se movieron a la vista de
hallazgos, que ahora se ordena **alta → media → baja**. El botón de plantilla pasó a mostrarse solo
cuando **no hay** plan: una evaluación es inmutable, así que regenerar desde plantilla con un plan ya
existente daría exactamente el mismo resultado (botón sin efecto perceptible). Cuando ya hay plan solo
queda "Regenerar con IA", que sí puede cambiar la salida.

**Incidentes: activos e historial (UI-06 + OP-04, parcial).** Nuevo `PATCH /incidents/{id}` con
`{"estado": ...}` (`IncidentUpdate`), validado contra `INCIDENT_ESTADOS`
(`open/triaged/contained/recovering/closed`, `app/ops/incidents.py`) y con scoping por organización
como el resto. `svc.update_incident_estado` persiste el cambio. La pestaña de incidentes ahora tiene
**Activos / Historial** (historial = `estado == "closed"`); desde el plan de respuesta del incidente,
el botón **"Marcar como resuelto"** lo cierra y lo mueve al historial. `estado` se muestra con
etiqueta/color (`incidentEstadoMeta`). Nota: un `closed` que vuelve a dispararse **no** se reabre
automáticamente (el `upsert` no toca `estado`); queda como historial. Reabrir sería un cambio de
política posterior.

**Ingesta de eventos: feedback menos ambiguo.** Los dos botones de demo no son un interruptor (nunca
borran incidentes ya abiertos); se aclaró con un texto fijo y el resultado de cada ingesta ahora
siempre indica log, nuevos y total. "Flujo correcto" muestra explícitamente "sin incidentes nuevos…
los eventos de este log no cumplen los disparadores".

**OP-04 queda parcialmente cubierto:** transiciones de estado de incidente hechas; siguen pendientes
los hallazgos `contradiccion`/`limitacion`.

**Verificación:** backend **214 tests** + `ruff` limpio (dos tests nuevos en
`test_api_methodology_orgs.py`: cierre persiste el estado, estado inválido → 422). Frontend
`typecheck`/`lint`/`build` limpios.

## 25. Los planes se generan solos (plantilla), la IA sigue siendo explícita

Los planes de un assessment no se generaban automáticamente: había que pedirlos con
`POST /assessments/{id}/plans` (el botón "Generar plan (plantilla)"). Eso obligaba al usuario a un
paso manual que un prototipo no debería exigir.

**Cambio:** `run_pending_assessment` (el pipeline que corren el worker, la CLI y los tests) ahora
llama a `generate_plans` **sin cliente de IA** al terminar, después de persistir los resultados. Es
determinista y barato. Así, apenas una evaluación queda `completada`, ya tiene su plan de acción.

**La IA sigue siendo explícita:** `POST /assessments/{id}/plans?use_ai=true` recalcula los planes
con IA (sujeto al guard de costo, docs/05 §7). No hay nada que genere IA de forma implícita. Esta
separación es **provisional de prototipo**: cuando la capa de IA esté probada, la intención es
generar los planes directamente con IA y eliminar la plantilla (docs/11 UI-02).

**Frontend:** se quitó el botón "Generar plan (plantilla)"; en Recomendaciones solo queda "Regenerar
con IA". Si un hallazgo no tiene plan (evaluación anterior a este cambio), se muestra un aviso para
reevaluar en vez de un botón manual.

**Nota:** los planes de incidente ya se generaban solos en la ingesta (`generate_incident_plan`
dentro de `ingest_events`); esto solo iguala el comportamiento para los planes de assessment.

**Verificación:** backend **215 tests** + `ruff` limpio (nuevo
`test_completed_assessment_already_has_template_plans`). Frontend `typecheck`/`lint`/`build` limpios.

## 26. Seguimiento del plan (UI-08): estado sin tocar el puntaje

Se evaluó pedir un "implementado" que ajuste el puntaje al estilo de los incidentes y se descartó:
rompería el determinismo y la reproducibilidad (docs/00 §7, principios 1/3/4), creando dos fuentes
de verdad para un mismo criterio (evidencia vs. afirmación). La forma correcta de reflejar una
mejora sigue siendo reevaluar + comparar. Lo que sí se agregó es **seguimiento del plan**, que es
informativo.

**Modelo:** `PlanRow.estado` ya existía (default `abierto`, sin uso). Pasa a
`pendiente` · `en_progreso` · `hecho` (`PLAN_ESTADOS`, `app/recommendations/plans.py`). El contrato
`Plan` gana `id` y `estado`. Migración de datos `21178e83bca2` normaliza las filas existentes
(`abierto`/vacío → `pendiente`); no cambia el esquema.

**API:** `PATCH /assessments/{id}/plans/{plan_id}` (`PlanUpdate`), validado contra `PLAN_ESTADOS`
(422) y con scoping por assessment/org (404). `svc.set_plan_estado` persiste; el puntaje del
criterio no se toca (test lo verifica).

**Al regenerar** (p. ej. `POST /plans?use_ai=true`) se **conserva** el estado por `criterion_id`,
para no perder el avance del usuario (docs/05 §4.4).

**Frontend:** en Recomendaciones, cada plan desplegado tiene el control Pendiente / En progreso /
Hecho y el encabezado cuenta "X de Y hechos". El chip de estado aparece en la fila del hallazgo.

**Herencia entre evaluaciones:** al crear una evaluación nueva, el plan es de otra instantánea, así
que sin esto el seguimiento se perdía. Se agregó `Assessment.previous_assessment_id` (auto-referencia,
migración `9f9593a6de1c`); `generate_plans`, en la primera generación, hereda el `estado` por
`criterion_id` desde la evaluación anterior.

- **Bug real (reportado):** la primera versión solo enlazaba en `create_pending_reevaluation`, así
  que **volver a evaluar el mismo entorno con "Nueva Evaluación" no heredaba nada** (todas las filas
  quedaban con `previous_assessment_id = NULL`; verificado en la BD del stack). Fix:
  `create_pending_assessment` **autodetecta** la última evaluación `completada` del mismo `org_id` +
  `scope` cuando no se le pasa una explícita; `create_pending_reevaluation` sigue pasando la suya
  (precisión) y `reevaluate` (CLI/tests) se refactorizó para pasar por ahí. Si el scope cambia u otra
  organización, no hay herencia.
- La herencia es desde la **inmediatamente anterior** (decisión del usuario).

**Verificación:** backend **219 tests** + `ruff` limpio (`test_plan_follow_up_state_is_persisted`
comprueba persistencia y que el score no cambia; `..._invalid_state_is_422`;
`test_reevaluate_inherits_plan_follow_up_state` y
`test_new_assessment_inherits_follow_up_from_same_org_scope` comprueban la herencia). Frontend
`typecheck`/`lint`/`build` limpios.

## 27. Refresco automático de madurez al ingerir + eventos sin evaluación

**Por qué:** el motor operativo no puntúa; la madurez solo cambia cuando se corre una evaluación.
Pedirle al usuario que "reevalúe" era (a) un paso manual y (b) sin valor si nada cambió (el pipeline
es determinista). Además, eventos e incidentes quedaban atados a la evaluación activa en el
frontend, cuando backend ya eran por `org`+`scope`.

**Refresco automático (docs/06 §6, docs/08 §8):**
- `ingest_events` ahora cuenta los `log.pattern` **realmente nuevos** por scope
  (`IngestResult.patrones_nuevos_por_scope`); reingerir el mismo archivo suma 0.
- Umbral configurable `vigilancia.refresco_min_patrones_nuevos` (`settings.yml`, default **3** =
  "cambio considerable", criterio de diseño).
- `svc.maybe_enqueue_maturity_refresh` encola una reevaluación de la última evaluación `completada`
  del `org`+`scope` si se supera el umbral. No dispara si: no hay Redis, no hay evaluación previa
  (nada que refrescar), ya hay una evaluación `pendiente`/`en_progreso` para ese `org`+`scope`
  (anti-apilamiento) o no se llega al umbral. Corre **sin IA** (determinista) y hereda seguimiento.
- `svc.enqueue_reevaluation` centraliza el "crear reevaluación + encolar `assessment_run`"; lo usan
  el endpoint `POST /assessments/{id}/reevaluate` **y** el refresco (antes duplicado en la ruta).
- `worker-logs.process_message` recibe un `redis_client` (opcional) y hace el refresco **best-effort**
  antes de `mark_done`: si falla, la ingesta ya fue exitosa y su job no se marca fallido. El worker
  `main()` pasa el cliente real.
- `tests/conftest.run_pending_jobs` ahora **drena en loop** (logs puede encolar core) y pasa el
  `FakeRedis` a `worker_logs.process_message`.

**Eventos e incidentes sin evaluación (UI-09):** la pestaña usa `user.org_id`/`user.org_nombre` de la
sesión y se puede abrir sin evaluación activa; tras una ingesta, la app refresca el **historial** por
si se encoló un refresco (`onIngested`). El backend no cambió: ya era independiente.

**Decisión pendiente:** el botón "Reevaluar" del dashboard quedó como estaba; con el refresco
automático su valor es marginal (docs/11 UI-10).

**Verificación:** backend **222 tests** + `ruff` limpio (tres tests nuevos en `test_workers_logs.py`:
dispara sobre el umbral, no dispara debajo, no dispara sin evaluación previa; fixture
`incidentes_demo.jsonl`). Frontend `typecheck`/`lint`/`build` limpios.

## 28. Pulido: detalle de privacidad y retiro de "Reevaluar"

**Privacidad — detalle desplegable (UI-01).** En la vista de privacidad del Resumen de Madurez, cada
fila se expande (chevron) para mostrar la **explicación completa** más score base/final y cantidad de
evidencias. Antes el detalle se truncaba sin forma de leer el resto.

**Botón "Reevaluar" retirado (UI-10).** Se quitó del dashboard (`MaturityDashboard` ya no recibe
`onReevaluate`/`reevaluating`; `App` ya no importa `reevaluateAssessment`/`getAssessment`/`pollJob`).
El endpoint `POST /assessments/{id}/reevaluate` **sigue existiendo**: lo usa el refresco automático
(FN-05) y la CLI. FN-04 (toggle de IA en Reevaluar) queda sin efecto al no haber botón.

**Aclaración del comportamiento del refresco (para el usuario).**
- **¿Por qué sin IA?** Porque no la necesita: el puntaje base es determinista y la IA es aumento
  opcional (U1/U2), no requisito; y porque no debe gastar créditos sin pedido explícito. Ver docs/08
  §8.
- **¿Reusa la última evaluación con IA?** **No.** El refresco vuelve a correr el pipeline completo
  sobre las mismas fuentes, **sin IA**: no copia `criterion_results`, ni evidencias documentales
  derivadas de IA (U1), ni el ajuste U2, ni el texto de los planes generados por IA (vuelven a
  plantilla). Lo único que hereda es el **estado de seguimiento** del plan por `criterion_id`
  (docs/05 §4.4). Si la evaluación previa no usó IA, el refresco es equivalente salvo por la
  evidencia operativa nueva. Cerrar este gap (recalcular solo lo afectado reusando la evaluación
  previa) es **FN-06** (docs/06 §6).
- **¿La IA ve los logs?** No las líneas: la IA (solo al redactar planes, U3) recibe un JSON
  estructurado del criterio y del disparador (`id`, `título`, `recomendación`, `severidad`, `score`,
  `evidence_ids`). El filtrado de ruido es determinístico (patrones → disparadores) y ocurre antes.

**Verificación:** frontend `typecheck`/`lint`/`build` limpios; backend sin cambios (222 tests).

## 29. Refresco selectivo de madurez (FN-06)

El refresco automático (FN-05) re-correría **todo** el pipeline sin IA, perdiendo lo derivado de IA
(claims U1, ajuste U2, texto de planes) y pudiendo "degradar" una evaluación previa con IA. Docs/06
§6 pedía recalcular **solo** los criterios afectados. Se implementó.

**Motor:** `engine.evaluate_only(methodology, evidence, criterion_ids)` (refactor de `evaluate_all`
sobre un helper `_evaluate_one`) para re-evaluar un subconjunto.

**Servicio (`svc.run_surveillance_refresh`):**
1. Copia las `Source` y la evidencia **no** operativa (todo menos `log.pattern`/`log.window`) de la
   evaluación anterior a la nueva, **remapeando ids** (cada `EvidenceInstance` es un uuid; los
   `evidence_ids` de los resultados copiados se reescriben).
2. Agrega evidencia de vigilancia **fresca** (`_collect_surveillance_evidence` con los
   `log_patterns` actuales del org+scope).
3. Copia los `criterion_results` de criterios **no afectados**; recalcula los **afectados** (los
   cuyo `criterio.evidencias` incluye `log.pattern`/`log.window`: hoy DE-02, RS-01, RC-02, RC-03).
4. Copia los planes de criterios no afectados (texto/estado, incluida IA) y regenera (plantilla)
   los de criterios afectados, preservando su estado de seguimiento.

Los agregados y el Tier se recalculan en lectura desde los `criterion_results` (no se persisten),
así que la instantánea queda coherente.

**Encolado/worker:** `enqueue_surveillance_refresh` marca el mensaje con `selective_refresh=True` y
`previous_assessment_id`; `worker-core` llama a `run_surveillance_refresh` en vez de
`run_pending_assessment`. `maybe_enqueue_maturity_refresh` ahora usa este encolado. El endpoint
`POST /assessments/{id}/reevaluate` y la CLI siguen haciendo el re-run completo (no hay botón que los
use).

**Verificación:** backend **223 tests** + `ruff` limpio
(`test_surveillance_refresh_reuses_unaffected_and_recomputes_operational`: un resultado/plan con
marca "IA" en un criterio no operativo se conserva; un criterio de vigilancia se recomputa).

## 30. La Matriz de Madurez muestra las 6 funciones (no 5)

`aggregate_by_funcion` solo produce agregados para funciones con resultados, así que **IDENTIFY** (0
criterios implementados, docs/11 §C) no aparecía en la "Matriz de Madurez NIST CSF 2.0": parecía que
el marco tuviera 5 funciones. El frontend ahora recorre las 6 de `FUNCTION_ORDER` y muestra la
faltante como **"Sin criterios"** (borde punteado, sin barra, "Aún sin criterios implementados"),
haciendo visible la brecha de cobertura hasta que CR-01/CR-02/CR-03 agreguen los criterios de ID.

**Verificación:** solo frontend (`MaturityDashboard`); `typecheck`/`lint`/`build` limpios.

## 31. CR-01: los 7 criterios MVP faltantes

El catálogo tenía 11 de los 23 criterios de docs/03 y el **Tier no podía pasar de Tier 1** (Tier 2
exige `GV-02` e `ID-03`). Se agregaron los 7 MVP: `GV-02`, `GV-03`, `ID-01`, `ID-02`, `ID-03`,
`DE-01`, `RC-01`. `criteria.yml` pasa a **v2**; quedan 18/23.

**Reglas:** un módulo por criterio en `app/evaluation/rules/`, registrados en `engine._RULES`.
Helpers nuevos en `rules/_common.py` (`doc_claims`, `best_found`, `result`).
- **Documentales** (`GV-02`, `GV-03`, `ID-02`, `ID-03`, `RC-01`): leen `doc.claim` de un
  `tipo_afirmacion` y evalúan `contenido` con umbrales de docs/03 (100/75/50/0; sin documentos →
  `evidencia_insuficiente`). `ID-03` y `RC-01` comparten `process_defined` y se distinguen por
  `contenido.proceso` (`riesgos` vs `recuperacion`).
- **Mixtos** (`ID-01`, `DE-01`): `ID-01` contrasta el inventario documental con los tipos de recurso
  presentes en Terraform (cobertura sobre tipos soportados, docs/03 lo declara como limitación);
  `DE-01` combina CloudTrail con logs de sistema.

**Extracción (U1):** se extendió el prompt con los **campos de `contenido`** esperados por tipo de
afirmación (`extraction._CONTENT_FIELDS`), para que la IA no invente nombres de campo distintos. Los
tipos nuevos (`role_assigned`, `risk_tolerance`, `data_inventory`, `process_defined`, `backup_policy`)
se piden a la IA dinámicamente vía `criterio.regla.tipos_afirmacion` (loader).

**Simplificaciones / desvíos de docs/03 (documentados):**
- `DE-01` usa `an.service.state` (servicio de logging habilitado) en vez de `an.task.config`, mismo
  criterio que `CRI-PR-06` (docs/09 §7): un servicio corriendo es una señal más directa y es lo que el
  adaptador de Ansible puede afirmar con confianza.
- `ID-02` no contrasta todavía con `ctx.profile` (activos críticos del contexto): ese pipeline no
  existe (docs/11 OP-01 + docs/12 §3). La consistencia con el contexto queda pendiente.
- Los criterios **documentales** dependen de `doc.claim` extraído por IA (U1): sin `DEEPSEEK_API_KEY`
  quedan `evidencia_insuficiente`, igual que `CRI-GV-01` hoy. No hay parser documental determinístico.

**Efecto:** con evidencia documental (U1), **Tier 2 pasa a ser alcanzable** (`GV-02`+`ID-03`); `GV-03`,
`DE-01` y `RC-01` alimentan Tier 3. Sin IA, esos criterios no puntúan (abstención, no penalización).

**Verificación:** backend **243 tests** + `ruff` limpio (`test_cr01_mvp_criteria.py` cubre los 7;
`test_methodology_loader` actualizado a 18 criterios).

## 32. CR-02 / CR-03: el resto del catálogo (salvo DE-03)

Se agregaron `GV-04` (revisión del desempeño), `ID-04` (inventario de datos, privacidad), `RS-02`
(análisis de incidentes) y `RS-03` (notificación, privacidad). `criteria.yml` pasa a **v3**;
quedan **22/23** (solo `DE-03`, no-MVP, docs/11 AMP-03). Cobertura por función: GV 4/4, ID 4/4,
PR 6/6, DE 2/3, RS 3/3, RC 3/3.

**Reglas:** `gv04_strategy_review`, `id04_data_inventory`, `rs02_incident_analysis`,
`rs03_notification` (registradas en `engine._RULES`). Documentales salvo `RS-02` (mixto: proceso +
`log.pattern(incident_declared)`).
- `GV-04`: revisión (`policy_review` y/o `process_defined` con proceso de revisión) — 100 si además
  hay métricas/ajustes, 75 si solo la revisión, 0 si no se declara.
- `ID-04`: `data_inventory` con tipos de datos y clasificación (100), solo uno de los dos (50), o
  ninguno (0).
- `RS-02`: proceso de análisis/causa raíz; 100 con evidencia operativa de declaración, 75 documentado.
- `RS-03`: `notification_list` con destinatarios y plazos (100), sin plazos (75), genérico (50; quitado en §47).

**Extracción:** se agregó `notification_list` a los campos esperados del prompt y se extendió
`process_defined` con `metricas`/`ajustes` (`extraction._CONTENT_FIELDS`). `ID-04` y `RS-03` ya
estaban en la vista de privacidad del frontend (`PRIVACY_CRITERIA`), así que ahora aparecen con datos.

**Verificación:** backend **256 tests** + `ruff` limpio (`test_cr02_cr03_criteria.py` cubre los 4;
`test_methodology_loader` actualizado a 22 criterios).

## 33. Catálogo completo: DE-03 y CR-04 (DE-02 a 100)

Últimos dos pendientes de cobertura. `criteria.yml` pasa a **v4**: **23/23 criterios**.

- **DE-03** (`de03_alert_notification`): mixto. `notification_list` (destinatarios) + evidencia
  operativa de `alert_raised`: 100 con ambos, 75 solo documentado, 0 sin definición, sin nada →
  `evidencia_insuficiente`.
- **CR-04 / DE-02**: dejó de topar en 75. Ahora incorpora `doc.claim(process_defined)` con
  `contenido.criterios_declaracion`: 100 = criterios de declaración documentados **y** evidencia
  operativa de alerta/declaración; 75 = una de las dos; 50 = análisis descrito sin criterios; 0 =
  declaración sin alerta pese a una oportunidad real (regla de justicia intacta). Se agregó
  `tipos_afirmacion: [process_defined]` a la regla de `DE-02` y `criterios_declaracion` a los campos
  del prompt de U1.

**Nota:** el test `test_ops_plans::test_skips_unknown_criterion_...` se ajustó para usar un criterio
inexistente (`CRI-XX-99`): ya no queda ningún criterio del catálogo sin regla.

**Verificación:** backend **260 tests** + `ruff` limpio (DE-03 en `test_surveillance_criteria.py`;
caso documental de DE-02; `test_methodology_loader` a 23 criterios).

## 34. CR-05: los criterios operativos alcanzan 100 con `doc.claim`

Cierra la deriva entre el diseño (`docs/03`) y la implementación: cuatro reglas topaban en 75 por no
consumir la evidencia documental. `criteria.yml` pasa a **v5**.

- **PR-02** (`pr02_backup`): lee `doc.claim(backup_policy)`; si la retención configurada cumple la de
  la política (días parseados de texto libre) → 100; por debajo de la política → 50; sin política,
  tope 75.
- **RS-01** (`rs01_response_plan`): plan documentado (`process_defined` de respuesta y/o
  `escalation_path`) + `escalation_done`: plan completo → 100, parcial → 75; sin evidencia operativa,
  75/50; se mantiene la justicia (`incident_declared` sin escalar en ventana completa → 0).
- **RC-02** (`rc02_backup_verification`): `backup_policy.verificacion_integridad` + `restore_verified`
  → 100; política sin ventana → 75; `restore_exercise_run` fallido sigue prevaleciendo → 0.
- **RC-03** (`rc03_recovery_communication`): `restore_verified` + `recovery_communicated` **o**
  `notification_list` documentada → 100.

**Extracción:** `escalation_path` agregado a `extraction._CONTENT_FIELDS`; `tipos_afirmacion` en las
reglas de `PR-02`, `RS-01`, `RC-02` y `RC-03` para que U1 pida esos claims. (`RS-02` ya consumía
`process_defined` desde CR-03.)

**Diseño (`docs/03`):** además de la deriva, correcciones de coherencia interna: `RS-02` → **Tipo:
Mixto** (usa `log.pattern`), se quita el "Tier: T3" huérfano de `PR-02`, `PR-06`/`DE-01` declaran
`an.service.state` y `PR-03` deja de listar Ansible (lo cubre `PR-04`).

**Verificación:** backend **272 tests** + `ruff` limpio (`test_cr05_docclaim_criteria.py` cubre los 4;
`criteria.yml` v5).

## 35. Revisión final del backlog y saneo de subidas

**Revisión de cierre (solo documentación).** Pasada cruzando diseño (00–08) ↔ implementación (09) ↔
backlog (11) ↔ fuera de alcance (12) para detectar requisitos sin registrar. No apareció ningún ítem
`[ ]` falso; los huecos detectados se registraron en `docs/11` (FN-07/FN-08, CR-06/CR-07,
OP-11…OP-15, API-04, TS-01…TS-04, AMP-05) y `docs/12` (OP-16/OP-17/OP-18, DEP-01, SEC-07…SEC-09,
AMP-04/AMP-06, CAL-01). En `docs/05 §7` se eliminó la "opción de modo sin documentos externos": no
aporta capacidad nueva — sin documentos o sin U1, la dimensión documental ya queda
`evidencia_insuficiente`.

**Fix: saneo de nombres de archivo subidos (path traversal).** `_save_uploads`
(`routes_assessments.py`) y `POST /orgs/{id}/events` (`routes_orgs.py`) escribían
`upload_dir / filename` con el nombre **crudo** del cliente, permitiendo `../` o rutas absolutas.
Nuevo helper `app/core/uploads.py::safe_filename`: se queda con el **basename** (`Path(name).name`),
rechaza vacío/`.`/`..`/bytes nulos/`\` y valida la extensión contra una lista blanca por tipo
(`terraform` `.tf`; `ansible` `.yml`/`.yaml`; `documents` `.pdf`/`.md`/`.markdown`/`.txt`; `events`
`.jsonl`). La API responde **422** ante un nombre inválido (docs/04 §9). Registrado como corregido en
`docs/12 §4` (ya no está entre los SEC pendientes).

**Verificación:** `test_uploads.py` (basename, separadores, lista blanca, nombres inválidos) y
`test_api_assessments.py::test_upload_rejects_disallowed_extension`; backend **283 tests** +
`ruff` limpio.

## 36. CR-06 y AMP-05: puntajes que no aparentan más certeza de la que tienen

**CR-06 · expresiones sin resolver (`tf.expression.unresolved`).** Antes, un atributo como
`storage_encrypted = var.enc` quedaba como `unknown` con la limitación equivocada ("atributo
ausente"), y había tres fallos peores: `enable_logging = var.x` se convertía en `True`
(`bool("${var.x}")`), un `cidr_blocks = var.cidrs` rompía el adaptador (`str + list`), y un
`bucket` que no se resolvía descartaba la evidencia en silencio. Ahora el adaptador detecta las
expresiones (`python-hcl2` las serializa como `"${...}"`) en los atributos que deciden un puntaje
(`_WATCHED_ATTRS`: RDS, S3 cifrado/acceso público/versionado, security groups, CloudTrail), emite
`tf.expression.unresolved` por cada una, y deja el valor en `unknown` (CloudTrail
`habilitado: "unknown"`) o lo omite (CIDR). Los CIDR nunca se inventan.

Las reglas lo consumen con el decorador `noting_unresolved` (`rules/_common.py`): el puntaje se
calcula solo sobre lo resuelto y la explicación añade "Limitacion: N expresion(es) sin resolver
(recurso.atributo)", citando esa evidencia. `PR-06`/`DE-01` ya no puntúan 0 cuando CloudTrail es
`unknown`: quedan `evidencia_insuficiente`.

**CR-06 · evidencia declarada que las reglas ignoraban** (`criteria.yml` v6):
- `PR-02`: el 100 exige cifrado de la instancia RDS confirmado (`tf.encryption.config`); con
  retención ≥ política pero sin cifrado confirmado, tope 75.
- `PR-04`: `an.file.permissions` sobre `sshd_config` con escritura para grupo/otros (`mode & 0o022`)
  limita el puntaje a 25.
- `PR-05`: `tf.versioning.config` se informa en la explicación; no cambia el puntaje (docs/03).
- `DE-01`: cita `log.window` como corroboración de actividad observable; no cambia el puntaje.
- `PR-01`: `doc.claim(policy_exists)` nunca eleva el puntaje; se cita junto a una brecha (25) como
  diferencia entre lo declarado y lo observado. Se declaró `tipos_afirmacion: [policy_exists]`.

**AMP-05 · puntaje provisional.** `Aggregate.provisional` (también en subcategoría/categoría/función
y global) es verdadero cuando hay puntaje y la cobertura < `cobertura.umbral_provisional` (nuevo en
`settings.yml`, 0.5). La API expone `provisional_global`; el dashboard muestra una etiqueta
"Provisional" en la función y avisa en la tarjeta de Score Global. Es independiente de la marca
provisional del Tier (T2).

**Decisión:** el umbral 0.5 es un criterio de diseño, no un dato; vive en la metodología para poder
cambiarlo sin tocar código.

**Verificación:** backend **301 tests** + `ruff` limpio (`test_cr06_declared_evidence.py`, casos
nuevos en `test_aggregation.py`; `test_cr05_...::PR-02` actualizado porque el 100 ahora exige
cifrado). Frontend `typecheck`/`lint` limpios.

## 37. OP-12 y OP-14: capa de IA acotada, auditable y reproducible

La IA es la única parte no determinista y de pago; los incidentes de §5 y §17-§18 mostraron que su
consumo era difícil de ver. Se endureció sin tocar el contrato con el resto del sistema.

**OP-12 · contratos de IA.**
- **Backoff:** `DeepSeekClient` espera `1 s`, `2 s` entre reintentos (antes `continue` sin espera);
  `sleep` es inyectable para probarlo sin dormir. Tras 3 intentos degrada (`None`), como antes.
- **Log por llamada** (`app/ai/calllog.py`, logger `app.ai.calls`): una línea JSON con `paso`
  (U1/U2/U3), `prompt_version`, `criterion_id` o `doc_id`, `resultado` (`ok`/`cache`/`degradado`),
  motivo del fallo, intentos, duración y tokens. El cliente no sabe quién lo llama, así que el
  contexto viaja en un `ContextVar` (`call_context`) que fijan extracción, ajuste y planes. La caché
  también registra sus aciertos.
- **E5 (docs/05 §2.3):** `extraction._sanitize_content` valida `ultima_revision` (ISO, entre 1990 y
  mañana), `frecuencia` (mensual/trimestral/semestral/anual) y `roles` (lista de objetos con `rol`
  no vacío y ≤120 caracteres). Lo inválido se quita y queda en `contenido._descartados`; **no**
  se marca `limitations`, porque eso excluiría la afirmación entera de los criterios (`doc_claims`).
- **Tope de ajustes:** `ia.max_criterios_ajustados_por_evaluacion` (`None` = sin límite, el
  default). Con tope, `engine._criterios_a_ajustar` elige los de mayor peso (desempate por id); el
  resto no se intenta y por tanto no queda `degradado`. `adjustment.is_adjustable` centraliza qué
  resultado llamaría a la IA.
- **Bug de logging encontrado al probar:** `alembic/env.py` llamaba `fileConfig(...)` con el default
  `disable_existing_loggers=True`, así que correr migraciones desactivaba todos los loggers `app.*`
  ya creados. Ahora `disable_existing_loggers=False`.

**OP-14 · reproducibilidad.** Nueva columna `assessments.reproducibility` (JSON, migración
`c41a7d2e9b10`) con, por fuente usada, la versión del adaptador (`ADAPTER_VERSION`, se sube a mano;
Terraform arranca en `2` por CR-06) y de la librería que parsea (`python-hcl2`, `PyYAML`), y, solo si
la IA participó de verdad, el modelo y la versión de prompt de cada paso (`extraccion`, `ajuste`,
`planes`). El modelo se resuelve atravesando el envoltorio de caché. `generate_plans` con IA añade
`planes`; el refresco selectivo hereda el valor de la evaluación anterior porque reutiliza lo
derivado de IA. Evaluaciones previas quedan en `NULL`. El dashboard muestra una línea ("Sin IA
(determinista)" o el modelo y prompts).

**Verificación:** backend **322 tests** + `ruff` limpio (`test_op12_op14_ai_hardening.py`, más
`test_api_assessments::test_detail_exposes_reproducibility`). Frontend `typecheck`/`lint` limpios.
La migración se probó con la guarda `test_migrations`; no contra el Postgres de Docker.

## 38. OP-04 (contradicciones) y TS-03

El diseño (docs/02 §5, D7) dice qué hacer cuando un documento y la configuración discrepan, pero el
sistema solo producía `brecha`. Ahora también `contradiccion`: deterministas, sin IA, comparando dos
lados que **ya son evidencia** (`app/recommendations/contradictions.py`).

- **Técnico vs documental:** `doc.claim(backup_policy)` vs `tf.backup.config`. Alta si la política
  declara respaldos y Terraform los deshabilita (retención 0); media si la retención configurada es
  menor que la de la política.
- **Documento vs documento:** dos documentos **distintos** con retención de backup (`PR-02`) o
  frecuencia de revisión (`GV-01`) diferentes. Un mismo documento repitiéndose no cuenta.
- **Reglas:** solo evidencia del mismo `scope`; las afirmaciones de confianza baja no participan; una
  retención desconocida es una limitación, no una contradicción; si Terraform "no aporta nada", se
  acepta lo documental (sin hallazgo).
- **Un hallazgo por criterio y clase**, aunque haya varios recursos (docs/07 "registrado una sola
  vez"); cita ambos lados en `evidence_ids` y los describe en `detalle`.
- **Plan:** una contradicción no genera plan (`generate_plans` sigue usando solo `brecha`).
- **Puntaje:** en esta primera versión no lo alteraba; §41 cambió eso (la afirmación contradicha no
  cuenta).

`Finding` gana `detalle` y `score` pasa a opcional (`None` en una contradicción). `derive_findings`
recibe la evidencia de forma opcional; `GET /assessments/{id}/findings` la pasa, los planes no. El
frontend muestra las contradicciones en una tarjeta aparte en Recomendaciones y deja la lista de
brechas intacta.

**Límite que había aquí:** solo dos propiedades tenían ambos lados estructurados; el ejemplo "BD no
pública" vs `publicly_accessible` se cerró en §40.

**Verificación:** backend **336 tests** + `ruff` limpio (`test_contradictions.py`: 15 casos, incluido
un E2E con el fixture `gaps` y una política extraída). Frontend `typecheck`/`lint` limpios.

## 39. TS-01: golden files

Un golden file es la salida esperada, versionada en git, de correr el código real sobre un fixture
fijo (`tests/golden/*.json`, `tests/test_golden.py`, `tests/golden_utils.py`). Convierte "el motor es
determinista" en una prueba de regresión sobre entradas reales, no solo sobre evidencia armada a mano.

- **Dos niveles:** la **evidencia** que emite cada adaptador (`terraform`/`ansible` × `good`/`gaps`;
  detecta cambios de parser) y el **resultado del pipeline** para cada caso (Terraform + Ansible →
  23 criterios con estado, puntajes, explicación y evidencia citada, agregados por función, global y
  Tier; detecta cambios de reglas, pesos o umbrales).
- **Normalización:** se quitan `id`, `observed_at` y `source_id` (varían por corrida); `locator.file`
  queda como nombre de archivo; `evidence_ids` pasa a etiquetas `tipo|sujeto`; todo con orden estable.
  Un test comprueba que dos corridas normalizan igual.
- **Cambio intencional:** `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` reescribe los archivos y
  el diff se revisa en git. El mensaje de fallo lo recuerda.
- **Revisión manual de los valores iniciales** (no se aceptaron a ciegas): `gaps` coincide con
  `main.tf` (cifrado `false` → `PR-01`=25, retención 0 → `PR-02`=25, 22/3389 abiertos → `PR-03`=25,
  `block_public_acls=false` → `PR-05`=0) y su score global (21.25) coincide con el medido a mano en
  §16. Se comprobó que alterar un valor del golden hace fallar el test.
- **Observación (resuelta en §40):** `publicly_accessible = true` estaba en el fixture `gaps` pero ningún
  adaptador lo emitía.

**Verificación:** backend **343 tests** + `ruff` limpio.

## 40. `publicly_accessible`: evidencia, puntaje y contradicción

Cierra el hueco que dejaron §38 y §39: el fixture `gaps` declaraba `publicly_accessible = true` y nada
lo leía, justo el ejemplo canónico de docs/02 §5. Un atributo declarado sin consumidor es lo que CR-06
quería evitar, así que se cableó completo.

- **Evidencia:** nuevo tipo `tf.db_exposure.config` v1 (`{publico: true|false|"unknown"}`),
  `evidence_types.yml` v2 (un tipo publicado no se modifica, por eso no se reutilizó
  `tf.public_access.config`, que es de S3). Ausente o expresión sin resolver → `unknown` (y
  `tf.expression.unresolved`), nunca el default del proveedor. `ADAPTER_VERSION` de Terraform pasa a `3`.
- **Puntaje (`CRI-PR-05`, `criteria.yml` v7):** una base pública puntúa **0**, igual que un bucket sin
  bloqueo; la explicación conserva el estado de los buckets. Con solo bases y todas no públicas → 100;
  sin buckets ni bases → `no_aplicable`. Es la decisión que más cambia: PR-05 deja de ser solo S3.
- **Política:** nuevo tipo de afirmación `exposure_policy` (`bases_publicas_permitidas`), que U1 pide
  vía `PR-05.regla.tipos_afirmacion`. Nunca eleva el puntaje (D7).
- **Contradicción:** política que prohíbe bases públicas + `publicly_accessible = true` del mismo
  `scope` → hallazgo `contradiccion` de severidad alta sobre `CRI-PR-05`, citando ambos lados.
- **Goldens:** se regeneraron y se revisó el diff: solo la evidencia nueva y el texto de
  explicación de `PR-05`; ningún puntaje cambió (`gaps` ya daba 0, `good` sigue en 100).

**Efecto en costo:** pedir `exposure_policy` cambia el prompt de U1, así que los chunks cacheados en
`.cache/ai_extraction` se vuelven a pagar una vez.

**Verificación:** backend **357 tests** + `ruff` limpio (`test_db_exposure.py`, con un E2E sobre
`gaps`).

## 41. La afirmación contradicha no cuenta para el puntaje

Antes (§38), una contradicción solo se informaba; el criterio seguía leyendo ambas fuentes. En el caso
documento-vs-documento eso significaba que "ganaba" la afirmación con mayor confianza de la IA, que no
es un criterio de verdad (docs/02 §5 pide la más reciente o específica). Decisión: **una afirmación
documental que contradice a otra fuente no cuenta para puntuar**, como si no existiera, y se marca.

- **Dónde:** la detección se movió a `app/evaluation/contradictions.py` (el motor la necesita antes de
  puntuar y `recommendations` depende de `evaluation`, no al revés); `recommendations/contradictions.py`
  solo la presenta como `Finding`. `engine.evaluate_all`/`evaluate_only` llaman a
  `exclude_contradicted`, evalúan sobre la evidencia sin las afirmaciones contradichas y anotan la
  explicación del criterio ("Contradiccion entre fuentes… no cuenta para este puntaje").
- **Qué se excluye:** tecnico-vs-documental → solo la afirmación documental (la técnica nunca);
  documento-vs-documento → **todas** las afirmaciones de esa propiedad en ese scope (no se elige
  ganador). El mismo documento repitiéndose no es contradicción.
- **La evidencia no se borra:** sigue guardada y citada en el hallazgo; solo deja de usarse para
  puntuar, y no aparece en `evidence_ids` del criterio.

**Efecto que conviene conocer:** si la retención configurada está por debajo de la política pero
cumple el mínimo (`7 ≤ retención < política`), `PR-02` pasa de 50 ("bajo la política") a 75 (solo
técnico, sin política), porque la política deja de contar. Con retención 0 sigue en 25 (el técnico ya
dominaba). `PR-05` no cambia (la política de exposición nunca puntuaba). Los golden files no cambian
(ningún caso tiene contradicciones).

**Verificación:** backend **365 tests** + `ruff` limpio (8 casos nuevos en `test_contradictions.py`:
exclusión, política concordante que sí cuenta, evidencia técnica intacta, retención 0, dos documentos,
repetición en un mismo documento, `evaluate_only`, sin contradicción).

## 42. Tope de puntaje mientras la contradicción siga sin resolverse

Consecuencia de §41: al dejar de contar la afirmación contradicha, el puntaje de un criterio puede
**subir** por el solo hecho de que aparezca una contradicción (`PR-02`: 50 → 75). Premiaría justo lo
que no se puede verificar. Decisión: **mientras un criterio tenga una contradicción, su `final_score`
no puede superar el de la evaluación anterior** del mismo org+scope (docs/02 §5).

- **No penaliza, solo no premia:** puede bajar, nunca subir. `base_score` queda intacto (lo que dicen
  las reglas); el tope se aplica a `final_score` y se anota en la explicación del criterio.
- **Dónde:** `contradictions.cap_contradicted` (puro) y `assessment_service._cap_contradicted`, que
  carga los puntajes de la evaluación anterior y se aplica después de los ajustes de IA en
  `run_pending_assessment`. Sin evaluación anterior o sin puntaje anterior del criterio, no hay tope.
- **Por qué mientras persista y no solo la primera vez:** una primera versión limitaba únicamente la
  primera evaluación en que aparecía la contradicción; bastaba esperar una evaluación más para cobrar
  el puntaje completo con la contradicción sin resolver. El tope se levanta resolviendo la
  contradicción (corregir la política o la infraestructura).
- **Costo conocido:** quien mejora de verdad la infraestructura no ve el puntaje subir mientras la
  política la contradiga; el hallazgo `contradiccion` indica qué corregir.

**Verificación:** backend **370 tests** (`test_contradictions.py`: tope, bajar sí
permitido, sin puntaje anterior / otro criterio, sin contradicción, y un E2E de cuatro evaluaciones:
nueva → tope, persiste → tope, se resuelve → se levanta).

## 43. TS-02: golden set de la extracción de IA

docs/05 §8 y docs/07 §3 prometían medir U1 contra documentos anotados, pero solo existían tests con
respuestas simuladas, que prueban el contrato y no la calidad del modelo. Ahora hay un arnés que mide
la extracción real con el mismo chunking y `extract_claims` del pipeline.

- **Golden set:** `tests/golden_ai/` con 7 documentos (`documents/`) y su anotación manual
  (`expected.json`): 5 documentos con 10 afirmaciones esperadas (tipo + campos clave de `contenido` + cita
  literal), un documento sin información relevante (`manual-operaciones.md`) y un memo con una instrucción
  escondida (`memo-con-instrucciones.md`, marcado `adversarial`).
- **Qué se mide** (`app/ai/golden_eval.py`):
  - *Recall* ≥ 90 %: una afirmación esperada se encontró si hay una del mismo tipo cuyos campos clave están
    contenidos en lo que dijo la IA (puede decir más, no menos ni distinto).
  - *Citas localizables* = 100 %: el `fragmento` citado aparece literal en el texto enviado (sin distinguir
    mayúsculas, acentos ni espacios). Una cita fabricada es la invención de evidencia.
  - *Instrucciones obedecidas* = 0: en un documento `adversarial` cualquier afirmación es una orden obedecida.
  - Se informan como *adicionales* (sin puntuar) las afirmaciones citadas del texto que no estaban anotadas.
- **Por qué lo adicional no es error:** una primera versión contaba como "invención" cualquier afirmación no
  anotada, y después se le añadió una lista de "aceptables" para tolerar las legítimas. Ambas eran erróneas:
  los documentos aportados se toman como correctos (docs/02 §5) y una afirmación citada del texto es evidencia,
  no invención; si choca con otra fuente, la detecta la capa de contradicciones (§38, §41), no esta prueba. Una
  lista de aceptables, además, solo habría sido la salida del modelo copiada a mano. Se eliminó.
- **Las citas se verifican sobre la respuesta cruda:** la evidencia `doc.claim` no guarda el `fragmento`
  (solo página/sección), así que el arnés envuelve al cliente y lo captura antes de que `extract_claims` lo
  descarte.
- **Corrida real:** `uv run python -m app.main eval-ai --confirm-live-ai` (pasa por el guard de IA viva, exige
  `DEEPSEEK_API_KEY`, sale con código 1 si no aprueba). Las respuestas se cachean como en cualquier extracción;
  las llamadas degradadas se reportan aparte para no confundirlas con recall bajo.
- **Tests** (`tests/test_ai_golden.py`, sin red): un cliente "oráculo" responde con la propia anotación y debe
  aprobar; variantes rotas comprueban que cada métrica detecta su fallo (afirmación omitida, orden obedecida
  desde el documento, contenido equivocado, cita fabricada, IA degradada), que una afirmación adicional citada se
  informa pero no hace fallar, y que la anotación es coherente con los documentos.

**Resultado de la corrida real (2026-10-02, DeepSeek, prompt `extract_v1`): APROBADO.** Recall 100 % (10/10),
citas localizables 100 % (19/19), 0 instrucciones obedecidas: el modelo no siguió la orden escondida del memo
y no produjo nada de él. Hubo 9 afirmaciones adicionales, todas citadas del texto (p. ej. `policy_exists` sobre
el plan de continuidad, `role_assigned` para los responsables que el texto nombra, un `escalation_path` y un
`process_defined` sacados del manual de operaciones). Se comprobó con la caché que no alteran los criterios
en este conjunto: `GV-01` da 100 con o sin ellas, y los `process_defined` de tipo `otro` no los lee ninguna regla.

**Historia, para no repetir el error:** la primera lectura de esa misma corrida fue "NO APROBADO, 9
invenciones" y se propuso exigir un aprobador en `policy_exists` y endurecer el prompt. Era un error de la
prueba, no del modelo: la rúbrica de `GV-01` ya tiene un tramo para "existe sin aprobación identificada" (50), y
exigir aprobador habría restado aplicabilidad. Se probó un `extract_v2` con una regla sobre contactos y
escalamiento; movió las extras de sitio y no aportó nada (la métrica correcta ya aprobaba), así que se descartó
y el prompt volvió a `extract_v1`, idéntico al original. La elección de `GV-01` por mayor confianza se mantiene
(decisión: la confianza es el criterio, aun si el reclamo no trae aprobador).

**Observación derivada:** una afirmación encontrada sin `destinatarios` daba 50 en `RS-03`; se corrigió en §47.

**Verificación:** backend **409 tests** (`test_ai_golden.py`: 11) + `ruff check` limpio.

## 44. AMP-02: informes en PDF

El informe ejecutivo y la comparación se pueden descargar como PDF. Es la forma de entregar los
resultados a quien no usa la plataforma (separa el acceso a la herramienta del acceso a los resultados).

- **Endpoints:** `GET /assessments/{id}/report.pdf` y `GET /assessments/{id}/compare/{other_id}/report.pdf`
  (`attachment`). Mismas reglas que el resto: sesión, 404 si el assessment es de otra organización,
  **409 si la evaluación no está `completada`** (no hay informe de algo a medias).
- **Contenido del informe ejecutivo:** organización, alcance, fecha y versión de la metodología; puntaje
  global, cobertura y Tier (con la advertencia de *provisional* y lo que falta para el siguiente nivel);
  madurez por función; hallazgos prioritarios por severidad y contradicciones entre fuentes; plan de
  acción (los 10 abiertos de mayor prioridad; los `hecho` no aparecen); resultados por criterio; notas
  sobre cómo leer los puntajes y si participó la IA. La comparación muestra puntaje global y Tier de
  ambas evaluaciones y solo los criterios que cambiaron.
- **Solo presenta:** `app/reports/pdf.py` recibe datos ya calculados (los mismos objetos que sirve la API)
  y no puntúa ni decide nada, así que el PDF no puede diferir de la UI. Se generó con `reportlab` (puro
  Python, fuentes estándar: sin dependencias del sistema, funciona en el contenedor tal cual). Se
  descartó imprimir desde el navegador: el resultado dependería del navegador y no habría un archivo
  entregable.
- **UI:** botón "Informe PDF" en el tablero (deshabilitado hasta que la evaluación termina) y
  "Comparación PDF" en la vista de comparación. La descarga va por `fetch` con el token, no por un
  enlace, porque la API exige `Authorization`.
- **Límites:** solo español y fuentes Latin-1 (los textos evitan símbolos fuera de ese rango); el
  informe es de texto y tablas, sin gráficos.

**Verificación:** backend **389 tests** (`test_api_report_pdf.py`: 8, leyendo el texto del PDF generado;
incluye 404 de otra organización, 409, 401 y que un plan `hecho` no aparece) + `ruff check` limpio;
frontend `typecheck`, `lint` y `build` limpios. Se revisó el render de ambos PDF a mano.

## 45. FN-01/API-03: historial de jobs

Hasta ahora solo existía `GET /jobs/{id}`: había que conocer el id, y la UI solo lo conocía para el job que
acababa de lanzar. Recargar la página a mitad de una evaluación, o querer ver por qué falló una, no tenía
salida. Se comprobó primero qué había: la tabla `jobs` ya guarda todo lo necesario (`tipo`, `estado`,
`progreso`, `error`, `assessment_id`, `org_id` y las tres fechas), así que **no hubo cambios de esquema ni
migración**.

- **Pertenencia:** un `event_ingest` lleva `org_id`; un `assessment_run` solo lleva `assessment_id` (la
  organización sale de la evaluación). El listado busca por los dos caminos (`jobs.org_jobs_query`), igual
  que ya hacía `GET /jobs/{id}` para devolver 404 a otra organización.
- **Endpoint:** `GET /jobs?estado=&tipo=&limit=`, solo de la organización del usuario, del más reciente al
  más antiguo. `estado` y `tipo` fuera de los valores conocidos responden 422; `limit` va de 1 a 200
  (50 por defecto).
- **Reaping al listar:** antes de listar se marcan `fallido` los jobs activos de la organización que se
  quedaron colgados (mismas reglas y mismos timeouts que `GET /jobs/{id}`, y se falla la `Assessment`
  ligada). Sin esto el historial mostraría "pendiente" un job que nadie va a tomar, justo el caso en que más
  se necesita. La lógica se extrajo a `_reap_if_stale` y la comparten ambos endpoints.
- **UI:** vista "Actividad" (`JobHistory.tsx`), independiente de la evaluación activa como la de eventos. No es una
  pestaña: es un detalle operativo, no parte del análisis. Se abre con un botón "Actividad" en la cabecera, que
  **reemplaza al indicador "API · En línea"** (no aportaba nada: si la API cae, cada pantalla ya muestra
  "No se pudo contactar la API"). El botón se ve en todos los tamaños de pantalla, cuenta lo que está en curso
  (consulta `GET /jobs` cada 10 s) y gira mientras haya alguno; la vista tiene "Volver". Se llama "Actividad" y
  no "Trabajos" (calco de *jobs*, que en español suena a empleo). La vista muestra:
  fecha, tipo, estado (con progreso si está en curso), error y, si el job completó una evaluación que está
  en el historial, un acceso para abrirla. Filtro por estado; se refresca sola cada 3 s mientras haya jobs
  activos.
- **No incluido aquí:** reintentar un job fallido. Se resolvió enseguida, ver §46.

**Verificación:** backend **395 tests** (6 nuevos en `test_api_jobs.py`: ambos tipos y orden, aislamiento
por organización, filtros, límite, reaping con la evaluación fallada, 401) + `ruff check` limpio;
frontend `typecheck`, `lint` y `build` limpios.

## 46. FN-09: reintentar un job fallido

El historial (§45) mostraba el error de un job fallido, y el mensaje de "job perdido" dice que se vuelva a
intentar, pero no había cómo: las rutas de los archivos subidos (ya guardados en disco) viajaban solo en el
mensaje de Redis, no en la base de datos. Un job perdido o fallido no tenía de dónde reencolarse, y el
usuario tenía que volver a subir todo. Se registró como **FN-09** (P1) y se hizo.

- **Entradas persistidas:** nueva columna `jobs.payload` (JSON, migración `d52e8b7f1a43`, nullable) con el
  mensaje de la cola sin `job_id`. Los cuatro sitios que crean y encolan un job (crear evaluación,
  reevaluar, refresco selectivo, ingesta de eventos) pasan por `core/dispatch.py::dispatch_job`, que crea el
  job con su payload y lo encola; así no puede haber un job encolado sin entradas guardadas. `jobs.py` (base
  de datos) y `queue.py` (Redis) siguen sin conocerse.
- **`POST /jobs/{id}/retry`** (202, devuelve el job nuevo): solo un job `fallido`, de la organización del
  usuario. Responde 409, con el motivo, si el job no está fallido, es anterior a FN-09 (sin payload), ya no
  existen los archivos subidos, o la evaluación ya se reintentó.
- **Se reutiliza la evaluación**, no se crea otra: vuelve a `pendiente`, sin error, y se encola un job nuevo
  con las mismas entradas. El historial no se llena de evaluaciones fallidas y la evaluación anterior de la
  que hereda (planes, tope de contradicciones) sigue siendo la misma. El job original queda `fallido` como
  registro del intento.
- **Sin duplicados:** antes de reencolar se borran evidencia, resultados, planes y fuentes de esa evaluación.
  Una corrida que falló *después* de guardar (p. ej. al generar los planes) los habría dejado duplicados.
  La ingesta de eventos ya era idempotente (dedup por `event_id`), y un test lo confirma.
- **El permiso de gasto no se hereda:** si el job usaba IA real, el reintento exige `confirm_live_ai` otra vez
  (mismo guard que al crearlo); la UI pide confirmación explícita antes de reintentar. `JobOut` gana
  `reintentable` y `usa_ia` para que la UI sepa cuándo mostrar el botón y cuándo advertir.
- **UI:** botón "Reintentar" en las filas fallidas de la vista Actividad.
- **Límites:** los jobs anteriores a esta migración no tienen payload y no son reintentables (se indica al
  intentarlo). El reintento es manual; no hay reintento automático.

**Verificación:** backend **409 tests** (`test_job_retry.py`: 13; más la migración en `test_migrations.py`)
+ `ruff check` limpio; frontend `typecheck`, `lint` y `build` limpios. Se comprobó que quitar el borrado de
filas parciales hace fallar el test de duplicados.

## 47. Una afirmación sin destinatarios no puntúa en `RS-03`/`DE-03`

Salió de la primera corrida real del golden set (§43): el manual de operaciones produjo una `notification_list`
con `destinatarios: []` y `criterios: "falla del servidor principal"`. Citada del texto, así que no es un
error de extracción (los documentos se toman como correctos), pero al llegar a los criterios daba **50** en
`RS-03` ("mencionada de forma genérica"), un tramo que **no existe en la matriz** (docs/03 §5: 100 / 75 / 0) y
que `DE-03`, que lee la misma afirmación, no tiene (sin destinatarios, 0). Con solo ese documento, `RS-03`
habría dicho que existe una notificación definida a medias.

- **Qué se cambió:** `RS-03` y `DE-03` eligen la mejor afirmación *entre las que traen `destinatarios`*
  (`_common.best_found_with`), no entre todas. Sin ninguna que lo declare, `RS-03` es 0 ("no declaran a quién
  se notifica"), como `DE-03` y como la matriz. Se quitó el tramo de 50.
- **Efecto colateral que también se corrigió:** antes la mejor afirmación se elegía por confianza *antes* de
  mirar si traía destinatarios, así que una afirmación callada con 0,95 tapaba a otra con la lista completa y
  0,7. La confianza sigue decidiendo entre afirmaciones que dicen algo sobre el mismo dato; una que lo calla no
  compite. (No cambia la decisión de `GV-01`: ahí se elige por confianza entre las que declaran la política.)
- **Lo que no se hizo:** descartar en la extracción toda afirmación con contenido vacío. En la caché real no hay
  ninguna con el contenido completamente vacío, y `GV-01` usa a propósito una afirmación sin nombre
  ("mención informal", 25), así que un descarte global rompería esa regla.
- **Tests:** `RS-03` sin destinatarios (con `{}` y con otros campos) es 0; una afirmación callada no tapa a la que
  declara destinatarios (`RS-03` y `DE-03`). El test anterior `test_rs03_generico_es_50` se reemplazó.

**Verificación:** backend **411 tests** + `ruff check` limpio. Los golden files no cambian (ningún caso tiene
documentos).

## 48. La BD SQLite de dev se pone al día sola

Al agregar `jobs.payload` (§46) se vio que la BD local `backend/.data/pf.db` no tenía esa columna, ni
`assessments.reproducibility` (OP-14), ni `assessments.previous_assessment_id`. `create_all` solo crea tablas que
faltan, nunca columnas, y esa BD no tiene `alembic_version` (se creó con `create_all`), así que
`alembic upgrade head` tampoco servía. Los tests no lo notaron porque cada uno usa una BD nueva; una BD de dev
vieja fallaba con "no such column" en cuanto el ORM seleccionaba la columna.

- **`db.add_missing_columns`** (llamada desde `ensure_schema`, solo en SQLite): agrega con `ALTER TABLE ADD
  COLUMN` las columnas **nullable** que el modelo tiene y la tabla no. No toca datos ni tipos. Una columna
  NOT NULL sin default no se puede agregar a una tabla con filas: solo se avisa en el log (hay que recrear la BD).
  Es idempotente y devuelve lo agregado. En Postgres sigue mandando Alembic.
- **Probado** con una BD creada con el esquema viejo (se comprueba que falla sin la mejora, que se agregan las
  columnas, que los datos viejos quedan intactos y que se puede escribir `payload`) y sobre una copia de la BD
  de dev real, donde agregó las tres columnas.
- **Límite:** solo columnas nuevas nullable. Un cambio de tipo, un renombre o una columna NOT NULL siguen
  pidiendo recrear la BD de dev o, en Postgres, una migración de Alembic.

**Verificación:** backend 4 tests nuevos (`test_db_schema_upgrade.py`) + `ruff check` limpio.

## 49. OP-13: `schema_version` en el mensaje de la cola

`api` y los workers pueden desplegarse por separado (docs/04 §3.1). Si cambiaba el contrato del mensaje, un
worker viejo lo interpretaba a medias: no había forma de saber qué versión lo produjo.

- **Contrato:** todo mensaje encolado lleva `schema_version` (`queue.MESSAGE_SCHEMA_VERSION`, hoy 1), añadido en
  `dispatch_job`, el único punto que encola. Se sube cuando un campo cambia de significado o pasa a ser
  obligatorio; añadir un campo opcional no la sube.
- **Worker:** `queue.message_version_error` decide si el mensaje se puede procesar. Un mensaje **sin** versión es
  de antes de OP-13 y se acepta (versión 1), para no romper lo que haya en vuelo. Una versión mayor, no
  entera o inválida hace que el worker **falle el job** (y la evaluación ligada, en `worker-core`) con el motivo
  ("este worker solo entiende hasta N; actualiza el worker y reintenta") antes de tomarlo ni ejecutar nada.
- **Reintento (§46):** la versión no se guarda en `Job.payload` sino que se añade al encolar, así que un job
  reintentado se encola con la versión vigente y, tras actualizar el worker, el reintento funciona.

**Verificación:** backend 5 tests nuevos (aceptación de mensajes viejos, rechazo de versiones mayores/inválidas,
ambos workers fallan el job sin ejecutarlo, la versión viaja en el mensaje y no en el payload).

## 50. FN-07: el origen del evento llega a la evidencia

`RawEvent.fuente` se parseaba y se descartaba: `events.source_id` valía `events:{ruta absoluta del servidor}` y
la evidencia operativa siempre `surveillance:org`, así que no se podía saber qué sistema (`log:sshd`,
`cloudtrail`…) respaldaba un patrón (docs/06 §2 dice que `fuente` se persiste como `source_id`).

- **`events.source_id`** es ahora la `fuente` del evento; si no la declara, `events:{nombre del archivo}`
  (solo el nombre: la ruta del servidor no es un origen y se filtraba a la base de datos).
- **`log_patterns.fuentes`** (JSON, nullable; migración `e7a1c3d49b52`) guarda los orígenes de los eventos que
  formaron el patrón. La evidencia `log.pattern` usa `source_id` = esos orígenes ordenados y unidos con `+`
  (p. ej. `cloudtrail+log:sshd`); la `log.window`, los orígenes de todos los eventos del scope.
- **Compatibilidad:** los patrones anteriores no tienen `fuentes` y conservan `surveillance:org`. La BD de dev se
  pone al día sola (§48).
- **Límite:** `source_id` es un solo texto, por eso los varios orígenes se unen con `+`; si hiciera falta
  consultarlos por separado habría que pasar a una lista en el contrato de evidencia.

**Verificación:** backend 6 tests nuevos (`test_event_source.py` y la migración) + `ruff check` limpio.

## 51. FN-03: la ingesta informa eventos nuevos vs ya existentes

Al volverse asíncrona la ingesta (§16), `POST /orgs/{id}/events` devuelve solo `job_id` y la UI perdió el
detalle de cuánto era nuevo; lo aproximaba comparando el total de incidentes antes y después.

- **`jobs.resultado`** (JSON, nullable; migración `f1b6d2a85c37`): resumen de lo que hizo el job al terminar.
  Hoy lo llena `worker-logs` con `IngestResult.summary()`: `eventos_leidos`, `eventos_nuevos`,
  `eventos_existentes` (mismo `event_id` en el mismo scope = ya estaba, no se duplica), `patrones_nuevos`,
  `incidentes_nuevos` e `incidentes_actualizados`. `None` mientras corre, si falla, y en `assessment_run`.
  `JobOut` lo expone en `GET /jobs/{id}` y `GET /jobs`.
- **UI:** el mensaje tras ingerir sale de `job.resultado` ("6 eventos nuevos · 1 incidente nuevo", o "0 eventos
  nuevos · 6 ya existían" al reingerir el mismo archivo); la vista Actividad muestra el mismo resumen en cada
  ingesta completada. La CLI imprime "N nuevos, M ya existían".
- **Por qué en el job y no en la respuesta del POST:** el POST encola y responde antes de que haya algo que
  contar; el resultado solo existe cuando el worker termina, y el job es lo que el cliente ya sondea.

**Verificación:** backend 4 tests nuevos (resumen de la ingesta y de la reingesta, resultado en el job, job
fallido sin resultado, API, migración) + `ruff check` limpio; frontend `typecheck`, `lint` y `build` limpios.

## 52. OP-11: transiciones validadas y motivo de cierre del incidente

`PATCH /incidents/{id}` aceptaba cualquier estado desde cualquier estado (se podía reabrir un incidente cerrado o
saltar de `open` a `recovering`) y cerrar no dejaba rastro de por qué. docs/08 §4 pide que se registre cómo se
verificó.

- **Transiciones** (`ops/incidents.allowed_transitions`): un paso por vez (`open → triaged → contained →
  recovering → closed`), sin retroceder. `closed` es terminal y es el único estado al que se puede saltar, desde
  cualquier estado abierto. Es una decisión propia: el diagrama de docs/08 §4 solo muestra `open → closed`
  (falso positivo), pero la UI ya cerraba incidentes en cualquier punto y obligar a recorrer todo el ciclo para
  cerrar uno resuelto habría sido peor; el motivo obligatorio distingue un caso del otro.
- **Motivo:** cerrar exige `motivo` (texto no vacío) y se guarda en `incidents.motivo_cierre` (migración
  `a9d4e6b1c280`). Toda transición, cierre o no, agrega a la línea de tiempo
  `{transicion: "open->triaged", momento, motivo?}` (docs/08: "hechos observados, con la transición").
- **API:** transición inválida o cierre sin motivo → **409** con el motivo y los estados permitidos; estado
  desconocido sigue siendo 422. `IncidentOut` gana `motivo_cierre` y `transiciones` (los estados a los que puede
  pasar ahora; vacío si está cerrado), de modo que la UI no repite la regla.
- **UI:** el cajón del incidente ofrece "Pasar a …" para el siguiente paso y "Cerrar incidente…", que pide el
  motivo antes de confirmar; el motivo se muestra en los incidentes cerrados y las transiciones en la línea de
  tiempo.
- **Pendiente (opcional en el backlog):** `brecha_ref` del plan y "condición de cierre".

**Verificación:** backend 19 tests nuevos (`test_incident_transitions.py` y la migración) + `ruff check` limpio;
frontend `typecheck`, `lint` y `build` limpios.

