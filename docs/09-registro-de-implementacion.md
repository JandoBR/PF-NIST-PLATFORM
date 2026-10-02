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
| Pruebas | 223 tests (`pytest`) + `ruff` limpio; E2E de documentos, guarda de migraciones, API y workers | Hecho |
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
| Solo hallazgos tipo `brecha` | Planes (§9) | `contradiccion` (doc 02 §5) y `limitacion` quedan para una ampliación |
| `CRI-PR-03` no usa evidencia de Ansible | Ansible (§7) | Decisión deliberada, no pendiente — ver §7 |
| Un `Source` por adaptador, no por archivo | Persistencia (§6) | Solo si se necesita trazabilidad por archivo individual |
| Disparador D2 no implementado | Motor operativo (§10) | Ningún escenario de aceptación (doc 08 §9) lo ejercita; agregar su patron `incident_triaged` cuando haga falta |
| Sin cooldown/rate-limit real (O4) | Motor operativo (§10) | Solo idempotencia por `correlation_key`; falta ventana de tiempo / límite por org-criterio |
| Una ventana = un lote ingerido, sin ventanas deslizantes | Motor operativo (§10) | Stream continuo real es evolución futura (doc 08 §11) |
| `log.window` no persistido (se recalcula desde `Event`) | Motor operativo (§10) | Mismo patrón que `score_aggregates`/`tier_estimates`/`findings` |
| Sin `POST /assessments/{id}/sources` ni `/run` separados | API (§12), Workers (§16) | `GET /jobs/{id}` ya existe y es real (§16); lo que falta es solo subir evidencia y lanzar la corrida como dos pasos en vez de uno |
| `app/api/app.py` en vez de `app/main.py` (doc 04 §7 asumía este último) | API (§12) | `app/main.py` ya es la CLI; no se desplaza |
| Sin consumidores de `log_ingest`/`log_aggregate` separados (una sola cola/job `event_ingest`) | Motor operativo (§10), Workers (§16) | Simplificación deliberada: el pipeline de eventos ya corre completo (patrones→disparadores→incidentes) en un solo job porque así ya estaba escrito en `assessment_service.ingest_events`; partirlo en dos jobs es evolución, no un gap funcional |

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
- `RS-03`: `notification_list` con destinatarios y plazos (100), sin plazos (75), genérico (50).

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
