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
| Control de costo de IA | Store persistente `ai_results` (BD) + votación U1, tope de chunks/documento, guard de arranque | Hecho |
| Persistencia | SQLAlchemy + Alembic + SQLite por defecto, `run`/`reevaluate`/`compare` | Hecho |
| Adaptador Ansible | Parser YAML, CRI-PR-04, CRI-PR-06 ahora Mixto de verdad | Hecho |
| Ajuste de IA (U2) | Fórmula B/A/D/α → S acotada, con todas las reglas J1–J7/R3–R6 | Hecho |
| Planes (U3) | Hallazgos → planes priorizados, alcance simplificado (sin criticidad de activo) | Hecho |
| Motor operativo (docs 06/08) | Eventos → patrones (flujo A) + disparadores → incidentes → planes (flujo B) | Hecho |
| Multitenancy + auth (doc 10) | Login con token, tabla `users`, aislamiento por `org_id` en toda la API | Hecho |
| Pruebas | 1023 tests (`pytest`) + `ruff` limpio; E2E de documentos, guarda de migraciones, API y workers | Hecho |
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

## 53. OP-05 y FN-08: disparador D2 y los patrones de triaje y contención

D2 (`alert_raised` sin `incident_triaged`) se había dejado fuera (docs/09 §24) porque necesitaba un patrón de
`incident_triaged` que nada más usaría, y los tipos `incident_triaged` y `containment_done` se parseaban y se
descartaban. Ahora D2 es el consumidor del primero y el segundo queda documentado como contexto.

- **Patrones** (`surveillance/patterns.py`): `incident_triaged` y `containment_done` pasan a ser patrones de
  existencia, así que quedan como evidencia `log.pattern` (que además cuenta para el umbral del refresco
  automático de madurez) en vez de perderse al parsear.
- **D2** (`ops/triggers._d2_sin_triaje`): hay `alert_raised` y no hay `incident_triaged` dentro de
  `vigilancia.plazo_triaje_minutos` (30, en `settings.yml`, igual que `plazo_escalamiento_minutos`). Un triaje
  anterior a la alerta no cuenta como su triaje. Severidad media, criterio `CRI-RS-01`, clave de correlación
  `alert-sin-triaje:{recurso}:{momento de la alerta}`, plan con plantilla de diagnóstico propia. Si hay ráfaga de
  fallos *y* alerta no se dispara D1 (hay alerta), sí D2 si nadie la triajea.
- **`containment_done` es solo contexto:** ningún criterio ni disparador lo consume. Se decidió no sumarlo a
  `RS-01` por ahora porque cambiaría puntajes sin un caso que lo pida; queda registrado como evidencia y
  documentado así en docs/06 §3.
- **Metodología:** `settings.yml` pasa a `version: 2` (nuevo umbral y nuevo disparador cambian resultados, y
  `methodology_version` debe reflejarlo). El escenario `e1_flujo_correcto` sigue sin crear incidente (hay
  triaje a los 60 s); `e1c_alerta_sin_triaje.jsonl` es el nuevo escenario de D2.

**Verificación:** backend 12 tests nuevos (D2 dentro/fuera/antes del plazo y sin alerta, el escenario E1-c con su
plan, los dos patrones) + `ruff check` limpio. Los golden files no cambian.

## 54. OP-15: la evidencia apunta a líneas concretas

`Locator.line_start/line_end` existían y nunca se llenaban: la evidencia de Terraform y Ansible solo decía "en
este archivo". Ahora indica qué líneas.

- **Terraform** (`resource_line_ranges`): `python-hcl2` no devuelve posiciones (su opción `with_meta` no las
  entrega en esta versión), así que se calculan sobre el texto: el bloque empieza en `resource "tipo" "nombre" {`
  y termina donde se cierra su llave, sin contar llaves dentro de strings ni de comentarios. Toda la evidencia de un
  recurso lleva sus líneas. Adaptador **v4**.
- **Ansible**: se compone también el árbol de nodos de PyYAML y cada tarea lleva sus líneas. PyYAML deja
  `end_mark` donde empieza el token siguiente, no donde acaba el nodo, así que se retrocede hasta la última línea
  con contenido (se vio en los golden: la primera versión solapaba una tarea con la siguiente). Adaptador **v2**.
  `an.playbook.present` no lleva líneas: es el archivo entero.
- **Recursos Terraform no soportados:** su `tf.resource.present` ahora trae la limitación "tipo de recurso no
  soportado: se registra su presencia, no sus atributos" (antes parecía una evidencia completa).
- **`resuelto_por: parser`: se corrigió la documentación, no el código.** docs/02 §4 prometía resolver variables
  locales literales; el adaptador no lo hace a propósito (una variable es una expresión no resuelta y el criterio
  decide con `unknown`, que es más seguro que adivinar). Implementarlo agregaría riesgo sin un caso que lo pida.
- **`created_by`:** docs/01 no listaba `surveillance`, que usa la evidencia operativa; se agregó.
- **Golden files:** se regeneraron los de los adaptadores y se revisó el diff: solo cambian los locators y las
  limitaciones de los tipos no soportados.

**Verificación:** backend 5 tests nuevos (rangos con anidación, strings y comentarios, bloque sin cerrar, líneas de
Terraform y de Ansible, limitación de lo no soportado) + `ruff check` limpio.

## 55. API-04: todos los errores son `problem+json` y toda respuesta lleva la versión de metodología

docs/04 §6 prometía errores `application/problem+json` y `methodology_version` en toda respuesta. Solo dos
excepciones propias (`AssessmentNotFoundError`, `SurveillanceError`) salían como problem+json; el resto
(`HTTPException` de jobs, incidentes, auth…, la validación 422 y los 500) salía con el `{"detail": ...}` de
FastAPI, y la validación con `detail` como lista de objetos.

- **Errores** (`api/errors.py`): handlers para `HTTPException` (conserva sus cabeceras), `RequestValidationError`
  (422) y cualquier excepción no prevista (500). Forma común: `type`, `title` (la frase HTTP), `status`,
  `detail`, `instance`. `detail` es **siempre texto**, así que el cliente lo muestra tal cual (la UI ya leía
  `body.detail`); la validación lo resume ("limit: …") y agrega `errors` con `loc/msg/type` por campo. El 500
  responde un mensaje genérico y deja el detalle en el log: no filtra mensajes ni trazas internas.
- **Versión de metodología:** middleware que añade `X-Methodology-Version` a toda respuesta (incluidos los
  errores 4xx), y CORS la expone al navegador junto con `Content-Disposition`. Se eligió una cabecera y no un
  campo en cada cuerpo para no tocar todos los esquemas; las evaluaciones ya la traían en el cuerpo.
- **Límite:** un 500 que genera el servidor antes del middleware no lleva la cabecera.

**Verificación:** backend 6 tests nuevos (`test_api_errors.py`: 404, 409, 401, 422, la cabecera en varias rutas y que
el 500 no filtra) + `ruff check` limpio.

## 56. OP-04 (resto): hallazgos de tipo `limitacion`

Era lo único que quedaba de OP-04. Cuando una expresión de Terraform no se resuelve (`var.x`, funciones, módulos)
o un atributo falta, el criterio ya lo decía en su explicación (CR-06), pero no era un hallazgo: no aparecía junto
a las brechas y las contradicciones, ni en el informe.

- **Qué es:** un hallazgo `limitacion` dice **qué parte de un resultado hay que leer con cautela y por qué**. No
  puntúa (`score: null`), no genera plan y no es una brecha; severidad fija `baja`, porque mide la certeza del
  análisis y no la gravedad de lo evaluado.
- **Derivación** (`recommendations/limitations.py`): de la evidencia que el propio criterio citó en su resultado.
  Una `tf.expression.unresolved` da "{recurso}.{atributo} sin resolver" con la expresión y el motivo; una evidencia
  `tf.*` con `estado: unknown` da "{recurso}: estado desconocido". Un hallazgo **por (criterio, evidencia)**: la
  misma expresión puede condicionar a dos criterios (`enable_logging` → `PR-06` y `DE-01`) y cada uno la lee
  distinto. Un recurso desconocido *porque* una expresión no se resolvió no se repite: ya lo explica la expresión.
- **Se pide con la evidencia** (`derive_findings(…, evidence)`); la generación de planes no la pasa, así que las
  limitaciones nunca producen un plan.
- **UI:** tarjeta "Limitaciones del análisis" en Recomendaciones, aparte de la de contradicciones; las brechas
  (la lista y los planes) siguen filtrando por `tipo == 'brecha'`. El informe PDF las lista (hasta 10).
- **No incluido:** documentos escaneados sin capa de texto o chunks omitidos por el tope (`chunks_omitidos`) tampoco
  son hallazgos todavía; el alcance son las limitaciones del parser de Terraform, que era lo que el backlog pedía.

**Verificación:** backend 7 tests nuevos (`test_limitation_findings.py` y el PDF) + `ruff check` limpio; frontend
`typecheck`, `lint` y `build` limpios.

## 57. CR-07: tipos de evidencia sin productor

docs/02 listaba tres tipos que nada emitía. Se decidió uno por uno, no en bloque.

- **`doc.source.info` — se implementa.** docs/05 §2.3 E6 pide marcar como analizado el documento aunque ninguna
  sección dé afirmaciones; hasta ahora un documento revisado sin hallazgos era indistinguible de uno nunca
  analizado. El adaptador de documentos (v2) emite una marca por documento con `secciones`, `analizadas` (las que
  la IA contestó), `omitidas` (las que dejó el tope de secciones) y `sin_respuesta`. **No se emite si la IA no
  contestó ninguna sección**: decir "analizado" de lo que no se leyó sería inventar (la degradación sigue sin
  producir evidencia). Un documento sin texto extraíble (PDF escaneado) queda con `secciones: 0`. Se agregó al
  catálogo (tipos v3, que cambia `methodology_version`) y el informe PDF lista los documentos analizados y avisa
  si hay secciones sin analizar.
- **`tf.attr.value` — fuera de alcance.** El adaptador emite tipos específicos por tema (cifrado, backup,
  exposición…) y los atributos no resueltos van en `tf.expression.unresolved`; un volcado genérico de atributos
  no lo consume ningún criterio. Se declaró en docs/02 como no emitido.
- **`log.event` — fuera de alcance.** Los eventos viven en la tabla `events` y las evaluaciones consumen sus
  ventanas y patrones (docs/08 §3); duplicarlos como evidencia crearía una segunda fuente de verdad (misma razón
  que OP-17 en docs/12).
- **Consecuencia:** ya no hay tipos documentados sin productor ni sin decisión.

**Verificación:** backend 7 tests nuevos (marca con y sin afirmaciones, sin marca si la IA no contesta, conteo
parcial, tope, documento vacío, informe PDF) + `ruff check` limpio.

## 58. `ruff format` y la evaluación activa que termina

- **`ruff format`:** el código solo se había pasado por `ruff check`; `ruff format --check` fallaba en 30 archivos
  (los registros anteriores que decían "ruff limpio" se referían a `check`). Se sospechó que era la diferencia de
  versión (el flake trae 0.16.8; el lockfile pide 0.16.9). No lo era: se ejecutó el binario 0.16.9 del
  entorno virtual (en NixOS, vía el cargador de glibc de la tienda de Nix) y daba el mismo resultado. Se formateó
  todo el backend y **0.16.8 y 0.16.9 coinciden** en el código ya formateado, así que no hace falta fijar el flake.
  Convención desde ahora: `ruff format app tests` antes de confirmar, y `ruff format --check` + `ruff check`
  deben pasar.
- **Evaluación en curso que termina (UI):** al elegir en el historial una evaluación que aún corría, la UI cargaba
  el detalle del *historial* (sin puntajes) y nada lo volvía a pedir al terminar el job; los criterios sí
  aparecían porque se piden aparte. Ahora, mientras la evaluación activa está `pendiente`/`en_progreso`, `App`
  la consulta cada 3 s y, al pasar a un estado terminal, recarga todo (resumen, criterios, hallazgos, planes) y
  refresca el historial. Elegir una evaluación del historial pide además su detalle actual en vez de usar el
  guardado en la lista. No hay pruebas automáticas de frontend en el proyecto (no hay test runner); se verificó con
  `typecheck`, `lint` y `build`.

## 59. Revisión del estado: lógica de puntaje, mantenibilidad, documentación y demo

Una revisión completa de código, documentación y lógica de negocio (2026-10-02) encontró lo siguiente; esta
sección registra lo que se cambió.

**Lógica de puntaje (cambia resultados visibles):**

- **Tier "no estimable" (T3) era inalcanzable.** `tier.estimate_tier` contaba como "presente" cualquier
  indicador con resultado, y todo criterio tiene siempre uno (aunque sea `evidencia_insuficiente`). Ahora un
  indicador cuenta solo si dio puntaje (`evaluado`/`no_implementado`). Ejemplo: solo Terraform, sin
  documentos → antes "Tier 1 (Partial), provisional"; ahora "No estimable".
- **Cobertura global** pasa a ser la fórmula de docs/01 §7 sobre todos los criterios (aplicables con puntaje /
  aplicables). Antes era el promedio de las seis coberturas por función: en el fixture `gaps`, 11,1 % en vez
  de 17,4 %. La marca *provisional* del global sale de este número.
- **CRI-RS-01 no podía encontrar un plan de respuesta en documentos.** La regla busca `proceso` con
  "respuesta"/"escalamiento", y el prompt de extracción solo ofrecía `riesgos|recuperacion|revision|analisis
  incidentes|otro`. Con documentos, RS-01 quedaba en 50 como máximo, y RS-01 ≥ 75 es requisito de Tier 3.
  El vocabulario ofrece ahora `respuesta` (prompt **`extract_v2`**), y un test comprueba que cada regla que
  filtra por `proceso` es alcanzable desde el vocabulario.
- **U2** solo acepta como evidencia citada los ids que se le mostraron para ese criterio (antes, cualquier id
  de la evaluación).
- Los golden de pipeline se regeneraron: solo cambian Tier y cobertura.

**Mantenibilidad:**

- `core/assessment_service.py` (1.019 líneas) se dividió en `operations.py` (eventos e incidentes),
  `refresh.py` (refresco de madurez) y `comparison.py`. Queda en 528 líneas.
- `jobs.fail_linked_assessment` reemplaza tres copias de "marcar fallida la evaluación ligada".
- `surveillance/evidence.py` no lo importaba nadie (el servicio tenía su propia versión); se eliminó.
- Las vistas de evaluación y comparación pasan a `app/schemas/assessment.py`: `reports/pdf.py` ya no importa
  `app.api`.
- Frontend: se quitó `@supabase/supabase-js`, que no se usaba.

**Documentación:**

- **docs/03** reescrita donde se había separado del código: GV-04, DE-01, DE-02, RS-01, RC-01, RC-02 y RC-03.
  La matriz declara ahora que describe el código y que una regla que cambia se actualiza allí en el mismo
  commit.
- **docs/01:** §6 describe la agregación real (promedio ponderado por criterio en cada nivel, no promedio de
  promedios; ya lo decía la regla A4); §7 fija la fórmula de la cobertura global; T3 define qué es
  "evaluar" un requisito.
- **docs/04:** la estructura de carpetas era la del plan original (`ingestion/`, `adapters/logs/`,
  `tiers.yml`…); se reemplazó por la real. Se quitó una viñeta de errores duplicada.
- **README:** estado actualizado (`criteria.yml` v7, nada pendiente en docs/11), cómo probarlo y las
  comprobaciones antes de confirmar.

**Demo:**

- **Gobernar e Identificar vacíos en la UI.** El paquete "Entorno conforme" no traía documentos, y el de
  "brechas" solo una política y un manual vacío; ambos dominios son documentales, así que nunca tenían
  evidencia. Los dos paquetes traen ahora un juego de documentos (completo en uno, débil en el otro), y el
  diálogo avisa que sin la opción de IA los documentos no se leen.
- **Los logs de ejemplo empiezan de cero:** nuevo `DELETE /orgs/{id}/events` (borra eventos, patrones,
  incidentes y sus planes; 409 si hay una ingesta en curso) que los botones de ejemplo llaman antes de
  ingerir. Subir un `.jsonl` propio sigue sumándose a lo que hay. Efecto a saber: cada clic en un log de
  ejemplo vuelve a contar sus patrones como nuevos, así que puede disparar el refresco automático de
  madurez (una evaluación nueva en el historial).

**Pendiente de decisión (no cambiado):**

- `DE-02` exige una ventana de eventos completa: sin eventos da `evidencia_insuficiente` aunque los documentos
  definan criterios de declaración. `RC-02`, en el caso equivalente, da 75. docs/03 describe ahora el
  comportamiento actual.
- `ID-01` compara el inventario documentado con los **tipos** de Terraform buscando el texto del tipo
  (`aws_db_instance`) en la lista de activos: un inventario en prosa ("la base de datos de clientes") no
  coincide y queda en 25. Los documentos de demo nombran los tipos para que la demo funcione.
- **"Analizado y sin hallazgos" no es determinista.** Al revisarlo con la caché real se vio que el modelo
  suele devolver afirmaciones `encontrado: false` (105 frente a 39 encontradas en 40 respuestas), y las reglas
  las convierten en 0 ("no se declara"). Si el modelo omite el tipo en vez de marcarlo, el mismo documento da
  `evidencia_insuficiente`. Hay que elegir una de las dos lecturas y aplicarla sin depender del modelo
  (`doc.source.info` permite hacerlo). `GV-04` sigue aceptando un `policy_review` solo para el 75.
- Con `extract_v2` la caché del golden set (§43) ya no aplica: la próxima corrida de `eval-ai` hace llamadas
  reales.

**Verificación:** backend 491 tests + `ruff check` y `ruff format --check` limpios; frontend `typecheck`,
`lint` y `build` limpios.

## 60. Citas verificadas, silencio documental conservador, GV-04 y DE-02

Decisiones tomadas tras la revisión de §59.

- **Citas (E8, docs/05 §2.3).** `extract_claims` comprobaba solo que la cita no estuviera vacía y luego la
  descartaba: una cita inventada ("aprobada por el Directorio en 2024") contaba igual y nadie podía verla. Ahora
  la cita tiene que aparecer en el texto enviado, con la misma normalización que el golden set
  (`app/ai/quotes.py`). Si no aparece, la afirmación se guarda con la limitación `CITA_NO_LOCALIZABLE` y, como las
  de confianza baja, no cuenta para ningún criterio; un hallazgo `limitacion` ("Cita no localizable") la muestra
  en cada criterio que pedía ese tipo. La cita se guarda en `value.cita`, lo que cambia el esquema: tipo nuevo
  **`doc.claim@2`** (v1 queda para evaluaciones anteriores), `evidence_types.yml` v4 y `criteria.yml` v8.
- **Silencio documental conservador.** Comprobado con la caché real: el modelo suele devolver
  `encontrado: false` para lo que no está, y las reglas lo convertían en 0; si omitía el tipo, el mismo documento
  daba `evidencia_insuficiente`. Ahora ambos casos dan **`evidencia_insuficiente`**, no 0, en todos los criterios
  documentales (GV-01/02/03/04, ID-01/02/03/04, RS-02, RS-03, RC-01, DE-03), con un helper común
  (`rules._common.silencio_documental`). Eso incluye "hay un documento sobre otra cosa" (p. ej. solo un proceso
  de recuperación para ID-03) y "el inventario existe pero no clasifica" (ID-02/ID-04). Razón: que un documento
  calle no prueba que la práctica falte; la organización puede no haber aportado ese documento (docs/01 §3). Un 0
  queda para la evidencia explícita de ausencia: configuración técnica o una falla observada en eventos.
  Para que no se lea como "no se miró", un hallazgo `limitacion` ("Ningún documento analizado lo declara") lista
  los documentos analizados (`doc.source.info`) en cada criterio así. Efecto esperable: menos criterios con
  puntaje, cobertura más baja y Tier "no estimable" más a menudo cuando los documentos no cubren GV/ID.
- **GV-04.** `policy_review` solo (la política declara su frecuencia de revisión) pasa de 75 a **50**: es revisar
  un documento, no la estrategia ni el desempeño (GV.OV), y ese mismo claim ya da a GV-01 su tramo de revisión.
  El 75 exige un proceso de revisión; el 100, además, métricas o ajustes. Sin esto, una frase de la política
  cubría dos de los siete requisitos de Tier 3.
- **DE-02 como RC-02.** Sin ventana de eventos, DE-02 evalúa lo documental: 75 con criterios de declaración, 50
  con el análisis descrito sin criterios, insuficiente sin nada. Antes daba insuficiente aunque los documentos
  definieran los criterios.
- **docs/03, 01, 02 y 05** describen todo lo anterior.

**Pendiente:** con `extract_v2` y la verificación de citas, el golden set (§43) debe volver a correrse contra el
modelo real (cuesta dinero; no se hizo).

**Verificación:** backend 501 tests (nuevos en `test_conservative_documents.py` y `test_ai_extraction.py`; se
actualizaron los que fijaban el 0 por silencio) + `ruff check` y `ruff format --check` limpios. Los golden de
pipeline solo cambian el texto de una explicación de DE-02.

## 61. Citas tolerantes a formato y la evaluación nueva pasa a ser la activa

- **Comparación de citas (E8).** `quotes.normalize` ahora deja solo letras y dígitos (minúsculas, sin acentos),
  separados por un espacio. Antes solo colapsaba espacios: una viñeta, un `**` de markdown, comillas rizadas o un
  guion distinto bastaban para descartar una cita fiel como "no localizable", y la afirmación dejaba de puntuar
  por formato. Las palabras distintas o en otro orden siguen fallando, así que una cita inventada no pasa. La
  misma función usa el golden set. Tests nuevos en `tests/test_quotes.py`.
- **Evaluación nueva = activa al aceptarse el job.** El sondeo de la evaluación activa (§58) ya recargaba
  puntajes, hallazgos y planes al terminar, pero una evaluación nueva solo pasaba a ser la activa cuando el
  sondeo del modal acababa: si el modal se cerraba a mitad, quedaba en el historial y había que elegirla a mano.
  Ahora `App.handleAccepted` obtiene la evaluación apenas la API acepta el job (202), la activa y cambia al
  resumen; el sondeo existente la recarga al terminar, esté o no abierto el modal. Efecto: al lanzar una
  evaluación se deja de ver la que se miraba antes (se ve vacía hasta que termina).

**Verificación:** backend 505 tests; `tsc --noEmit` del frontend limpio. El cambio de UI no se probó en el
navegador.


## 62. Cuatro correcciones tras una revisión de bugs

- **Clave de correlación única por organización.** `incidents.correlation_key` era única global, pero la clave
  sale de los eventos (recurso + hora): dos organizaciones que ingerían el mismo log (p. ej. `demo` y `smoke`
  con el log de ejemplo) chocaban y la segunda ingesta fallaba con `IntegrityError`. Ahora la unicidad es
  `(org_id, correlation_key)` (migración `b7e2f4c19d55`). Una BD SQLite de dev creada antes conserva la
  restricción vieja: hay que recrearla.
- **PR-03 con puerto sin resolver.** `from_port = var.ssh_port` con un CIDR abierto lanzaba `TypeError` y
  tumbaba la evaluación. Ya no falla. Primero se dejó en 100 con la limitación; se corrigió después a
  `evidencia_insuficiente`: abierto a Internet en un puerto desconocido no permite afirmar ni 25 ni 100
  (docs/03 actualizado).
- **La exclusión por contradicción es por criterio.** La afirmación contradicha se quitaba de toda la
  evaluación: una `backup_policy` cuya retención contradecía a Terraform (PR-02) dejaba además a RC-02 y RC-01
  sin evidencia, y dos frecuencias de revisión distintas (GV-01) silenciaban GV-04, sin nota en esos
  criterios. Ahora solo deja de contar para el criterio de la contradicción (docs/02 §5 actualizado). El
  efecto sobre el propio criterio (§41) no cambia.
- **ID-03 por valor.** `_es_de_riesgos` miraba si las claves `registro_riesgos`/`priorizacion` existían; como
  el prompt las pide en todo `process_defined`, un proceso de recuperación con ambas en null contaba como
  proceso de riesgos (ID-03 = 75, requisito de Tier 2). Ahora mira el valor.

**Verificación:** backend 511 tests; migración probada ida y vuelta en SQLite, no en Postgres.

## 63. Lógica de negocio: tres correcciones (`criteria.yml` v9)

De la lista de inconsistencias de la revisión se corrigió solo lo que contradecía a los propios documentos:

- **Todo 0 sale como `no_implementado`.** docs/01 §3 define ese estado como "evidencia explícita de ausencia →
  0", pero las reglas devolvían sus 0 como `evaluado` (solo `DE-01` usaba el estado). Consecuencia: la
  protección J2/R3 ("la IA no sube un `no_implementado`") nunca se activaba, y U2 podía subir una falla
  observada en `DE-02`, `RS-01` o `RC-02`. Ahora el motor (`engine._evaluate_one`) fija el estado para
  cualquier puntaje base 0. Los puntajes no cambian; cambian el estado y el conteo de estados (golden
  `pipeline_gaps` regenerado). Al comparar con una evaluación anterior a este cambio, esos criterios aparecen
  como modificados por el estado.
- **D3 como D2.** Un `escalation_done` anterior al `incident_declared` contaba como escalamiento a tiempo
  (delta negativo ≤ plazo). Ahora exige que sea posterior, igual que el triaje en D2 (§53).
- **`RC-03` exige destinatarios.** Leía la `notification_list` con `best_found`, así que una lista sin
  destinatarios (el caso real de §47) bastaba para el 100. Usa `best_found_with("destinatarios")`, como
  `DE-03` y `RS-03`.

**Revisado y dejado como está** (decisiones documentadas o de diseño, no errores): `GV-01` elige por confianza
(§47); una retención contradicha da 75 en `PR-02` (§41); `RC-03` acepta la lista documentada en lugar de la
comunicación observada (docs/03); `DE-02` cuenta la declaración como positivo aunque D1 abra incidente por
falta de alerta (docs/03 vs docs/08 §5); `DE-01` acepta cualquier `destino` como centralización (docs/03); el
Tier usa el puntaje final, con ajuste de IA incluido.

**Verificación:** backend 514 tests.

## 64. Lógica de negocio, segunda pasada: lo que no tenía sentido (`criteria.yml` v10)

Revisión por sentido, no por coincidencia con los documentos. Cambia decisiones anteriores (§41, CR-05):

- **Incumplir la política de respaldos da 50, no 75.** §41 excluía toda afirmación contradicha. Eso es
  correcto cuando el documento afirma un hecho falso, pero una retención documentada es un requisito: con
  política de 30 días y 14 configurados la organización incumple su propia política, que es justo el tramo de
  50 de `PR-02`. Al excluirla puntuaba 75, igual que quien no tiene política, y el tramo de 50 era
  inalcanzable. Ahora esa contradicción no excluye nada: la regla puntúa 50, la política se cita y el hallazgo
  se mantiene. Las demás contradicciones (respaldos deshabilitados, base pública, documento vs documento)
  siguen excluyendo.
- **`RC-03`: el 100 exige comunicación observada.** Una lista de notificación documentada bastaba para el 100
  mientras D5 abría un incidente por esa misma comunicación faltante. La evidencia operativa no sale de
  Terraform ni de Ansible sino de los eventos (`recovery_communicated`), que son la misma fuente de la que
  sale `restore_verified`: `RC-03` ya exigía una ventana de eventos para puntuar, así que el 100 sigue siendo
  alcanzable. Con lista y sin comunicación observada: 75, y la lista se cita.
- **`DE-01`: centralización = multirregión.** Se aceptaba cualquier `destino`, pero el bucket del trail es
  obligatorio en `aws_cloudtrail`: la condición era siempre verdadera.
- **`PR-03` con CIDR sin resolver.** El adaptador omitía la regla y el grupo quedaba en 100. Ahora la emite
  con `cidr: unknown` (adaptador v5) y, en un puerto administrativo y sin otra exposición confirmada, el
  criterio es `evidencia_insuficiente`.
- **Etiqueta.** `no_implementado` se muestra como "Ausente o fallido": desde §63 incluye fallas observadas
  (un ejercicio de restauración fallido), y "No implementado" no las describía.

**Se mantiene** que `GV-01` elija por confianza (§47): elegir la afirmación más favorable daría un puntaje
mayor del que es realista; la confianza es el criterio conservador.

**Verificación:** backend 518 tests; `tsc` y `eslint` del frontend limpios. La etiqueta no se probó en el
navegador.

## 65. Resto de la revisión de bugs (`criteria.yml` v11, Terraform v6, Ansible v3)

**Pisos de las reglas técnicas.** La severidad de un hallazgo sale del puntaje (alta < 25). `PR-01/02/03/04`
no bajaban de 25, así que SSH abierto a Internet o una base sin cifrar ni respaldos eran siempre severidad
media, y un solo flag de S3 en `false` (0 en `PR-05`) era alta. Se bajaron los pisos en vez de mover las
bandas: 0 cuando la ausencia es total (ningún recurso cifra, ninguna base tiene backups, administración
expuesta a Internet, las dos directivas de SSH en `yes`), 25 cuando es parcial. En el entorno con brechas de
la demo `PR-01`, `PR-02` y `PR-03` pasan de 25 a 0. Como son `no_implementado` (§63), la IA no los sube.

**Reglas y adaptadores:**

- `ID-01` contaba como activos los recursos que solo configuran un bucket (`aws_s3_bucket_versioning`…): un
  inventario completo de la demo conforme daba 50 (4/7).
- Ansible: `mode: 0644` sin comillas llega de YAML como el entero 420 y se guardaba como "420", que leído como
  octal es escritura para el grupo: `PR-04` caía a 25. `0600` se ignoraba. Ahora el modo se guarda en octal.
- `PR-04` leía `regexp` además de `line`: `regexp: '(yes|no)'` con `line: '... yes'` daba 100.
- `PR-05` ignoraba un bucket sin bloque si otro lo tenía (100). Ahora es `evidencia_insuficiente`.
- `PR-02`: la retención de la política ignoraba la unidad ("1 año" = 1 día).
- Terraform: las referencias a un bucket solo se resolvían dentro del mismo `.tf`; un bloque en otro archivo
  se informaba como "bucket sin bloque declarado".

**Vigilancia:**

- `auth_failures_burst` exigía que todos los fallos del actor cupieran en la ventana: un fallo suelto una hora
  después ocultaba la ráfaga. Ahora es una ventana deslizante.
- **Los patrones se detectan sobre todos los eventos guardados del org+scope**, no por archivo. Antes dos logs
  dejaban dos filas del mismo patrón y cada regla tomaba la primera; además la clave de deduplicación no
  incluía `resultado`, así que un ejercicio `ok` cargado tras uno `fail` a la misma hora se descartaba. Ahora
  hay una fila por patrón y por scope, que se reemplaza en cada ingesta; entre dos eventos con la misma hora
  cuenta como último el que se ingirió después. Un disparador solo toca su incidente si el archivo aporta
  alguno de sus eventos, y regenerar el plan conserva su estado de seguimiento.

**Plataforma:**

- `worker-core`/`worker-logs` solo toman jobs `pendiente`. Un job dado por perdido mientras hacía cola y luego
  reintentado dejaba dos mensajes para la misma evaluación y los resultados quedaban duplicados (46 filas para
  23 criterios).
- `context` inválido en `POST /assessments` o `/reevaluate` da 422 antes de crear nada (antes 500 y una
  evaluación `pendiente` para siempre).

**No se tocó:** validar afirmación por afirmación en la extracción (en las respuestas reales en caché no hay
ningún caso que lo necesite).

**Verificación:** backend 545 tests. Regresiones en `tests/test_review_fixes.py`.

## 66. Paquetes de ejemplo: tres momentos en vez de dos extremos

Con los pisos de §65 los dos paquetes de la UI quedaban en los extremos (global 3,75 con casi todo en 0, y 97,4
sin ningún hallazgo): no se veía ningún tramo intermedio ni casi nada de lo corregido en §62–§65.

- **Entorno con brechas** (suavizado): una segunda base cifrada y con 3 días de retención. `PR-01` y `PR-02`
  pasan a 25 (parcial); siguen en 0 `PR-03` (SSH/RDP abiertos) y `PR-05` (base pública). Severidades alta y
  media.
- **Entorno en mejora** (nuevo, `demo/mid`): Terraform en dos archivos (el bloqueo del bucket referencia un
  recurso de otro archivo), una base sin cifrar (25), un bucket sin bloque (`evidencia_insuficiente`), un CIDR
  como variable en un puerto no administrativo (hallazgo `limitacion`), CloudTrail de una región (75), SSH sin
  root pero con contraseña (25) y `mode: 0644` sin comillas. Los documentos están escritos para dar tramos de
  75 y 50 (política aprobada con revisión vencida, roles sin autoridad, proceso de riesgos sin registro,
  procedimiento de recuperación sin criterios de activación) y una retención de 30 días que los 14 configurados
  incumplen (`PR-02` = 50 más contradicción, §64).
- **Entorno conforme** (suavizado): un bucket de logs con el bloqueo público incompleto. `PR-05` = 50, un
  hallazgo de severidad baja.
- **Log "Respuesta parcial"** (nuevo): alerta y triaje a tiempo, escalamiento a los 45 minutos y restauración
  verificada sin comunicar. Abre D3 y D5.

Global técnico sin IA: 16 → 68 → 94. `tests/test_demo_bundles.py` fija los puntajes técnicos de cada paquete y
los disparadores de cada log. Los fixtures de `backend/tests/fixtures` no cambian: los paquetes de la UI ya no
son copias suyas.

**Verificación:** backend 554 tests; `tsc`, `eslint` y `vite build` del frontend limpios. **No verificado:** los
puntajes documentales de los tres paquetes (dependen de una corrida real con IA) ni la UI en el navegador.

## 67. Comparar: qué cambió y por qué

La vista decía cuánto cambió el puntaje, no qué cambió ni por qué, y uno de sus números estaba mal.

- **Puntaje por función.** Se calculaba en el navegador como promedio simple de los criterios; el real es
  ponderado por peso, así que Comparar y el Resumen de Madurez podían mostrar valores distintos para la misma
  evaluación. Ahora usa los agregados del backend, con su cobertura.
- **Dirección del cambio (`direccion`, backend).** Pasar de `evidencia_insuficiente` a un puntaje no contaba
  como nada (flecha neutra). Ahora cada criterio es `mejora`, `retroceso`, `ahora_evaluado`,
  `dejo_de_evaluarse`, `cambio_de_estado` o `igual`: ganar o perder evidencia no se confunde con mejorar o
  empeorar.
- **El porqué.** `GET /assessments/{a}/compare/{b}` devuelve la explicación del criterio en cada evaluación;
  cada fila se despliega y las muestra lado a lado.
- **Aviso de reglas o alcance distintos** (`misma_metodologia`, `mismo_scope`), también en el PDF: tras subir la
  metodología de v8 a v11, comparar una evaluación vieja con una nueva muestra cambios que son de las reglas.
- **Cobertura y Tier** junto al puntaje global, y **hallazgos** que ya no aparecen o son nuevos
  (`hallazgos_resueltos`, `hallazgos_nuevos`).
- Solo se listan los criterios con cambio (los demás, a pedido), primero lo que empeoró; los estados usan las
  etiquetas de la UI; "Antes" es por defecto la evaluación inmediatamente anterior a la activa; la comparación
  se calcula sola y hay un botón para intercambiar; aviso si "Antes" es más reciente que "Después". Se quitó la
  tarjeta de barras del puntaje global (repetía el resumen) y el texto que mandaba a un botón "Reevaluar" que
  ya no existe.

**Verificación:** backend 557 tests (`tests/test_comparison.py`); `tsc`, `eslint` y `vite build` limpios. **No
verificado:** la pantalla en el navegador.

**PDF de la comparación.** Tenía las mismas carencias que la pantalla y solo había recibido el aviso de reglas
o alcance distintos. Ahora trae también: cobertura de evidencia junto al puntaje y el Tier; tabla de cambio por
función (puntaje ponderado y cobertura, los mismos agregados que el informe ejecutivo); hallazgos que ya no
aparecen o son nuevos; la columna "Cambio" con la dirección (Mejoró, Empeoró, Ahora se evalúa, Dejó de
evaluarse) en vez de "N/D" cuando faltaba un puntaje, ordenada con lo que empeoró primero; y una sección "Por
qué cambió cada criterio" con la explicación de antes y de después. En ambos PDF `no_implementado` se muestra
como "ausente o fallido", igual que en la UI. Revisado a la vista generando la comparación brechas → en mejora.

## 68. El núcleo de NIST en el repositorio: validación del mapeo y cobertura de implementación (AMP-04)

**El problema.** `CriterionDefinition.subcategorias` era `list[str]` sin validar y no existía ningún
catálogo de NIST contra el que contrastarlo. Una subcategoría mal escrita —o una de las que NIST
retiró en la v1.1 y nunca renumeró, como `ID.AM-06` o `PR.DS-03`— se cargaba en silencio y falseaba
el mapeo. Y la cobertura de implementación que `docs/01 §7` especifica no se calculaba en ninguna
parte: estaba en `docs/12` como AMP-04.

**El núcleo.** `methodology/csf_subcategories.yml` (`version: 1`) trae las 6 funciones, 22 categorías
y 106 subcategorías del CSF 2.0, con `total_declarado: 106` como guarda. Los huecos de numeración son
reales y el fichero lo advierte: "rellenarlos" produciría más de 106 entradas y rompería el modelo.
Los títulos son traducción propia resumida; lo normativo es el id.

`CsfCoreCatalog` (`app/methodology/schemas.py`) valida cuatro invariantes al cargar: cada categoría
cuelga de su función, cada subcategoría de su categoría, el sufijo es `-NN` y no hay duplicados ni
descuadre con `total_declarado`.

**La validación que faltaba.** `loader._validate_cross_references` recibe ahora el núcleo y comprueba,
para cada criterio: que la categoría exista, que pertenezca a la función que el criterio declara, que
la subcategoría exista y que su categoría padre esté listada en `categorias`. Las cinco formas de
error fallan el arranque. Las 23 criterios actuales pasan sin cambios: el mapeo estaba bien escrito,
solo no estaba comprobado.

**La métrica.** `app/methodology/coverage.py`, deliberadamente fuera de `evaluation/aggregation.py`.
Son dos coberturas que `docs/01 §7` obliga a no mezclar: la de evidencia es por evaluación y decide
la marca `provisional`; la de implementación es metadato del producto, función pura de `criteria.yml`
+ el núcleo, y no toca ningún puntaje. Tenerlas en el mismo módulo invitaba a alimentar una con la
otra. `Methodology.cobertura_implementacion()` la expone, igual que `tipos_afirmacion_requeridos()`.

Devuelve subcategorías cubiertas, ratio, desglose por función, el mapa subcategoría → criterios y
`categorias_sin_criterio`, que hoy es `['GV.OC', 'GV.SC', 'ID.IM', 'PR.AT', 'RS.MI']`. Esa lista es
el indicador legible de lo que falta por cubrir, calculado por el sistema y no a mano.

**Estado actual: 37 de 106 subcategorías (34,9 %)** — GV 8/31, ID 6/21, PR 6/22, DE 5/11, RS 7/13,
RC 5/8 — y 17 de 22 categorías.

**API.** `GET /methodology` añade `nucleo_csf_version` y `cobertura_implementacion` como claves
hermanas, nunca anidadas en `criterios`. `methodology_version` incorpora `csf=N`, así que las
evaluaciones nuevas registran una versión distinta de las anteriores.

**Verificación:** 570 tests (`tests/test_csf_core_catalog.py` nuevo, con los conteos por categoría y
la guarda de ids retirados; seis casos negativos nuevos en `tests/test_methodology_loader.py`).
`ruff check` y `ruff format` limpios. Endpoint comprobado a mano. (La pantalla llegó en el §71.) **Preexistente, ajeno a este cambio:**
`test_uploads.py::test_windows_separator_is_rejected` y los dos
`test_golden.py::test_ansible_adapter_evidence_matches_golden` fallan en Windows también sin estos
cambios (comprobado sobre el árbol limpio).

## 69. Goldens portables: rutas absolutas como `<REPO>/...`

**El problema.** Los goldens de evidencia de Ansible llevaban la ruta absoluta del checkout
canónico (`/home/jando/.../hardening.yml`) en `value.archivo`. `normalize_evidence` ya reducía
`locator.file` al nombre base, pero no tocaba `value` — y su docstring prometía normalizar "rutas
absolutas" sin hacerlo. Resultado: esos dos tests solo pasaban en una máquina y en una ruta, y en
cualquier otro checkout fallaban haciéndose pasar por regresión (así se diagnosticó el aviso de
Windows del §68: feat real verificado, fallo ambiental).

**El fix.** `tests/golden_utils.py::_portable_paths`: reescribe recursivamente las cadenas que
empiezan por la raíz del repo (calculada desde `__file__`, no hardcodeada) como
`<REPO>/...` con separador `/`. Solo toca rutas bajo el repo; regex y valores de configuración
quedan intactos. Se aplica en `normalize_evidence` antes de ordenar, así el orden también es
independiente de la máquina. Goldens regenerados: el diff son exactamente 6 líneas de rutas, nada más.

**Verificación:** suite completa **573 tests** + `ruff check` y `ruff format` limpios; `test_golden.py`
pasa desde un checkout en otra ruta (`/tmp/...`), cosa que antes fallaba.

## 70. Oleada 0: declarar lo que las reglas ya evidencian (`criteria.yml` v12)

**Por qué es gratis.** `aggregation.aggregate_by_subcategoria` (`aggregation.py:50`) no tiene ni una
llamada en todo el repo: los agregados por subcategoría nunca se calculan, ni se persisten, ni están
en los goldens. Añadir una subcategoría a un criterio existente mueve exactamente dos cosas: la
salida de `GET /methodology` y el numerador de la cobertura de implementación. Cero reglas, cero
tests, cero goldens.

**Qué se declaró, y qué lo sostiene.** El campo `subcategorias` no es una etiqueta temática: tiene
que poder defenderse frente al ancla que lo evidencia.

| Criterio | Subcategoría | Lo que la sostiene |
|---|---|---|
| `CRI-GV-04` | `GV.OV-02` | el ancla 100 exige `contenido.ajustes` (`gv04_strategy_review.py:52`), que es literalmente "la estrategia se revisa **y ajusta**" |
| `CRI-ID-03` | `ID.RA-03`, `ID.RA-06` | `registro_riesgos` (amenazas identificadas y registradas) y `priorizacion` (respuestas al riesgo priorizadas) son las dos claves del ancla 100 (`id03_risk_assessment.py:60-62`) |
| `CRI-RS-02` | `RS.AN-06` | misma base de evidencia que el ya declarado `RS.AN-07`: el filtro de afirmación admite "evidencia"/"forense" y el ancla 100 habla de conservación (`rs02_incident_analysis.py:23-29,55-63`) |

**Tres que se quedaron fuera.** Esta oleada se había anunciado como siete subcategorías. Al
contrastar cada una con su regla, `ID.RA-04`, `DE.AE-03` y `RS.MA-05` no están evidenciadas por
nada: el motivo y el coste de hacerlas honestas quedan en `docs/12 §5`. Preferimos 41 defendibles
que 44 opinables, porque la cobertura se reporta como métrica del producto.

**Estado: 41 de 106 subcategorías (38,7 %)** — GV 9/31, ID 8/21, PR 6/22, DE 5/11, RS 8/13, RC 5/8.
Las categorías siguen en 17/22; `categorias_sin_criterio` no se mueve hasta la Oleada A.

**Un test sí observaba el mapeo.** `test_current_catalog_maps_cleanly_onto_nist` fijaba
`len(declaradas) == 37`, así que rompía con la primera subcategoría añadida. Ahora compara contra
`cobertura_implementacion().subcategorias_cubiertas`: el conteo vive en un solo sitio
(`test_csf_core_catalog.py` ya usaba invariantes) y no vuelve a romper en cada oleada.

**Verificación:** 572 tests y `ruff check`/`format` limpios; conteo comprobado contra
`GET /methodology`. Sigue fallando solo `test_uploads.py::test_windows_separator_is_rejected`,
preexistente y específico de Windows (los dos de Ansible los arregló el §69).

## 71. La cobertura del catálogo, en pantalla

**Lo que faltaba.** El §68 dejó la cobertura de implementación calculada y servida, pero invisible:
`getMethodology` existía en `lib/api.ts` **sin un solo consumidor**, y `MethodologyCatalog` ni
siquiera declaraba los campos nuevos. La Sección VII-C del informe afirma que se reportan dos
métricas de cobertura; se cumplía en la API y no en la herramienta.

**El 22/22 lo cuenta el sistema.** `CoberturaImplementacion` gana `categorias_cubiertas` y
`categorias_totales`. Se cuentan en `coverage.py` y no en el consumidor a propósito: "22 de 22" es
*la* afirmación fuerte del catálogo y no debe salir de una resta con el 22 escrito a mano en la UI.
`GET /methodology` los expone junto a los demás.

**El panel.** `CatalogCoverage` en `MaturityDashboard.tsx`, debajo de la matriz: el ratio global, el
desglose por función (cubiertas/totales con barra, reusando `FUNCTION_ACCENTS`) y las categorías sin
ningún criterio como chips. Cuando esa lista se vacíe, el panel lo dice en positivo: "Las 22
categorías del marco están representadas". La petición se hace una vez (`useEffect`, sin dependencia
de la evaluación, porque es metadato constante de la versión de metodología) y **si falla, el panel
no se pinta**: es metadato y no debe tumbar la matriz.

**Las dos coberturas, separadas por nombre.** La tarjeta que decía "Cobertura Global" ahora dice
**"Cobertura de evidencia"**, con el subtítulo "criterios con evidencia suficiente en esta
evaluación". El panel nuevo se titula "Cobertura del catálogo NIST CSF 2.0" y declara en su propio
texto que describe la herramienta y no la corrida. Dos números llamados "cobertura" en la misma
pantalla era exactamente lo que `docs/01 §7` prohíbe mezclar.

**Contrato con test.** `test_methodology_exposes_implementation_coverage` fija el conjunto exacto de
claves de `cobertura_implementacion` y que son hermanas de `criterios`, nunca anidadas en él: la UI
ya depende de esa forma.

**Verificación:** 573 tests y `ruff` limpios; `npm run typecheck`, `npm run lint` y `npm run build`
limpios; `GET /methodology` comprobado contra la API corriendo (41/106, 17/22).
**Verificado en el navegador** (§74): Chrome headless por CDP contra `npm run dev`, con sesión
sembrada en `localStorage`. El panel muestra 54 %, 57 de 106, el desglose por función y
"Las 22 categorías del marco están representadas".

## 72. Oleada A (1/2): `RS.MI` e `ID.IM`, con evidencia operativa (`criteria.yml` v13)

De las cinco categorías sin ningún criterio, estas dos se cubren **sin inventar un tipo de
afirmación**: la evidencia que necesitan ya la produce el sistema.

**`CRI-RS-04` — Contención y erradicación (RS.MI).** El patrón `containment_done` se agregaba desde
el §53 y ningún criterio lo consumía ("solo contexto"). Ahora es el eje de un criterio mixto, con la
misma regla de justicia que `CRI-RS-01`: un `incident_declared` en ventana completa sin contención
es un 0 por falla de mitigación, y sin ventana completa no se concluye nada de lo operativo. El
filtro documental pide un proceso de contención/erradicación/mitigación, así que el plan de respuesta
genérico de `CRI-RS-01` no lo alimenta por accidente — hay un test que lo fija.

**`CRI-ID-05` — Mejora continua (ID.IM).** Mixto a propósito. `ID.IM-02` habla de "mejoras a partir
de pruebas y ejercicios", y declararlo con solo un documento sería creerle al texto; la regla exige
`log.pattern(restore_exercise_run)` en ventana completa para el 100. `ID.IM-04` (mantener y mejorar
los planes) se queda fuera: nada lo evidencia. No está en `_SURVEILLANCE_RULES` porque su vía
documental **no** requiere ventana, igual que `CRI-RS-02`.

**Enum de `proceso`.** `_CONTENT_FIELDS` suma `contencion` y `mejora` al enum de `process_defined`:
sin eso U1 no tiene por qué devolver esos valores y el filtro de ambas reglas nunca acertaría. No
hace falta tipo de afirmación nuevo ni tocar `evidence_types.yml`.

**Dos tests que fijaban el tamaño del catálogo.** `test_loads_expected_criteria` enumera los ids (hay
que añadirlos a mano, es el inventario) y `test_aggregation` fijaba `round(4 / 23, 4)`; ahora usa
`len(methodology.criterios)` y no vuelve a romper por una oleada.

**Goldens.** Regenerados: el diff es exactamente los dos criterios nuevos en
`evidencia_insuficiente`, sus conteos de estado y el denominador de la cobertura global
(0,3043 → 0,28 en `good`). Ningún puntaje se movió, como estaba previsto: `_weighted_aggregate`
excluye `evidencia_insuficiente` del numerador y del denominador.

**Paquetes de ejemplo.** `good` gana las secciones de contención/erradicación (tres pasos) y de
mejora continua (lecciones aprendidas con métricas trimestrales y ajustes); `mid` gana una contención
sin procedimiento escrito, que es justo el tramo de 50; `gaps` no gana nada, y queda insuficiente.
Son documentos, así que solo puntúan en la corrida con IA.

**Estado: 46 de 106 subcategorías (43,4 %) y 19 de 22 categorías.** Quedan `GV.OC`, `GV.SC` y
`PR.AT`, que son la segunda mitad de la oleada.

**Verificación:** 588 tests (14 nuevos en `test_surveillance_criteria.py`), `ruff check`/`format`
limpios, cobertura comprobada con el loader. Sigue fallando solo el `test_uploads` de Windows.

## 73. Oleada A (2/2): las 22 categorías del CSF tienen criterio (`criteria.yml` v14)

Cierra `GV.OC`, `GV.SC` y `PR.AT`, las tres categorías que seguían sin ningún criterio. Las tres son
documentales y cada una estrena un tipo de afirmación.

**`CRI-GV-05` — Contexto organizacional (GV.OC).** `org_context` trae **un campo por subcategoría**:
`mision` → GV.OC-01, `partes_interesadas` → GV.OC-02, `requisitos_legales` → GV.OC-03,
`servicios_criticos` → GV.OC-04, `dependencias` → GV.OC-05. El puntaje es proporcional a cuántos de
los cinco se declaran (5 → 100, 3-4 → 75, 1-2 → 50) y la explicación **nombra los que faltan** con
su id. Esa lista es el valor del criterio; un número suelto sobre "contexto" no diría nada.

**`CRI-GV-06` — Cadena de suministro (GV.SC).** `supplier_program` exige `programa` para puntuar
(mencionar proveedores no es tener un programa: sin él es silencio documental, no 0) y suma `roles`
(GV.SC-02), `proveedores_priorizados` (GV.SC-04) y `requisitos_contractuales` (GV.SC-05). De las 10
subcategorías de `GV.SC` se declaran **4**: las otras seis (debida diligencia previa, monitoreo del
ciclo de vida, cierre de la relación…) no las evidencia nada. La señal técnica de procedencia de
módulos de Terraform sigue siendo AMP-07 en `docs/12 §5`.

**`CRI-PR-07` — Concienciación y formación (PR.AT).** `PR.AT` separa la formación general
(`PR.AT-01`) de la de roles especializados (`PR.AT-02`), así que la regla puntúa por separado
`frecuencia` y `roles_especializados`: con las dos, 100; con una, 75 (y la explicación dice cuál
falta); con solo el programa, 50.

**Los tres tipos declaran solo los campos que sus reglas leen.** Es la lección de CR-06 y CR-07
(§36, §57): un campo en `_CONTENT_FIELDS` que ninguna regla consume es evidencia declarada sin
consumidor. Por eso `training_program` no pide `registro` de asistencia, que no se usa en ningún
tramo.

**`CRI-ID-05` entra como indicador de Tier 4** (`settings.yml` v3, umbral 75). El nivel "Adaptativo"
se define por la mejora continua informada por riesgo, así que era el indicador que faltaba.
Comprobado antes de añadirlo: no mueve los goldens, porque su lista de `faltantes` solo llega a los
indicadores de Tier 2.

**`CRI-GV-05` no entra en el cruce de privacidad.** `GV.OC-03` nombra los requisitos de privacidad,
pero eso es **Govern-P** del PF 1.0, y el alcance declarado del cruce (docs/00 §6, docs/03 §7, y
§VII-E del informe) son Identify-P, Protect-P y los eventos. Añadirlo a `PRIVACY_CRITERIA` ensancharía
un límite de alcance declarado; queda como AMP-08 en `docs/12 §5` para decidirlo como lo que es.

**Golden set de IA.** `tests/golden_ai/documents/gobierno-y-proveedores.md` con los tres tipos
anotados en `expected.json`: así TS-02 cubre también las afirmaciones nuevas. **No verificado:** la
corrida real (`python -m app.main eval-ai`) cuesta dinero y necesita `DEEPSEEK_API_KEY`; la anotación
es la especificación de lo que U1 debe encontrar, no una medición.

**Paquetes de ejemplo.** `good` gana `gobierno-y-proveedores.md` con los cinco datos de contexto, el
programa de proveedores completo y el programa de formación con roles; `mid` gana una versión parcial
(contexto a medias, proveedores sin programa, formación anual sin roles); `gaps` gana una inducción
informal que **no** es un programa, que es justo el caso que debe dar insuficiente y no 0.

**Estado: 57 de 106 subcategorías (53,8 %) y 22 de 22 categorías** — GV 18/31, ID 11/21, PR 8/22,
DE 5/11, RS 10/13, RC 5/8. `categorias_sin_criterio` quedó **vacía**, que era el indicador que el
§68 dejó puesto para saber cuándo estaba cerrado.

**Verificación:** 606 tests (18 nuevos en `test_wave_a_documental_criteria.py`), `ruff
check`/`format` limpios, `npm run typecheck`/`lint`/`build` limpios, goldens regenerados sin que se
mueva un solo puntaje (el diff son los tres criterios nuevos en `evidencia_insuficiente` y los
denominadores de cobertura). Sigue fallando solo el `test_uploads` de Windows.

## 74. Comparar dos catálogos distintos: lo que no cambió no debe parecer un cambio

**Cómo salió.** Revisando las pantallas con el navegador (Chrome headless por CDP, porque la
extensión no estaba disponible), con dos evaluaciones de la misma infraestructura: una del catálogo
de 23 criterios y otra del de 28.

**El defecto.** Los cinco criterios nuevos aparecían en Comparar como **"Cambió de estado — → —"**.
Dos guiones y una etiqueta que afirma un cambio que no ocurrió: no es que el criterio pasara a otro
estado, es que **no existía** en la metodología anterior. El aviso general de "versiones distintas de
las reglas" ya estaba, pero cada fila seguía contando otra cosa. Y con el catálogo creciendo por
oleadas, este caso pasa a ser la norma y no la excepción.

**El arreglo.** `CriterionDiff.direccion` gana `criterio_nuevo` y `criterio_retirado`, que se
deciden **antes** que cualquier comparación de puntajes, porque sobre un `None` comparar no dice
nada. La pantalla y el PDF los etiquetan como "Nuevo en el catálogo" / "Ya no está en el catálogo" y
los ordenan al final, después de los cambios reales del entorno.

**El mismo error, un nivel más arriba.** La tarjeta "Cobertura de evidencia" mostraba
`30 % → 25 %, -5 pts` en rojo. No empeoró nada: la cobertura se mide sobre el catálogo de cada
evaluación y el denominador creció. Ahora, cuando la metodología difiere, la tarjeta lleva debajo
que esa diferencia no es comparable, y el PDF de comparación dice lo mismo (§67: el PDF no puede
diferir de la pantalla).

**Lo que no se tocó.** La comparación ya hacía la unión de los ids de las dos evaluaciones y marcaba
`misma_metodologia`, así que no había que cambiar ni el modelo ni la consulta: el fallo estaba solo
en cómo se nombraba el resultado.

**Verificación:** 608 tests (dos nuevos en `test_comparison.py`: el mapeo de dirección y una
comparación real a la que se le quita el resultado de `CRI-RS-04` para simular el catálogo
anterior), `ruff` limpio, `typecheck`/`lint` limpios, y las dos pantallas y el PDF comprobados en
una corrida real.

## 75. Oleada B (1/4): `DE.AE-03` — la correlación multi-fuente dejó de ser una promesa

**El defecto, que estaba a la vista.** `core/operations.py:197` calculaba los orígenes de cada
patrón detectado y los guardaba en `log_patterns.fuentes`. Al construir la evidencia,
`assessment_service.py:128` los colapsaba a un único `source_id` — porque un `source_id` solo puede
llevar uno — y la lista se perdía. El dato existía, se calculaba y se tiraba: ninguna regla podía
preguntar "¿esto lo vieron dos sistemas distintos o uno solo?".

Eso es exactamente `DE.AE-03`, "la información se correlaciona a partir de múltiples fuentes", que la
Oleada 0 dejó fuera por ese motivo (`docs/12 §5`, SUB-02).

**Qué se cambió.** `log.pattern` pasa a **v2** con `fuentes: [string]`; la v1 queda publicada
intacta, como se hizo con `doc.claim`. Los ocho criterios que declaraban `log.pattern@1` pasan a
`@2`, igual que en su día migraron todos a `doc.claim@2`.

**El ancla, y por qué ahí.** `CRI-DE-02` declara `DE.AE-03` y su 100 exige que el patrón positivo
venga de **dos orígenes distintos**. Con uno solo baja a 75 y la explicación lo dice con nombre
propio ("solo siem-corp"). Un sistema que alerta es detección; dos que ven lo mismo es correlación.

**Lista vacía ≠ un origen.** Un patrón de `log.pattern@1`, o uno cuyos eventos no declararon
`fuente`, llega con la lista vacía. Eso **no se penaliza**: el criterio se queda en 75 con la razón
explícita. Misma lógica que el silencio documental (§60) — que el dato falte no prueba que la
práctica falte.

**La demo tuvo que ganar un segundo sistema.** Ningún evento declaraba `fuente`, así que todo patrón
tenía un solo origen y el escenario conforme se habría quedado en 75 sin que ningún test lo notara
(los puntajes documentales no están fijados: `test_demo_bundles` solo fija los técnicos).
`flujo-correcto-demo.jsonl` ahora tiene el SIEM y un EDR levantando la misma alerta (`e1-006` y
`e1-006b`), con el segundo **después** del triaje para no mover `alerta.desde` y con ello el
disparador D2. Los otros dos logs quedan con un solo origen a propósito.

Conviene no confundirlos: en la UI el **paquete de evidencia** y el **log de eventos** son dos
botones independientes (`frontend/src/data/demo.ts`), así que "el escenario conforme" es el paquete
`good` más el log *Flujo correcto*, no un par fijo.

**Verificación:** 611 tests (tres nuevos de DE-02 y dos de `test_event_source.py`, que comprueban
que la lista llega al valor de la evidencia y no solo al `source_id`); goldens sin un solo cambio —
el pipeline golden es Terraform + Ansible, sin eventos. `ruff` limpio. Sigue fallando solo
`test_uploads.py::test_windows_separator_is_rejected`, preexistente y de Windows.

## 76. Oleada B (2/4): la deuda de la Oleada 0, cerrada (`criteria.yml` v16)

**Las tres que faltaban.** `docs/12 §5` guardaba `ID.RA-04`, `DE.AE-03` y `RS.MA-05` con el coste de
hacerlas honestas, para no re-razonarlas. `DE.AE-03` se cerró en §75; aquí van las otras dos, más
`ID.IM-04`, que la Oleada A había dejado fuera por el mismo motivo (ningún campo la evidenciaba).

| Subcategoría | Campo nuevo | Dónde decide |
|---|---|---|
| `ID.RA-04` | `impactos`, `probabilidades` | ancla del 100 de `CRI-ID-03`: registro y priorización ya no bastan |
| `RS.MA-05` | `criterios_recuperacion` | parte de "plan completo" en `CRI-RS-01` |
| `ID.IM-04` | `planes_actualizados` | condición del 100 de `CRI-ID-05`, junto al ejercicio observado |

**Una desviación del plan escrito, a propósito.** `docs/12 SUB-03` proponía que `CRI-RS-01` leyera
`criterios_activacion`, que ya existe. No se hizo: en un proceso de **respuesta**, ese campo son los
criterios para *activar la respuesta*, no para pasar a la recuperación, que es lo que dice
`RS.MA-05`. Y es además el campo que `CRI-RC-01` lee del proceso de recuperación en su ancla del 100
(`rc01_recovery_procedure.py:59-63`) — el choque que el propio documento advertía. Un campo propio
cuesta una línea más de prompt y deja las dos subcategorías separadas.

**`CRI-ID-03` pasa de tres anclas a cinco.** Cubre cinco subcategorías y no las distinguía: un
proceso con pasos pero sin registro ni priorización evidencia `ID.RA-01` y nada más, así que baja a
50 (antes 75), y el caso genérico a 25 (antes 50). Es un ajuste a la baja deliberado: con `ID.RA-04`
declarada, el tramo alto tiene que costar más.

**El prompt tenía un agujero de reproducibilidad.** `PROMPT_VERSION` nombra el archivo del *system
prompt*, pero el prompt efectivo lleva además los campos de `_CONTENT_FIELDS`. El salto v1→v2 se hizo
precisamente por un cambio de campos (`process_defined.proceso` ganó `respuesta`) sin tocar el
archivo. La Oleada A añadió **tres tipos de afirmación y una opción de enum sin bumpear**, así que
dos corridas con prompts distintos quedaron anotadas como la misma en el manifiesto de
`core/reproducibility.py`. Ahora es `extract_v3` y el comentario del módulo dice que un cambio en
`_CONTENT_FIELDS` obliga a bumpear.

**`"false"` es verdadero en Python.** Con los campos nuevos, las reglas deciden puntaje leyendo
verdad simple (`contenido.get("impactos")`). Un modelo que responda `"false"` o `"parcialmente, ver
anexo"` donde se pide un booleano producía un **falso positivo silencioso** justo en el tramo alto.
`_sanitize_content` normaliza ahora los booleanos declarados (`_BOOL_FIELDS`) y descarta lo que no
sea interpretable, que queda en `_descartados` como el resto de E5. Es la defensa que hace creíble
todo lo que viene después, donde casi todo campo nuevo es booleano.

**Las fixtures ya decían dos de las tres cosas.** `good/gestion-de-riesgos.md` ya dice "se estima
impacto y probabilidad" y su sección de mejora continua ya dice que los ajustes "se incorporan al
plan de respuesta y al de continuidad". Solo faltaba el traspaso a recuperación, que es una sección
nueva en `good/respuesta-incidentes.md`. `mid` se queda sin él a propósito: su `CRI-RS-01` baja de
100 a 75 en una corrida con IA, que es la diferencia que el paquete debe mostrar.

**Verificación:** 615 tests (cuatro anclas nuevas y dos del normalizador de booleanos); goldens sin
cambios (el pipeline golden no tiene `doc.claim`); `ruff` limpio. **61 de 106 subcategorías
(57,5 %)**, 22/22 categorías. `docs/12 §5` ya no tiene deuda de la Oleada 0.

## 77. Oleada B (3/4): la función Gobernar completa, 31/31 (`criteria.yml` v17)

**Por qué Gobernar y no un porcentaje.** GV estaba en 18/31 con tres categorías a medias: `GV.RM`
2/7, `GV.RR` 2/4 y `GV.SC` 4/10. Completar una función entera es una afirmación verificable ("las
siete subcategorías de la estrategia de riesgo tienen criterio") frente a un porcentaje global, que
no dice de qué. Y es la función donde el prototipo es más creíble: es toda documental, así que no
promete observación técnica que no tiene.

**Trece facetas, una por subcategoría.** No se añadió ningún criterio: los tres criterios de GV que
ya existían pasan a declarar su categoría completa, y cada subcategoría nueva entra con **su propio
campo** en el contenido de la afirmación. Un campo compartido no serviría: si `GV.SC-09` se declarara
por el mismo dato que `GV.SC-01`, serían la misma afirmación contada dos veces.

| Criterio | Categoría | Facetas nuevas |
|---|---|---|
| `CRI-GV-03` | `GV.RM` 2/7 → **7/7** | `integracion_empresarial`, `opciones_respuesta`, `lineas_comunicacion`, `metodo_estandarizado`, `oportunidades_estrategicas` |
| `CRI-GV-02` | `GV.RR` 2/4 → **4/4** | `recursos_asignados`, `practicas_rh` |
| `CRI-GV-06` | `GV.SC` 4/10 → **10/10** | `integracion_riesgo`, `debida_diligencia`, `riesgos_monitoreados`, `en_respuesta_incidentes`, `monitoreo_ciclo_vida`, `terminacion` |

**Anclas de amplitud, y por qué eran obligatorias.** Si el 100 de `CRI-GV-06` siguiera dependiendo
solo de que exista un programa, las diez subcategorías de `GV.SC` se sostendrían en una sola frase
del documento: *eso* sería inflar la cobertura. El puntaje mide ahora **cuántas de las nueve
prácticas declara el texto** (≥7 → 100, 4–6 → 75, 1–3 → 50, el programa pelado → 25), reutilizando
el patrón `_CAMPOS` que el propio criterio ya traía de la Oleada A. `CRI-GV-03` hace lo mismo con tres
de cinco facetas para el 100, y `CRI-GV-02` exige las dos: **nombrar a un CISO no es dotar a la
función**.

**El efecto es a la baja, a propósito.** Un documento que antes sacaba 100 en `CRI-GV-03` por fijar
objetivos y tolerancia ahora saca 75 si no dice cómo se calculan los riesgos ni por dónde se
comunican. Los tramos bajos también bajan un escalón (el caso genérico pasa de 50 a 25). Declarar
más subcategorías tiene que costar más evidencia; si no, la cobertura sube y el puntaje se vuelve más
fácil al mismo tiempo, que es exactamente la combinación que no se puede defender.

**`docs/03` llevaba tres criterios sin ficha.** `CRI-GV-05`, `CRI-GV-06` y `CRI-PR-07` entraron en la
Oleada A sin su ficha en la matriz, aunque la cabecera del propio documento dice que las reglas de
esa matriz **describen el código** y se actualizan en el mismo commit. La tabla decía "Govern | 6" y
había cuatro fichas. Escritas y contrastadas contra las reglas línea por línea (`gv05_org_context.py`
da 75 con tres o cuatro campos, no con cuatro; `pr07_awareness.py` da 75 también cuando hay
formación por rol sin periodicidad). Ahora hay 28 fichas para 28 criterios.

**Un solo bump de prompt.** `extract_v4`, y los dos bloques de facetas van en un commit en vez de
dos: separarlos obligaba a publicar dos versiones de prompt para un mismo cambio, o a repetir el
agujero de reproducibilidad que §76 acababa de cerrar. Se eliminó además `extract_v2.txt`, que había
quedado como copia huérfana: el repositorio mantiene un solo archivo de prompt por paso, el de la
versión vigente.

**Las fixtures.** `good` gana las trece facetas repartidas en tres documentos (gobierno y
proveedores, gestión de riesgos, roles). `mid` gana solo la tolerancia y las opciones de respuesta:
se queda en 75 en `CRI-GV-03`, sus roles siguen sin autoridad (50) y **no tiene programa de
proveedores**, así que `CRI-GV-06` sigue en silencio documental. `gaps` no se toca.

**Verificación:** 630 tests (`CRI-GV-06` pasa a estar fijado por tramos con `parametrize`, siete
casos de 0 a 9 prácticas); goldens sin cambios (ninguno de estos criterios tiene evidencia técnica);
`ruff` limpio. **74 de 106 subcategorías (69,8 %)**, **GV 31/31** y 22/22 categorías.

## 78. Oleada B (4/4): "10 categorías completas" lo cuenta el sistema

**La métrica se había quedado corta.** `cobertura_implementacion` sabía decir si una categoría tiene
**al menos** un criterio (`categorias_sin_criterio`, `categorias_cubiertas`). Eso era el indicador
exacto mientras hubiera categorías vacías: cuando la lista se vaciara, estaría cerrado. Se vació en
la Oleada A, y desde entonces `categorias_cubiertas` dice siempre 22 de 22 — dejó de distinguir
nada.

La afirmación de esta oleada es otra: **completitud**. "La función Gobernar completa" y "10 de las 22
categorías completas" son hechos verificables, y el mismo razonamiento que puso `categorias_cubiertas`
en el módulo y no en la UI (§71) aplica igual aquí: ese número no puede salir de una resta hecha a
mano en una pantalla.

**Qué se añadió.** `categorias_completas` (cuántas tienen **todas** sus subcategorías declaradas) y
`categorias_incompletas` (categoría → cuántas le faltan). Se calculan en el bucle que
`coverage.py` ya recorría, se exponen en `GET /methodology` y el contrato de la API comprueba que
`completas + len(incompletas) == 22`, para que la pantalla no pueda mostrar un hueco. Una categoría
completa **no** aparece en el diccionario, ni con un 0: la lista se lee como "lo que falta".

**En pantalla.** El panel de cobertura del catálogo ya mostraba el desglose por función; ahora una
función cuyas subcategorías están todas declaradas se marca con borde y cifra en verde, con un
`title` que lo dice ("Función GV completa: sus 31 subcategorías tienen criterio"), y el pie añade
"completas: 10 de 22" junto a "con criterio: 22 de 22". Las dos cifras se leen distintas porque
miden cosas distintas.

**El catálogo decía otra cosa que la matriz.** `CRI-GV-03` pasó a cubrir las siete subcategorías de
`GV.RM` pero su `titulo` seguía siendo "Objetivos de riesgo y tolerancia establecidos", y las
recomendaciones de `GV-02`, `GV-03` y `GV-06` seguían pidiendo solo los dos o tres resultados con los
que entraron. Un criterio que evalúa una categoría entera y recomienda un tercio de ella produce
planes incompletos, así que `criteria.yml` sube a **v18** con los títulos y las recomendaciones
alineados a lo que las reglas miden hoy. Se detectó mirando la pantalla, no los tests: ninguno
compara el título del catálogo con la ficha de `docs/03`.

**Un test fija la afirmación del informe.** `test_a_complete_function_has_every_one_of_its_categories_complete`
comprueba que `por_funcion["GV"]` cierra y que ninguna categoría de GV aparece como incompleta. Si
alguien retira una subcategoría de GV, el test cae: la frase "Gobernar completa" no se puede quedar
en el documento sin el código que la sostiene.

**Estado final de la Oleada B:** **74 de 106 subcategorías (69,8 %)**, **22/22 categorías**, **10
completas** (`GV.OC`, `GV.RM`, `GV.RR`, `GV.PO`, `GV.OV`, `GV.SC`, `ID.IM`, `PR.AT`, `RS.MA`,
`RS.MI`) y la **función Gobernar en 31/31**. Lo que queda está en `ID`, `PR` y `DE`, y en su mayoría
pide señales técnicas nuevas en los adaptadores, no más campos de afirmación documental.

**Lo que esta oleada no puede verificar sola.** Diecisiete campos de afirmación nuevos, y todos
deciden puntaje. `tests/test_ai_golden.py` usa un cliente oráculo que responde la propia anotación:
mide el arnés, no al modelo. La corrida real es `python -m app.main eval-ai`, cuesta dinero y
necesita `DEEPSEEK_API_KEY`. La Oleada A ya dejó tres tipos de afirmación sin medir contra el modelo;
con esta son **tres tipos y diecisiete campos**, así que correr `eval-ai` antes de la demo pasa de
recomendable a necesario. Si U1 no extrae estos campos, `GV.RM`, `GV.RR` y `GV.SC` se quedan en los
tramos bajos y "Gobernar completa" queda cierto en el catálogo y vacío en pantalla — que es
exactamente la diferencia entre las dos coberturas que `docs/01 §7` obliga a no mezclar.

**Verificación:** 632 tests, `ruff check`/`format` limpios, `typecheck` y `lint` del frontend
limpios. Sigue fallando solo `test_uploads.py::test_windows_separator_is_rejected`, preexistente y
específico de Windows.

## 79. Endurecimiento de GV-02, RS-03 y RS-01 (integrado en `criteria.yml` v19)

Decisión de producto: un **100 exige evidencia completa**. No se concede por aproximación ni por
un dato parcial; sigue siendo alcanzable con documentos reales, porque solo se pide que el dato
declarado esté, no que la organización sea perfecta.

- **GV-02 (roles).** El 100 anterior miraba solo `autoridad`, así que `{rol: CISO, autoridad: …}`
  bastaba. Ahora exige **responsable nombrado + responsabilidades + autoridad**, además de
  `recursos_asignados` y `practicas_rh` (GV.RR-03/04 de la Oleada B). 75 si hay autoridad pero
  falta alguna de esas piezas; 50 si hay roles sin autoridad; 25 si solo hay roles genéricos.
  `role_assigned` incorpora `responsabilidades` a `_CONTENT_FIELDS` (`app/ai/extraction.py`), el
  campo que la regla necesitaba y el esquema no pedía.
- **RS-03 (notificación).** El 100 anterior solo miraba `plazos`, aunque docs/03 exige “criterios y
  plazos”. Ahora el 100 exige destinatarios + criterios + plazos; con destinatarios pero sin uno de
  los dos, 75. No se reintroduce el tramo 50 que §47 eliminó.
- **RS-01 (respuesta).** El 100 anterior aceptaba cualquier `escalation_done`, incluso anterior al
  `incident_declared`. Ahora exige que el último evento del patrón sea **posterior** a la
  declaración (misma lógica que D3, docs/08 §5); sin declaración, o con escalamiento anterior, el
  plan completo se queda en 75 y un incidente declarado en ventana completa sin escalamiento
  posterior vuelve al 0 de la regla de justicia. Se usa `hasta` del patrón para admitir varias
  escalaciones: si la última es posterior, hay al menos una que lo es.

**Tests:** `test_gv02_rol_completo_con_recursos_y_practicas_rh_es_100`,
`test_gv02_nombrar_un_ciso_no_es_dotar_la_funcion`,
`test_gv02_responsable_sin_responsabilidades_es_75`, `test_gv02_sin_autoridad_es_50`,
`test_gv02_rol_sin_responsable_es_75`, `test_gv02_rol_generico_sin_responsable_es_50`,
`test_gv02_elige_el_rol_completo_entre_varios`; `test_rs03_con_criterios_y_plazos_es_100`,
`test_rs03_sin_criterios_es_75`, `test_rs03_sin_plazos_es_75`;
`test_rs01_plan_completo_con_escalamiento_posterior_scores_100`,
`test_rs01_escalamiento_anterior_a_la_declaracion_scores_0`,
`test_rs01_plan_completo_con_escalamiento_sin_declaracion_tope_75`. Se actualizaron las
aserciones que bendecían el comportamiento laxo.

**Versión:** estos cambios se integran en **`criteria.yml` v19** (v18 de GitHub + el
endurecimiento). `docs/03` §1/§5 y `docs/02` §3.3 quedan alineados.

**Verificación:** en su corte, suite completa **580 tests** + `ruff check`/`format` limpios; la
integración final se verifica en §89.

## 80. Otras correcciones de estricta puntuación (Terraform v7, Ansible v4)

Misma regla de producto: no se concede un 100 si falta evidencia de un recurso o requisito aplicable.

- **PR-05 con flags sin resolver.** `con_bloque` se construía con todos los `tf.public_access.config`
  (incluidos los `unknown`), así que un bucket con los cuatro flags sin resolver no aparecía como
  “sin bloque” si otro bucket estaba completo: 100. Ahora solo cuenta un bloqueo **resuelto**; un
  bucket con bloqueo incompleto o sin bloque queda `evidencia_insuficiente` (docs/03 §3).
  Test: `test_pr05_an_unresolved_block_prevents_the_100`.
- **`state` de Ansible manda sobre `enabled`.** `enabled: true` + `state: stopped` se leía como
  “habilitado” (100 en PR-06/DE-01), y `state: restarted`/`reloaded` quedaba `desconocido`.
  Ahora se evalúa primero `state`; `enabled` solo es el respaldo cuando no hay `state`. Test:
  `test_service_state_wins_over_enabled`.
- **Retención HCL integral.** `backup_retention_period = 7.0` (número válido en HCL) se descartaba
  por `isinstance(..., int)` y PR-02 quedaba `evidencia_insuficiente`. Ahora un float integral se
  normaliza a días. Test: `test_integral_float_retention_is_read_as_days`.
- **S3 con varias `rule`.** Se miraba siempre `rules[0]`; si la primera era un `filter` y la
  configuración por defecto iba después, el cifrado quedaba `unknown`. Ahora se usa la primera
  `rule` que declare `apply_server_side_encryption_by_default`. Test:
  `test_s3_encryption_uses_the_rule_that_defines_sse`.

**Versiones de adaptador:** Terraform pasa a **v7** y Ansible a **v4** (cambia la evidencia emitida;
`assessments.reproducibility` lo registra). No cambia `methodology_version` por esto.

**Verificación:** suite completa **584 tests** + `ruff check` y `ruff format` limpios.

## 81. Security groups dinámicos y disparadores con varios eventos (Terraform v8)

- **`dynamic "ingress"/"egress"`.** python-hcl2 no los deja en `attrs["ingress"]`, así que el
  adaptador no emitía ninguna regla: PR-03 veía una lista vacía y devolvía 100. Ahora se emite una
  regla con `cidr: unknown` (los puertos del `content`, si están), y PR-03 la trata como
  indeterminada → `evidencia_insuficiente`. No se expande `for_each` (puede ser una variable).
  Terraform pasa a **v8**. Test: `test_dynamic_ingress_is_unknown_not_absent`.
- **D1/D2/D3/D5 con varios eventos.** Los patrones guardan el primero y el último evento del tipo;
  los disparadores comparaban los `desde`, así que un triaje/escalamiento/alerta/comunicación
  viejo ocultaba uno nuevo. Ahora comparan los `hasta` (último evento de cada patrón):
  - D1 solo se silencia con una alerta posterior al inicio de la ráfaga.
  - D2 mide el triaje posterior contra la última alerta.
  - D3 mide el escalamiento posterior contra la última declaración.
  - D5 solo se silencia con una comunicación posterior a la verificación.
  Tests: los seis casos nuevos en `test_ops_triggers.py` (triaje viejo + alerta nueva, alerta
  vieja + triaje nuevo, escalamiento viejo + declaración nueva, declaración vieja + escalamiento
  viejo, alerta vieja + ráfaga nueva, comunicación vieja + verificación nueva). docs/08 §5 y
  docs/02 §4 quedan alineados.

**Límite conocido:** sigue habiendo una fila por patrón y scope (docs/06 §3), así que con varios
pares alerta/triaje intercalados la comparación de extremos es una aproximación. Resolverlo del
todo requiere patrones por evento o por par, que es un cambio de modelo (docs/12).

**Verificación:** suite completa **591 tests** + `ruff check` y `ruff format` limpios.

## 82. Robustez de IA y de los adaptadores (Terraform v9, Ansible v5, Documentos v3)

- **U2 no se aplica si la respuesta no es del criterio.** `AdjustmentResponse` valida rango
  (`puntaje_base_recibido`/`puntaje_propuesto` 0–100, `confianza` 0–1) y `adjust()` exige que
  `criterion_id` y `puntaje_base_recibido` coincidan con el criterio evaluado; si no, degrada a
  `S = B` con `degradado=True`. Un `NaN`/`Infinity` que `json.loads` acepta ya no llega a
  `round()`: Pydantic lo rechaza y se degrada. U1 también rechaza confianzas fuera de rango.
- **Caché de IA.** La clave incluye modelo y base URL (cambiar `DEEPSEEK_MODEL` ya no devuelve la
  respuesta del modelo anterior). Una entrada corrupta o no-dict se trata como miss; la escritura
  es atómica (temp + replace).
- **Ansible.** `_AnsibleLoader` acepta `!vault`/`!unsafe` y cualquier tag `!...` como opaco (no
  descifra secretos, no tumba la evaluación); `!vault` se guarda como `<vault>`. Las fechas YAML
  se convierten a texto (`line: 2025-01-01` no rompe el JSON de la evidencia) y `hosts` siempre es
  un array de strings (`hosts: [web, db]` ya no queda anidado).
- **BOM y documentos.** Terraform, Ansible y Markdown leen con `utf-8-sig`; un BOM ya no rompe el
  `.tf` ni pierde el primer encabezado. Los encabezados `#` dentro de bloques ```/~~~ no son
  secciones. Un PDF cifrado con contraseña se omite (cero secciones), no deja la evaluación
  `fallida`.

**Versiones de adaptador:** Terraform **v9**, Ansible **v5**, Documentos **v3** (cambia la
evidencia emitida; `assessments.reproducibility` lo registra). No cambia `methodology_version`.

**Verificación:** suite completa **601 tests** + `ruff check` y `ruff format` limpios.

## 83. Reevaluación con documentos, refresco y procedencia de planes

- **La API de reevaluación pedía U1 solo si `ai_adjust`.** `enqueue_reevaluation` ponía
  `ai_requested = apply_ai_adjustment`; si la evaluación anterior tenía documentos, el worker
  re-leía los PDFs/Markdown con `NullAIClient` y perdía todos los `doc.claim`: GV-01 pasaba de 100 a
  `evidencia_insuficiente`. Ahora la ruta detecta `Source(tipo="documents")`, aplica el guard de IA
  real con `confirm_live_ai` y encola `ai_requested=True` (el CLI ya lo hacía). Test:
  `test_reevaluating_documents_requests_ai`.
- **Refresco selectivo con otra metodología.** `run_surveillance_refresh` copiaba resultados de la
  evaluación anterior sin mirar `methodology_version`: una evaluación con 6 criterios se completaba
  con 13/23 resultados, se marcaba con la versión nueva y `provisional=False`. Ahora
  `enqueue_surveillance_refresh` detecta el cambio y hace un **re-run completo** con las mismas
  fuentes (y U1 si hay documentos); `run_surveillance_refresh` además falla el job si un refresco
  selectivo viejo llega tras el deploy. Tests:
  `test_enqueue_refresh_falls_back_to_full_run_when_methodology_changed` y
  `test_selective_refresh_refuses_a_different_methodology`.
- **Procedencia de planes.** `generado_por` se decidía por la clase del cliente: un cliente de IA
  que caía a la plantilla se grababa como `ai:plan_v1`. Ahora `generate_plan_content` marca el
  contenido (`generado_por`), y `recommendations/plans`/`ops/plans` lo copian; un fallback queda
  como `plantilla`. Tests: `test_ai_client_without_content_is_labelled_template` en ambos módulos.
  docs/04 §6 y docs/06 §6 quedan alineados.

**Verificación:** suite completa **606 tests** + `ruff check` y `ruff format` limpios.

## 84. Entradas hostiles: 401/422 en vez de 500

- **Firma no ASCII.** `hmac.compare_digest(str, str)` lanza `TypeError` con caracteres no ASCII;
  cualquier cliente sin token podía provocar un 500. `decode_token` lo captura y devuelve `None`
  (401). Test: `test_non_ascii_signature_is_rejected_not_500`.
- **Payload firmado malformado.** `exp` como string (`TypeError` al comparar), `sub` como lista
  (`session.get` revienta) u `org` no-string ahora se rechazan en `decode_token` como 401, no 500.
  Test: `test_token_with_a_malformed_payload_is_rejected`.
- **Login sin enumeración por tiempo.** Un usuario inexistente no saltaba PBKDF2 (~3 ms vs ~37 ms).
  Ahora ejecuta un hash de relleno cacheado al importar; el tiempo es comparable. Test:
  `test_unknown_user_still_runs_the_password_hash`.
- **`context` con un entero de >4300 dígitos** (o un objeto muy anidado) lanzaba `ValueError`/
  `RecursionError` fuera del `JSONDecodeError` capturado: 500. Ahora ambos son 422 antes de crear
  nada. Test: `test_context_with_a_huge_number_is_422_not_500`.
- **Nombre de archivo de >255 bytes.** Pasaba el saneo y `write_bytes` lanzaba `OSError` (500).
  `safe_filename` lo rechaza con 422. Test: `test_overlong_name_is_rejected`.

**Verificación:** suite completa **611 tests** + `ruff check` y `ruff format` limpios.

## 85. Ciclo de vida, contratos de jobs y determinismo

- **Plan antes de `completada`.** Se marcaba `completada` y se hacía commit antes de
  `generate_plans`; una lectura concurrente veía la evaluación terminada con cero planes. Ahora los
  planes se generan antes y recién entonces se publica `completada`. Test:
  `test_assessment_is_not_published_as_completed_before_plans`.
- **`methodology_version` al ejecutar.** Se copiaba en `create_pending_assessment`; un job encolado
  antes de un deploy corría las reglas nuevas pero registraba la versión vieja. Ahora el worker la
  fija al empezar. Test: `test_methodology_version_is_stamped_when_the_worker_runs`.
- **Contrato de `JobOut`.** `resultado` pasa de `dict` libre a `IngestJobResult` con defaults 0 (la
  UI no recibe `undefined`) y `reintentable` exige que la evaluación siga `fallida`: tras un
  reintento exitoso el job viejo deja de ofrecer "Reintentar" (antes el botón siempre daba 409).
  Tests: `test_job_result_is_exposed_by_the_api` y la aserción nueva en `test_job_retry.py`.
- **Fechas de eventos.** `event_time` se normaliza a UTC al parsear; mezclar naive y aware lanzaba
  `TypeError` y tumbaba la ingesta. Test: `test_mixed_naive_and_aware_event_times_are_normalized`.
- **`best_found` determinista.** En empate de confianza decide el `subject_ref` y luego el
  contenido, no el orden de la lista. Tests: `test_rules_common.py`.
- **Golden set.** Una respuesta no-objeto o un `afirmaciones` no-lista ya no rompen el arnés; una
  cita que normaliza a vacío (`"..."`) no cuenta como localizable. Test nuevo en
  `test_ai_golden.py`.
- **Frontend.** `MethodologyCatalog.methodology_version` es `string` (no `number`) e incluye
  `nucleo_csf_version` y `cobertura_implementacion`.

**Verificación:** suite completa **617 tests** + `ruff check` y `ruff format` limpios; frontend
`typecheck`, `lint` y `build` limpios.

## 86. PR-01 sin evidencia de cifrado y PR-04 con modos simbólicos (integrado en `criteria.yml` v19)

- **PR-01.** Un `aws_s3_bucket` sin `aws_s3_bucket_server_side_encryption_configuration` no emitía
  `tf.encryption.config`; PR-01 veía una lista vacía y devolvía `no_aplicable` (o 100 si otro
  recurso cifraba). Ahora cruza `tf.encryption.config` con `tf.resource.present` de buckets y bases:
  un recurso aplicable sin evidencia es `evidencia_insuficiente`, no 100. Tampoco da 100 un recurso
  con estado `unknown` (`storage_encrypted = var.enc`), que antes se puntuaba "sobre los resueltos".
  Un `disabled` explícito sigue prevaleciendo (0/25). Tests:
  `test_bucket_without_encryption_evidence_is_insufficient`,
  `test_plain_bucket_next_to_an_encrypted_one_is_not_100` y
  `test_rule_does_not_award_100_with_an_unresolved_resource`; los tests que arreglaban solo RDS
  ahora agregan también SSE al bucket. Golden `pipeline_good` regenerado (solo cambia la
  explicación: el fixture sí tiene SSE en ambos recursos).
- **PR-04.** `_modo_octal` traducía enteros pero dejaba los simbólicos tal cual; `int(modo, 8)`
  fallaba y la regla ignoraba el permiso, dando 100 con `u=rw,g=rw,o=rw` (0666). Ahora traduce los
  modos simbólicos absolutos (`u=rw,g=rw,o=rw` → `0666`) y marca los relativos (`u+rwx`) como
  `unknown`; PR-04 no da 100 con un modo no interpretable. Ansible pasa a **v6**. Tests:
  `test_symbolic_modes_are_translated_or_marked_unknown`,
  `test_pr04_symbolic_mode_caps_at_25`, `test_pr04_relative_symbolic_mode_is_insufficient`.

**Versión:** estos cambios se integran en **`criteria.yml` v19**. docs/02 §4, docs/03 §3 y
README/docs/11 quedan alineados.

**Verificación:** en su corte, suite completa **622 tests** + `ruff check`/`format` limpios; la
integración final se verifica en §89.

## 87. Rangos de línea de Terraform (Terraform v10)

`resource_line_ranges` contaba llaves sobre el texto crudo: un `}` dentro de un comentario
`/* ... */` o de un heredoc cerraba el bloque antes de tiempo, y una llave en la línea siguiente al
`resource` no se detectaba (el recurso quedaba sin locator). `_clean_hcl` blanquea comentarios y
cuerpos de heredoc conservando líneas y longitud; la apertura se busca con `_has_open_brace` y el
cierre con `_brace_delta`. Terraform pasa a **v10** (cambian los locators, no los valores).
Test: `test_line_ranges_ignore_block_comments_and_heredocs_and_accept_next_line_brace`.

**Verificación:** suite completa **623 tests** + `ruff check` y `ruff format` limpios.

## 88. Incidentes únicos por organización **y scope**

La clave de correlación sale del recurso y la hora del evento (`auth-burst:srv-app-01:2026-09-20…`),
no del entorno. La restricción era `(org_id, correlation_key)`, así que un mismo host/hora en
producción y staging se fusionaba: el incidente de producción recibía los `event_ids` y el
`last_event_time` de staging. `docs/08 §3` ya definía los incidentes como org+scope; faltaba la
restricción.

- **Modelo/consulta:** `Incident.__table_args__` pasa a
  `(org_id, scope, correlation_key)` y `upsert_incident` filtra también por `scope`.
- **Migración:** `f3a1c9d2e4b7` (rev. `b7e2f4c19d55`) recrea la restricción. Es solo esquema:
  agregar `scope` relaja la unicidad, así que las filas existentes son válidas. Una fila ya
  fusionada no se puede separar retroactivamente; desde esta versión, una ingesta nueva crea el
  incidente correcto. `downgrade` falla si hay dos scopes con la misma clave, porque volver atrás
  exigiría fusionarlos.
- **Ejemplos:** no necesitan migración de datos. Los paquetes/escenarios son JSONL y no guardan
  incidentes; se re-ingieren y crean las filas. La BD SQLite local de desarrollo (`.data/pf.db`)
  tenía **0 incidentes** y un esquema anterior a `b7e2f4c19d55`; se puede recrear (o dejar que
  Alembic la migre, si se creó con Alembic). El compose usa Postgres y la migración se aplica con
  el job `migrate`.
- **Verificación de la migración:** `alembic upgrade head` sobre SQLite limpio y sobre una BD
  detenida en `b7e2f4c19d55` con un incidente; tras el upgrade se pudo insertar el mismo
  `correlation_key` en otro scope. Test: `test_same_correlation_key_in_another_scope_is_a_separate_incident`.

**Verificación:** suite completa **624 tests** + `ruff check` y `ruff format` limpios.

## 89. Integración con GitHub: catálogo v18 + endurecimiento (v19)

GitHub era la línea principal (10 commits, docs/09 §70–§78, `criteria.yml` v18, 28 criterios y la
cobertura en el dashboard); la rama local tenía 10 commits de correcciones sobre §69. Se integró
con un **merge**, no rebase ni force-push: el commit de merge tiene ambas líneas como padres y es
fast-forward para los dos remotos.

**Qué aporta GitHub:** 28 criterios (GV-05/06, ID-05, PR-07, RS-04), correlación multi-fuente
(`log.pattern@2`), cobertura de implementación en la UI, comparación de catálogos, prompt U1 v4 y
los campos de afirmación de las Oleadas A/B.

**Qué se re-aplicó encima:** el endurecimiento de GV-02 (responsable + responsabilidades +
autoridad + recursos/RH), RS-03 (criterios y plazos), RS-01 (escalamiento posterior a la
declaración, combinado con `criterios_recuperacion` de RS.MA-05), PR-01 (evidencia por recurso),
PR-04 (modos simbólicos), PR-05 (bloqueo resuelto), D1–D5 con el último evento, la robustez de IA y
adaptadores, auth/entrada 4xx, el orden plan→completada, la versión al ejecutar y la migración de
incidentes por org+scope.

**Conflictos resueltos:** `criteria.yml` (v18 → **v19**), GV-02 y RS-01 (reglas y tests), docs/03,
docs/09 (nuestras secciones renumeradas §79–§88), docs/11, README y `frontend/src/lib/types.ts`
(`ImplementationCoverage` de GitHub + `methodology_version: string`).

**Versiones finales:** `criteria.yml` **v19**, `settings.yml` **v3**, Terraform **v10**, Ansible
**v6**, Documentos **v3**. La migración de incidentes `f3a1c9d2e4b7` sigue siendo la cabeza y se
aplicó sobre el esquema de GitHub sin cambios.

**Verificación:** suite completa **685 tests** + 2 skipped; `ruff check` y `ruff format --check`
limpios; frontend `typecheck`, `lint` y `build` limpios; `alembic upgrade head` sobre SQLite limpio
con la restricción `(org_id, scope, correlation_key)`.

## 90. Oleada C (1/5): el adaptador aprende a leer de dónde viene el código (`ID.RA-09`)

**AMP-07 llevaba dos oleadas anotado como deuda** (docs/12 §5), y la Oleada B lo había reescrito: ya
no era un ítem de cobertura, porque `GV.SC-07` quedó cubierta por vía documental, sino de **calidad
de la señal** — cambiar una afirmación extraída por IA por una observación determinística del IaC.
Esta oleada lo cierra, y de paso cubre `ID.RA-09`, que seguía descubierta.

**Había una ruta de parseo que no existía.** `TerraformAdapter` usa un parser HCL real
(`python-hcl2`), así que `hcl2.loads` ya devolvía las claves `module`, `provider` y `terraform` en el
diccionario; simplemente nadie las leía. `_flatten_resources` hacía `raw.get("resource", [])` y ahí
se acababa. El adaptador llevaba desde el principio **mirando solo una sexta parte de lo que ya
tenía parseado**.

Lo que sí había que construir eran los **locators**. `resource_line_ranges` estaba atada a la palabra
`resource` por una regex literal, y un bloque sin rango de líneas no es evidencia auditable: es una
afirmación sin dónde comprobarla. Se generalizó a `block_line_ranges(texto, patron)`, con
`_block_start(keyword, etiquetas)` construyendo el patrón según cuántas etiquetas lleva el bloque
(`resource` dos, `module` una, `terraform` ninguna). Un bloque sin etiquetas se indexa por orden de
aparición para que dos en el mismo archivo no se pisen, y el patrón de `terraform` exige que la línea
no sea otra cosa: sin eso, `terraform_remote_state` y `terraform = "x"` coincidían.

**Dos tipos nuevos** (`evidence_types.yml` v6): `tf.module.source` y `tf.provider.version`. El primero
clasifica el `origen` del `source` (`registry`/`git`/`externo`/`local`/`desconocido`) y si la
procedencia está `fijada`. Un `source` no literal se emite con `estado: "unknown"`, que es el
convenio que ya hace aparecer un hallazgo de limitación sin añadir código
(`recommendations/limitations.py`).

**`CRI-ID-06` y dos decisiones que la rúbrica hace explícitas.**

- **Un módulo local no se penaliza.** `source = "../modules/red"` es código del mismo repositorio: no
  se adquiere de nadie y no hay versión que fijar. Contarlo como "sin fijar" sería castigar tener el
  código propio ordenado en módulos, que es lo contrario de lo que se quiere incentivar. Lleva
  `estado: "propio"`, no `"fijado"`: `fijada: false` con `estado: "fijado"` se contradecía en la cara.
- **El piso es 25, no 0.** Un `source` sin `version` no es una negación, es silencio sobre la
  procedencia — el mismo razonamiento del silencio documental (§60). Para dar 0 haría falta una
  declaración explícita de que no se controla, y en HCL eso no existe. Es la primera vez que ese
  principio, que nació para los documentos, se aplica a una señal técnica.

Un `source` que el parser no puede leer cuenta como **de terceros**, no como propio: suponer lo
segundo sería suponer a favor.

**Los tres paquetes caen en tramos distintos**, que es lo que hace útil la demo: `good` 100 (proveedor
y módulo del registry fijados), `mid` 50 (el módulo fijado, el proveedor sin restricción), `gaps` 25
(dos módulos de git sin `?ref=` y ningún `required_providers`). La procedencia vive en un
`versiones.tf` propio por paquete, que es la convención de Terraform y además dejó intactos los
números de línea de los goldens: el diff es solo adiciones.

**Lo que esto mueve, y por qué está bien.** Un criterio nuevo es un sumando nuevo en el promedio
ponderado. En el pipeline golden —que es Terraform + Ansible, sin IA— la **función Identificar pasa de
`null` a tener puntaje**, porque hasta ahora ninguno de sus criterios se evaluaba sin afirmaciones
documentales. El global de `gaps` sube de 3,75 a 14,38. No es una regresión ni un ablandamiento de la
escala: el sistema mide una cosa más y esa cosa, en `gaps`, saca 25. `ID` queda además marcada
`provisional` (1 criterio evaluado de 6), que es exactamente para lo que existe esa marca.

**Y es la primera subcategoría de la cobertura que no depende de la IA.** Las Oleadas A y B subieron
cobertura añadiendo campos de afirmación: honestos, pero sin medir contra el modelo real. `ID.RA-09`
sale de leer el `.tf`, así que los tests la fijan de verdad.

**Verificación:** 717 tests (28 nuevos), `ruff check`/`format` limpios. Goldens regenerados y leídos
uno a uno: en los de evidencia solo hay adiciones, y cada puntaje que se movió en los de pipeline se
explica con el criterio nuevo.

## 91. Oleada C (2/5): identidades y autenticación, con dos señales que ya estaban en el `.tf`

`PR.AA` estaba en **1 de 6**: la única subcategoría cubierta era `PR.AA-05` (mínimo privilegio), por
los CIDR de los security groups. "Se gestionan las identidades" y "los usuarios se autentican" no
tenían criterio, y no por falta de documentación: los adaptadores no reconocían un solo recurso IAM.

**Dos señales, una por subcategoría.**

- **`PR.AA-01`** se evidencia con `tf.resource.present` filtrado a `aws_iam_*`, el tipo que ya
  existía. Un rol creado a mano en la consola no está gestionado; uno declarado en Terraform tiene
  dueño, revisión e historial. No hacía falta un tipo nuevo para esto.
- **`PR.AA-03`** sí lo necesitaba: `tf.identity.config`, con los atributos de
  `aws_iam_account_password_policy` y la exigencia de MFA.

**El MFA no es un atributo.** En AWS no existe un `require_mfa = true`: la exigencia se expresa como
la condición `aws:MultiFactorAuthPresent` dentro del documento JSON de una política IAM. El
adaptador lee ese documento cuando es literal (un heredoc) y busca la condición. Cuando el documento
viene de `jsonencode(...)` o de un `data` source no es literal, y entonces emite
`mfa_requerido: null` con `estado: "unknown"`, **nunca `false`**: lo contrario convertiría una
limitación del parser en un incumplimiento, que es justo lo que docs/02 §4 prohíbe.

**La asimetría de la rúbrica, que es lo más discutible y por eso va escrito.** Una política de
contraseñas *declarada y débil* puntúa **por debajo** de no declarar ninguna: 6 caracteres da 0,
10 da 25, y no tener política da 50. Parece al revés. No lo es: en IaC la ausencia no prueba la
ausencia —la cuenta puede tener su política puesta fuera de Terraform—, mientras que una longitud
mínima de 6 escrita en el `.tf` es la observación directa de un control débil. Es el principio del
silencio documental (§60) aplicado por segunda vez a una señal técnica, después de §90. Hay un test
que lo fija explícitamente, porque sin él el próximo que lo lea lo "arregla".

El umbral de 14 es el del **CIS AWS Foundations Benchmark**, no una cifra elegida a ojo. Con dos
políticas declaradas manda la más débil: es la que la cuenta aplica de hecho.

**`aws_iam_account_password_policy` entró en `CONFIG_RESOURCE_TYPES`.** Configura la cuenta entera,
no es un activo que un inventario deba listar — el mismo criterio que ya excluía los recursos de
configuración de S3. Sin eso habría bajado `CRI-ID-01` por un recurso que ningún inventario lista.

**Lo que sí movió a `CRI-ID-01`**, y es la clase de acoplamiento que solo se ve mirando: añadir
`aws_iam_role` y `aws_iam_policy` a los fixtures mete dos tipos nuevos en el denominador del
inventario. El documento de `good` listaba cuatro tipos y habría bajado de 100 a 50 **sin que
ningún test del pipeline lo detectara**, porque `CRI-ID-01` necesita IA y el pipeline golden no la
usa. Se añadieron los dos tipos a su inventario. `mid` y `gaps` no cambian de tramo (2/5 y 0/4 caen
donde caían).

**Los tres paquetes:** `good` 100, `mid` 25 (10 caracteres, sin MFA), `gaps` 0 (6 caracteres
declarados). En `gaps` eso **baja** el puntaje de la función Proteger de 3,75 a 3,0, que es lo que
debe pasar cuando se observa un control débil nuevo, y el global de 14,38 a 14,0.

**Verificación:** 734 tests (17 nuevos), `ruff` limpio, goldens releídos. `PR.AA` pasa de 1/6 a 3/6 y
la cobertura a **77/106 (72,6 %)**, con PROTECT en 10/22.

## 92. Oleada C (3/5): sobrevivir a una zona caída y aguantar la carga no son lo mismo

`PR.IR` estaba en **1 de 4**, con solo `PR.IR-01` cubierta por los security groups. Las dos que
faltaban y sí se pueden observar en el IaC suenan parecidas y no lo son, y por eso el CSF las separa:

- **`PR.IR-03`** ("mecanismos para alcanzar los requisitos de resiliencia") es **sobrevivir a la
  pérdida de una zona**: `multi_az` o una réplica de lectura.
- **`PR.IR-04`** ("capacidad de recursos adecuada") es **aguantar la carga**: un grupo de
  autoescalado.

Mezclarlas en un solo ancla habría dado 100 a una plataforma con autoescalado y una sola zona, que
es exactamente la que se cae entera un martes.

**`min_size == max_size` no es capacidad elástica.** Es capacidad fija con otro nombre, y no sostiene
"se mantiene capacidad adecuada para asegurar la disponibilidad". El `habilitado` del autoescalado es
cierto solo si el grupo puede crecer.

**`no_declarado` no es `unknown`, y la diferencia costó una decisión.** La primera versión emitía
`estado: "unknown"` para un `multi_az` ausente, por analogía con `tf.public_access.config`. Tres
tests de `test_limitation_findings.py` cayeron en el acto, y tenían razón: `unknown` es el convenio
que `recommendations/limitations.py` usa para decir *"el parser no pudo leer este valor"*, y hace
aparecer un hallazgo. Un atributo que simplemente no está escrito no es un valor ilegible — y
`multi_az` se omite en casi todo `.tf` real, así que habría generado un hallazgo de limitación por
cada base de datos de cualquier proyecto.

Toda esta oleada ha ido separando "no lo veo" de "lo veo y está mal"; aquí hacía falta un tercer
estado: **"no lo escribiste"**. `unknown` queda reservado a lo que el parser no puede resolver —para
eso ya está `tf.expression.unresolved` y el decorador `noting_unresolved`, que cita la expresión sin
tocar el puntaje.

**La rúbrica tiene cinco anclas porque hay cinco situaciones distintas**, y la del 25 es la que
obliga a pensar: capacidad elástica **con** `multi_az = false` explícito. Crecer con la carga no
compensa haber apagado la alta disponibilidad a mano, pero tampoco es lo mismo que no tener nada, y
por eso no es 0.

**Los tres paquetes:** `good` 100 (`multi_az` y un grupo de 2 a 6), `mid` 50 (el grupo crece, ninguna
base declara `multi_az`), `gaps` 0 (`multi_az = false` y sin autoescalado).

**Dos efectos colaterales que hubo que atender, los dos del mismo tipo:** `aws_autoscaling_group` es
un tipo de recurso nuevo, así que entra en el **denominador del inventario** de `CRI-ID-01` — el
documento de `good` lo lista ahora, igual que pasó con IAM en §91. Y el `multi_az` de `good` y `gaps`
se declara dentro de un bloque que ya existía en `main.tf`, así que **desplaza una línea** todos los
locators posteriores de ese archivo. Se comprobó que en los goldens de evidencia las únicas bajas son
`line_start`/`line_end`: ni un valor cambió.

**Verificación:** 747 tests (13 nuevos), `ruff` limpio. `PR.IR` pasa de 1/4 a 3/4 —`PR.IR-02`,
amenazas ambientales, es física y queda fuera del alcance declarado— y la cobertura a **79/106
(74,5 %)**, con PROTECT en 12/22.

## 93. Oleada C (4/5): el dato en viaje, y un ancla que baja a propósito

`PR.DS-02` ("se protege el dato en tránsito") era la última subcategoría de `PR.DS` alcanzable: la
que queda, `PR.DS-10` (dato **en uso**), pide enclaves o memoria cifrada y no está en el alcance de
los adaptadores.

**Sin criterio nuevo.** En reposo y en tránsito son las dos mitades del mismo control, y
`CRI-PR-01` ya compone evidencia de RDS y de S3. Se retituló a "Cifrado de datos en reposo y en
tránsito" y pasó a `version: 2`. Un criterio cuyo título dice menos de lo que evalúa produce
recomendaciones incompletas — la lección de §78.

**Las dos mitades no son simétricas, y la rúbrica lo refleja.** Un fallo en reposo es una base de
datos entera legible por quien consiga el volumen; un canal en claro es grave, pero acotado a lo que
pasa por él. Así que el tránsito **no** es una rama aparte: es una **compuerta sobre el tramo alto**.
Con todo cifrado en reposo, 100 exige además observar el canal, 75 si el IaC no dice nada de él, y 50
si se observa un listener HTTP. Pero un `storage_encrypted = false` sigue mandando por D7: un
listener HTTPS no lo sube. Hay un test que lo fija.

**Y el ancla del 100 bajó.** `good` seguiría en 100 solo porque se le añadió el listener HTTPS y el
`rds.force_ssl`; sin eso habría caído a 75. Eso es lo que debe pasar: declarar una subcategoría más
tiene que **costar más evidencia**, o la cobertura sube y el puntaje se abarata a la vez, que es la
combinación que no se puede defender (§77). Cuatro tests de otros archivos cayeron pidiendo el 100
antiguo y se actualizaron a 75 **sin tocar la regla**: eran la consecuencia correcta, no una
regresión.

**Dos señales, y una decisión sobre el ruido.** El listener se lee del `protocol` y la `ssl_policy`;
la base, del parámetro `rds.force_ssl` de un `aws_db_parameter_group`. Ese segundo emisor **solo
emite si el grupo declara ese parámetro**: un grupo que ajusta `log_statement` no dice nada sobre el
tránsito, y emitir `unknown` por cada grupo de parámetros del proyecto habría llenado los hallazgos
de ruido — el mismo criterio que llevó a `no_declarado` en §92.

**`aws_lb_listener` y `aws_db_parameter_group` entran en `CONFIG_RESOURCE_TYPES`:** configuran a otro
recurso (un balanceador, una base), no son activos que un inventario deba listar. `aws_lb` sí lo es,
y está en el inventario de `good` — es la cuarta vez en esta oleada que un tipo de recurso nuevo pasa
por el denominador de `CRI-ID-01`, y conviene decirlo: **cada señal técnica nueva tiene ese peaje**.

**Verificación:** 756 tests (9 nuevos), `ruff` limpio. En el golden de `good` el único cambio del
pipeline es la explicación —el 100 se sostiene con la evidencia nueva— y en el de evidencia solo hay
adiciones. `PR.DS` pasa de 2/4 a 3/4 y la cobertura a **80/106 (75,5 %)**, con PROTECT en 13/22.

## 94. Oleada C (5/5): un `sshd_config` endurecido sobre un sistema sin parchear

`apt` caía en `an.task.uninterpreted`. El adaptador de Ansible reconocía siete módulos —
`lineinfile`, `copy`, `template`, `file`, `service`, `ufw`, `iptables` — y **ningún gestor de
paquetes**, así que la señal más directa de "el software se mantiene" (`PR.PS-02`) se registraba
como "módulo no soportado" y se perdía.

**`an.package.state` lee la intención, no el módulo.** `apt`, `yum`, `dnf` y `package` son cuatro
módulos para lo mismo, y lo que decide es qué hace la tarea: `actualiza` (`upgrade`, o
`state: latest`), `instala`, `elimina` o `desconocido`. **Solo `actualiza` sostiene `PR.PS-02`**: un
`state: present` deja instalada la versión que ya hubiera, y confundir "el paquete está" con "el
paquete está al día" sería exactamente el tipo de atajo que esta oleada ha ido evitando.

**Sin criterio nuevo, y con el título corregido.** `CRI-PR-04` pasa a "Configuración y
mantenimiento seguro del servidor" y a `version: 2`. Las dos mitades son lo mismo visto dos veces:
`PR.PS-01` es cómo está configurado el servidor, `PR.PS-02` es si sigue estándolo el mes que viene.

**El orden de las tres reglas importa, y es el único detalle fino de este commit.** El tope por
permisos inseguros (25) se aplica **antes** de la compuerta de mantenimiento, y la compuerta solo
toca el 100:

1. Si el SSH no está endurecido, ese es el problema — el estado de los paquetes no lo mejora ni lo
   empeora.
2. Si `sshd_config` es escribible por otros, tope 25 aunque el sistema esté al día.
3. Solo con las dos directivas endurecidas y los permisos correctos decide `PR.PS-02`: 100 con una
   tarea que actualice, 75 sin ella.

Los tres pasos tienen su test, porque un reordenamiento accidental no se vería en el puntaje de la
demo (`mid` y `gaps` están en 25 por el SSH y no llegan a la compuerta).

**Tres tests de otros archivos pedían el 100 antiguo** y bajaron a 75 sin tocar la regla, igual que
en §93. Uno de ellos, el parametrizado de modos octales de `test_review_fixes.py`, lo que fija es la
lectura del modo y no el tramo: se dejó anotado para que no se lea como una regresión.

**`good` 100** (`apt: upgrade: safe` con `update_cache`), **`mid` 25** (sigue dominando
`PasswordAuthentication yes`; su tarea nueva solo instala un agente) y **`gaps` 25**. Que `mid` no se
mueva es la demostración de que la compuerta no toca los tramos bajos.

## Cierre de la Oleada C

**81 de 106 subcategorías (76,4 %)**, **31 criterios**, **PROTECT de 8/22 a 14/22** y las 22
categorías con criterio. Siete subcategorías nuevas —`ID.RA-09`, `PR.AA-01`, `PR.AA-03`, `PR.IR-03`,
`PR.IR-04`, `PR.DS-02`, `PR.PS-02`— y **ninguna depende de que la IA extraiga nada**: todas salen de
leer el IaC, así que los tests las fijan de verdad. Es la primera oleada de la que se puede decir eso.

Lo que la oleada **no** declaró, y por qué, está en `docs/12 §5`: no se quedó en la cabeza de nadie.

## 95. Lo que encontró revisar la Oleada C

Tres hallazgos, y los tres del mismo tipo: cosas que la suite no podía ver porque nada las miraba.

**Un módulo de registry privado se reportaba como ilegible.** El patrón de `module_origin` aceptaba
`namespace/nombre/proveedor` y nada más, así que `app.terraform.io/acme/vpc/aws` —la forma
documentada de Terraform Cloud, `host/namespace/nombre/proveedor`— caía en `desconocido` y emitía
`estado: "unknown"` con el hallazgo *"source no literal: procedencia no determinable"*, cuando el
`source` **sí** era literal y la `version` **sí** estaba fijada. En pantalla eso es una limitación
falsa en un proyecto que no tiene ninguna.

El puntaje no se movía (`desconocido` ya contaba como externo, y `fijada` seguía siendo cierto),
así que ningún test lo habría detectado nunca: solo se vio probando formas de `source` a mano. De
paso dejaba la contradicción **`fijada: true` con `estado: "unknown"`**, exactamente la que §90
había corregido para los módulos locales, reaparecida por otra puerta.

Arreglado en dos sitios, porque eran dos errores: el patrón reconoce el host (se distingue de un
namespace porque lleva un punto, así que el registry público de tres segmentos sigue igual), y
`module_pinned` devuelve `false` cuando el `source` no es literal — fijar la versión de un módulo
que no se sabe cuál es no hace reproducible su procedencia. Terraform **v15**.

**Dos fichas de `docs/03` con el título truncado**, y son de cosecha propia: las escribió la Oleada B
(§77) al cubrir las tres que faltaban. `CRI-GV-05` decía "Contexto organizacional" por "Contexto
organizacional declarado" y `CRI-PR-07` "Concienciación y formación" por "Concienciación y formación
en seguridad". Es **el mismo fallo que esa oleada denunció** para `CRI-GV-03` y arregló a mano
(§78), reintroducido en dos de las tres fichas nuevas en el mismo commit que lo arreglaba.

**Tres veces el mismo fallo es un test que falta, no mala suerte.** La cabecera de `docs/03` afirma
que "las reglas de esta matriz describen el código" y que se actualiza en el mismo commit;
`tests/test_criteria_matrix_doc.py` hace que esa afirmación cueste algo: una ficha por criterio, el
título de cada ficha igual al del catálogo, y ninguna ficha sin subcategorías, evidencias o regla.
Comprobado contra una mutación —truncar un título a mano— antes de darlo por bueno. Encontró de
paso que `CRI-RC-03` escribe su regla como `**Regla** (...)` en vez de `**Regla:**`: eso no era un
defecto del documento sino del patrón del test, y se relajó el patrón, no el documento.

**Lo que se comprobó y estaba bien:** los seis tipos de evidencia nuevos tienen productor y
consumidor; ningún criterio declara evidencia que su regla no lea; las cifras de `docs/01`,
`docs/00`, `README` y `docs/11` coinciden con las que calcula `GET /methodology`; no hay referencias
rotas a secciones de `docs/09`; `demo.ts` lista exactamente los archivos que existen; los fixtures
de Ansible siguen idénticos byte a byte a los de la demo y los de Terraform mantienen el recorte
documentado; y los tres paquetes progresan de verdad —global 18,3 / 59,5 / 97,1 y PROTECT 11,6 /
53,5 / 91,4—, con los tres criterios nuevos repartidos por toda la escala en vez de amontonados.

**Estado final: 778 tests**, 2 skipped, `ruff` y frontend limpios.

## 96. Las 106 subcategorías, cubiertas o justificadas

`docs/12 §5` decía de sí mismo que el motivo de lo no declarado "va aquí, no en la cabeza de nadie".
**No se cumplía.** De las 25 subcategorías descubiertas, solo 16 tenían motivo escrito; las otras
nueve no aparecían en ninguna parte. Nada lo detectaba, porque la cobertura solo sabe contar las que
**sí** están cubiertas: lo que falta es, por definición, lo que no se cuenta.

Ahora están las 25, repartidas en tres grupos que no son lo mismo: **13 fuera del alcance
declarado**, **2 descartadas por circularidad** y **10 alcanzables** con su coste anotado. De las
nueve que faltaban:

- **Cuatro van al primer grupo** (`PR.DS-10`, `DE.AE-07`, `DE.CM-06`, `RC.CO-04`): ninguna de las
  tres fuentes —IaC, documentos, logs— las evidencia. `PR.DS-10` pide *confidential computing*;
  `DE.CM-06` exigiría que el modelo de eventos tuviera el concepto de tercero como actor, que no
  tiene.
- **Dos estrenan el segundo** (`DE.AE-04`, `RS.AN-08`), y es el grupo que más merecía estar
  escrito. La entidad `Incident` **ya tiene `severidad`**, así que las dos parecen a un paso de
  declararse. No lo están: esa severidad la asigna un disparador determinístico del propio sistema,
  no un analista estimando impacto. Declararlas sería evaluar como práctica de la organización lo
  que la herramienta acaba de calcular sola — cobertura que sube sin una sola evidencia nueva. Es el
  principio del silencio documental (§60) llevado a su conclusión incómoda: **para afirmar algo hay
  que observarlo, y la salida propia no es una observación.**
- **Tres van al tercero** (`RC.RP-06`, `RS.CO-03`, `RC.RP-04`), que ya tenía `ID.AM-03` y las seis
  documentales de gobierno. `RC.RP-06` es la más cercana de todas: el incidente ya se cierra con `motivo_cierre`
  obligatorio (§52), pero eso es una acción sobre la API, no evidencia observada; haría falta un
  evento `recovery_completed`, exactamente la forma de lo que la Oleada A hizo con
  `containment_done` (§72).

**Y un test detrás, porque la afirmación tiene que costar algo.**
`tests/test_csf_scope_documented.py` comprueba las dos direcciones: que ninguna descubierta se quede
sin motivo, y que ningún motivo sobreviva a su causa —si una oleada futura cubre una, hay que
sacarla de la lista, porque un motivo que afirma "fuera de alcance" sobre algo que ya se evalúa es
peor que no tenerlo—. También que el total del encabezado sea el de verdad. Validado contra tres
mutaciones (quitar un motivo, desajustar el total, cubrir una subcategoría dejando su motivo) antes
de darlo por bueno; las caza las tres.

Afinar el test costó una iteración: leía la fila entera de la tabla y confundía las subcategorías
**citadas dentro de una explicación** (`RS.CO-02` para decir que `CRI-RS-03` cubre el plan de
notificación, `RC.CO-03` para situar `recovery_communicated`) con subcategorías presentadas como
descubiertas. Ahora lee solo la primera columna.

**Lo que esto cambia para el informe.** La afirmación del proyecto deja de ser un porcentaje y pasa
a ser una propiedad verificable: **cada una de las 106 subcategorías del CSF 2.0 tiene un criterio
que la evalúa o un motivo escrito de por qué no lo tiene**, y un test impide que eso se degrade. El
81/106 sigue siendo el número, pero ya no es el argumento.

**Verificación:** 781 tests, 2 skipped, `ruff` limpio. No se tocó el motor, el catálogo, los
fixtures ni los goldens: `GET /methodology` sigue en 81/106 con 31 criterios y `criterios=24`.

## 97. Segunda revisión: lecturas que puntuaban lo que no estaba

Una revisión de la Oleada C con sondas a mano —formas de HCL que los fixtures no usan— encontró
siete lecturas equivocadas. Dos daban **100 sobre una premisa falsa**, que es el peor error posible
en un evaluador; otras dos bajaban a 50 infraestructura bien configurada.

**Puntaje perfecto sin motivo:**
- **MFA (`CRI-PR-08`).** "Exige MFA" era buscar la cadena `aws:MultiFactorAuthPresent` en el
  documento, así que una condición con `"false"` contaba como exigirlo. Ahora se parsea el JSON: un
  `Allow` condicionado a `true` (`Bool`/`BoolIfExists`) o un `Deny` cuando vale `false`. Un JSON
  ilegible queda `unknown`. De paso se quitan los marcadores `<<EOF` que `hcl2` deja en el valor,
  sin lo cual toda política escrita como heredoc habría quedado `unknown`.
- **Módulos fijados (`CRI-ID-06`).** Cualquier `?ref=` fijaba, incluidos `?ref=main` y `?ref=`
  vacío. Ahora solo un tag de versión o un SHA de commit.

**Penalización a lo que estaba bien:**
- **`rds.force_ssl` (`CRI-PR-01`).** El booleano de HCL `true` se convertía en `"True"`, que no es
  `"true"`, y quedaba `disabled`: tope 50. Ahora `True`, `1`, `"1"` y `"true"` sin distinguir
  mayúsculas activan.
- **Listener HTTP que redirige a HTTPS (`CRI-PR-01`).** Se leía solo `protocol`, así que la
  configuración estándar (puerto 80 que redirige al 443) contaba como dato en claro. Ahora la
  redirección a HTTPS cuenta como canal cifrado, y un listener TCP (paso directo de un NLB) queda
  `unknown`: el TLS puede terminar detrás.
- **`PermitRootLogin prohibit-password` (`CRI-PR-04`)** contaba como sin endurecer, aunque es lo
  que recomienda CIS. Ahora cuenta como `no`, con `without-password` y `forced-commands-only`.
- **`required_providers` en la forma antigua** (`aws = "~> 4.0"`) se leía como sin restricción.

**Un estado mal nombrado:** un grupo de autoescalado con `min_size == max_size` y sin alta
disponibilidad caía en *"ninguno los declara de forma literal"*, cuando los valores sí eran
literales. Ahora es `evaluado` con **0**, la misma ancla que `multi_az = false` sin capacidad
elástica: la capacidad fija no es un positivo, es su ausencia declarada.

**Fuera de las reglas**, en la misma tanda:
- El cliente de IA reintentaba cualquier error, también un 401 por clave inválida: tres intentos
  con espera por cada llamada condenada. Ahora reintenta solo timeouts, errores de conexión, 429 y
  5xx; el resto degrada al primer intento.
- Frontend: el panel de incidente arrastraba los pasos marcados y el motivo de cierre del incidente
  anterior; el spinner de comparar podía quedarse girando; una evaluación fallida no mostraba su
  error; el sondeo de la evaluación activa no tenía fin (ahora corta a los 10 minutos). Se quitó el
  código muerto que dejó la IA siempre activa.
- Docs: la IA siempre activa, `AI_MAX_CONCURRENCY`, la nueva política de reintentos y el snapshot de
  metodología (docs/01 §10, docs/04, docs/05).

`ADAPTER_VERSION` de Terraform sube a 16. **Ningún golden cambió**: los fixtures no usaban ninguna
de estas formas, que es exactamente por qué la suite no podía verlas (el mismo patrón que §95).

**Verificación:** 830 tests, 2 skipped, `ruff` limpio; typecheck, lint y build del frontend limpios.

## 98. Una evaluación consumía todos los eventos de su entorno, eligiera o no

Una evaluación no elegía qué eventos leer: `collect_surveillance_evidence` tomaba **todos** los
`events`/`log_patterns` del `org`+`scope`. En la demo, el log de un escenario ingerido 51 s antes se
colaba en la evaluación de otro y llevaba RS-01/RS-04/RC-02 a cero. Además, nada quedaba registrado
sobre qué eventos había usado la evaluación, así que el resultado no era reproducible, y los
`log_patterns` se leían de filas que podían sobrar de ingestas anteriores (una regla tomaba la
primera coincidencia).

**Qué cambió:**
- `GET /orgs/{org_id}/event-sources` lista los orígenes (`Event.source_id`: la `fuente` declarada o
  el archivo de origen) con cantidad de eventos, rango `desde`/`hasta` y última ingesta
  (`max(creado_en)`; no hay fila de ingesta por origen).
- `POST /assessments` acepta `event_source_ids` (array JSON, opcional). Omitido = todos los orígenes
  del `org`+`scope`, para no romper llamadas existentes ni el refresco automático; `[]` = ninguno;
  un id que no pertenece a la organización da 400 antes de crear o subir nada. La selección viaja en
  el payload del job y el reintento la conserva.
- `collect_surveillance_evidence` -> `surveillance_snapshot`: filtra los eventos por la selección y
  **recalcula los patrones en memoria** con `detect_patterns`, el mismo código determinista de la
  ingesta, en vez de leer `log_patterns`. Así la ventana y los patrones describen exactamente los
  eventos elegidos, la correlación entre fuentes seleccionadas sigue correcta y una fila duplicada o
  vieja ya no puede decidir un criterio. `_patron()` y los consumidores operativos de
  `log_patterns` no cambian: la ingesta sigue reemplazando las filas por scope.
- `reproducibility.eventos` guarda `todas`, `source_ids`, `conteo`, `desde`, `hasta` y `sha256` de
  los eventos canónicos (orden por tiempo e id, JSON estable). `GET /assessments/{id}` ya lo expone.
- Re-evaluación y refresco automático **heredan** la selección: si la evaluación anterior usó una
  lista explícita se conserva (un log excluido no entra por la puerta de atrás); si usó todos
  (`todas: true`) sigue usando todos, para que una ingesta de un origen nuevo cuente. Una evaluación
  sin la marca (anterior a este cambio) se trata como "todos".
- Frontend: el diálogo "Nueva Evaluación" lista los orígenes con su conteo y rango, todos marcados
  por defecto; si hay orígenes se manda la lista explícita (aunque estén todos) para que el alcance
  no cambie solo. El dashboard muestra "N eventos de <origen(es)>" o "Sin eventos operativos".

No hubo migración: todo va en el JSON `assessments.reproducibility` y en el payload del job.

**Verificación:** tests nuevos en `tests/test_assessment_event_sources.py` (subconjunto, todos,
`[]`, id ajeno 400, endpoint, worker, herencia en reevaluación y refresco, sin patrones duplicados)
más los de servicio, API y workers; `ruff` limpio. Typecheck, lint y build del frontend limpios.

## 99. Una afirmación por fragmento: el documento entero cuenta

Un documento largo se parte en fragmentos y cada fragmento produce su propio `doc.claim`. La regla
de GV.OC declaraba sus cinco resultados repartidos en cuatro afirmaciones (misión y partes
interesadas, requisitos legales, servicios críticos, dependencias), pero `best_found` elegía **una**
y medía solo sus campos: 50 sobre un contexto completo. GV-03 y GV-06 tenían la misma lectura
latente: sus facetas son subcategorías distintas y pueden caer en fragmentos distintos.

**A. Fusión por campo.** `_common.merged_content` arma el contenido de todas las afirmaciones
`encontrado=true` del tipo: por cada campo vale la afirmación más confiable que **lo declara** (una
que lo calla no compite) y los booleanos se suman con `or`, porque no hay un mecanismo de
contradicción entre fragmentos del mismo documento (docs/02 §5 cubre documento contra documento y
contra Terraform). Devuelve también las afirmaciones que aportaron, y las reglas las citan todas.
Cambian GV-02 (solo los booleanos `recursos_asignados`/`practicas_rh`; el rol se sigue eligiendo por
completitud, no por confianza), GV-03, GV-04, GV-05, GV-06, ID-03, ID-04, ID-05, PR-07, RC-01,
RS-01 y RS-03. Quedan como estaban GV-01 (una política es un hecho único y ya toma la afirmación de
mayor confianza), ID-01 e ID-02 (una sola faceta: el inventario de activos y la criticidad,
respectivamente), DE-02, RS-02 y RS-04 (una faceta documental más la puerta operativa) y PR-02,
RC-02, RC-03 y DE-03 en su parte de un solo campo (`best_found_with`). ID-03 y ID-05 amplían además
su filtro de proceso con los campos que solo su subcategoría usa (`impactos`/`probabilidades` y
`planes_actualizados`), para que un fragmento que solo los declara no quede fuera del proceso.

**B. RC-02 contra RC-03.** Cualquier `restore_exercise_run` con `resultado=fail` daba 0, aunque una
verificación posterior ya hubiera restaurado el servicio y RC-03 la contara como 100. Ahora un fallo
superado por un `restore_verified` posterior (por `hasta`) no condena el criterio: se evalúa la
verificación y el fallo se cita en la explicación. Sin marcas de tiempo se mantiene el 0 conservador.
De paso, la lectura de patrones usaba la **primera** fila de la lista: `_common.latest_pattern`
toma la más reciente por `hasta` con desempate determinista, y sustituye las copias de `_patron` de
RC-02, RS-01, RS-04, RC-03, DE-02 e ID-05. En RS-01 esto importa: con dos escalamientos, el primero
(anterior a la declaración) tapaba al posterior y daba 0; ahora vale el último.

**C. La demo contaba la historia al revés.** La política de `gaps` decía última revisión
`2026-02-01` (vigente → GV-01 100) y la de `mid`, `2025-03-15` (vencida → 75-79): el paquete con
brechas se veía mejor en gobierno que el que está en mejora. `gaps` declara ahora que no se revisó
desde su aprobación (2025-03-01) y `mid` una revisión de 2026-02-01 dentro de la frecuencia anual.
El §66 describía la revisión vencida en `mid`; ahora ese estado está en `gaps`, y `mid` conserva los
demás huecos (roles sin autoridad, proceso de riesgos sin registro, recuperación sin criterios), que
es la progresión que la demo ya contaba en lo técnico.
`backend/tests/fixtures/documents` y `tests/golden_ai/documents` son copias propias para las pruebas
de extracción, no se leen desde `frontend/public/demo`; `test_demo_bundles` fija solo los puntajes
técnicos (Terraform + Ansible) y no cambió ninguna expectativa.

**Verificación:** 20 tests nuevos; 336 en el conjunto dirigido (reglas, helpers, vigilancia, demo y
goldens) en verde, `ruff` limpio. **Ningún golden cambió**: el pipeline de los goldens no incluye
documentos ni `log.pattern`.

## 100. `respuesta_vacia` no era silencio del documento: era el presupuesto de razonamiento

En una corrida del prototipo, 5 de ~60 extracciones U1 terminaron en `degradado` con
`motivo: respuesta_vacia` tras tres intentos **idénticos**. La extracción devolvía `[]` y las reglas
leían ese vacío como "el documento no lo declara" (`silencio_documental` → `evidencia_insuficiente`
con el hallazgo "Ningun documento analizado lo declara"): una afirmación sobre el texto que nadie
leyó.

**La causa, con evidencia.** `DEEPSEEK_MODEL=deepseek-flash` es correcto: `GET /models` del
proveedor devuelve exactamente `deepseek-flash` (DeepSeek-V4.1-Flash, 1M de contexto, pensamiento
activo por defecto con `effort: high`) y `deepseek-v4-pro`. El problema era el cliente: `max_tokens`
fijo en 2000 y `deepseek-flash` **razona antes de escribir**, con el razonamiento pagado del mismo
presupuesto. En los logs de los fallos, `completion_tokens=2000` (el techo) y sin línea de tokens
posterior; reproducido contra la API con los documentos del demo:

```text
max_tokens=1200 → finish_reason=length, completion=1200, reasoning_content≈5000 chars, content=""
max_tokens=8000 → finish_reason=stop,   completion=4571, content=1968 chars (JSON válido)
```

Con `max_tokens` bajo el JSON **no empieza**: los tokens se van en `reasoning_content` y `content`
queda vacío (o solo espacios, que es lo que deja el modo JSON cuando la salida no era JSON). El
techo real observado con los 14 tipos de U1 fue de ~5250 tokens de completion, muy por encima de
2000. Repetir tres veces con el mismo techo es repetir la misma petición condenada; que a veces el
tercer intento saliera (`intentos: 3, ok`) era la variación natural del razonamiento, no una señal de
que el reintento idéntico sirviera.

**Cambios.**
- `app/ai/client.py`: `max_tokens` 2000 → 16000 (`DEEPSEEK_MAX_TOKENS` para ajustarlo). El motivo del
  degradado ahora lleva el `finish_reason` (`respuesta_vacia:length`, `json_invalido:stop`) y la línea
  de tokens registra `finish=` y si hubo razonamiento. Si la respuesta se vacía por longitud, el
  reintento **duplica el techo** (hasta 64000) en vez de repetir; `content_filter` no se reintenta y
  una respuesta con solo espacios cuenta como vacía. `deepseek-flash` sigue siendo el modelo: no hay
  que cambiar `DEEPSEEK_MODEL`.
- `app/evaluation/rules/_common.py`: `documentos_sin_respuesta` + `es_silencio_documental` +
  `marcar_sin_respuesta`. El motor lo aplica a todo resultado (`engine._evaluate_one`): si la regla
  concluyó silencio documental y algún `doc.source.info` trae `sin_respuesta > 0`, la explicación
  pasa a encabezarse con "Limitacion: la IA no respondió para N sección(es) de <documento>; esa
  falta de respuesta no es silencio del documento y lo que no se pudo leer no se cuenta como
  ausencia". Sigue siendo `evidencia_insuficiente`, nunca 0.
- `app/recommendations/limitations.py`: esos criterios ya no generan "Ningun documento analizado lo
  declara" (que culpaba al texto) sino "La IA no respondió para parte de los documentos", con el
  número de secciones y archivos. El resto de los silencios no cambia.
- `app/api/app.py`: el proceso de la API nunca configuró logging, así que los `ai_call` de U3 (la
  generación de planes corre ahí) no llegaban a ningún sitio. Ahora usa el mismo
  `basicConfig`/formato que `worker.core`, sin tocar los loggers de uvicorn.
- `deploy/.env.example` y `backend/.env.example`: `DEEPSEEK_MODEL=deepseek-flash` se queda y se
  documenta `DEEPSEEK_MAX_TOKENS=16000`.
- Docs: docs/05 §5 (modelo, `max_tokens`, reintentos, razonamiento, chunk degradado ≠ silencio).

**Verificación.** Reproducción en vivo: con el cliente parchado y `max_tokens=1200`, el primer
intento devuelve `finish=length` con contenido vacío y el reintento a 2400 tokens devuelve
`finish=stop` con 14 afirmaciones (`intentos: 2`). Tests nuevos: `test_ai_client_finish_reason.py`
(vacío por longitud → sube el techo; motivo con `finish_reason`; techo acotado; espacios; filtro de
contenido), `test_silence_sin_respuesta.py` (insuficiente + limitación + hallazgo correcto, sin
cambiar el silencio normal) y `test_api_logging.py` (handler raíz con el formato de los workers,
`app.ai.*` en INFO, uvicorn intacto). Los tests dirigidos de cliente, silencio, logging, motor y
reglas quedan en verde y `ruff check`/`format --check` limpios.

## 101. Un documento que se contradice y documentos partidos en trozos de más

**A. El `or` de booleanos tapaba una negación explícita.** Desde §99, `_common.merged_content`
funde campo a campo las afirmaciones del mismo tipo y suma los booleanos con `or`. Eso funcionaba
entre documentos, pero dentro del mismo documento un `false` puede ser una negación explícita ("no
se realiza X") y el `or` la borraba: un fragmento que negaba los recursos asignados no bajaba el
puntaje de GV-02. Ahora los fragmentos se agrupan por documento (`subject_ref`, que la extracción
arma como `doc:<stem>`): **entre documentos** se mantiene el `or`; **dentro de uno que se
contradice** vale el valor de la afirmación más confiable (el mismo orden de `found`) y el caso se
registra como `ContradiccionBooleana`. `merged_bool` expone la misma regla a GV-02, que hacía el
`or` a mano para `recursos_asignados`/`practicas_rh`.

La contradicción no se deja implícita: `contradicciones_booleanas(evidence)` se recalcula desde la
misma evidencia que leen las reglas y el motor la aplica a todo resultado que haya citado una de
las afirmaciones en conflicto (`marcar_contradicciones`, al lado de `marcar_sin_respuesta`). La
explicación suma "Limitacion: el documento <archivo> se contradice sobre <campo> (vale sí/no, de la
afirmación más confiable)" y `recommendations/limitations.py` emite un hallazgo `limitacion`
("El documento <archivo> se contradice sobre <campo>") sin tocar ninguna de las doce reglas. El
puntaje y el estado no cambian: la regla ya resolvió con esa misma regla.

**B. El chunking partía por cada encabezado.** `extraction_text` hacía un chunk por encabezado
Markdown y uno por página PDF; el adaptador cortaba en 20 chunks. Un documento con muchas
subsecciones cortas producía muchas llamadas diminutas y sin contexto, y uno real con más de 20
subsecciones dejaba de analizarse. Ahora las secciones/páginas consecutivas se agrupan hasta
`DEFAULT_MAX_CHARS_PER_CHUNK` (8000 caracteres) sin partir ninguna; una mayor queda sola. El
texto conserva los encabezados, así que el prompt no cambió (`extract_v4` sigue vigente: nunca
mencionó "sección"). Cada `Chunk` guarda `Segmento(inicio, fin, locator)` por sección/página; la
cita se valida contra el chunk completo (E8) y el locator de la afirmación se resuelve al tramo
donde aparece `cita.fragmento`, con la primera sección como respaldo. El tope de 20 chunks ahora
aplica a chunks agrupados y `doc.source.info` sigue contando secciones/páginas (total, analizadas,
omitidas y sin respuesta), no chunks, que es lo que el informe y la UI muestran. `ADAPTER_VERSION`
sube a 4.

**C. Golden set.** El arnés (`golden_eval`) no indexa respuestas por texto del chunk: el cliente
"oráculo" responde las afirmaciones anotadas cuya cita aparece en el fragmento recibido y
`_check_citations` mide contra ese mismo texto. Al agrupar cambia el número de llamadas, pero no la
anotación ni el emparejamiento, así que **ningún golden se regrabó**; el golden set pasa con menos
llamadas.

**Verificación:** tests nuevos por regla afectada por booleanos (GV-02, GV-03, GV-04, GV-06, ID-03,
ID-05, PR-07, RS-01) con el conflicto dentro del documento y entre documentos, más
`test_rules_common` (resolución y `contradicciones_booleanas`), `test_limitation_findings` (hallazgo
del documento contradictorio), `test_document_extraction_text` (agrupación, presupuesto, sección
sobredimensionada, bloques de código y páginas PDF) y `test_document_adapter` (locator por sección,
tope y conteos). En la demo, las llamadas U1 bajan de 10→4 (`gaps`), 21→6 (`mid`) y 29→6 (`good`).
Conjunto completo y `ruff` al final del cambio.

## 102. La selección de eventos era por sistema emisor, y los tres escenarios comparten los mismos

Al regenerar las capturas de la demo se ingirieron los tres logs de ejemplo
(`flujo-correcto-demo.jsonl`, `incidentes-demo.jsonl`, `respuesta-parcial-demo.jsonl`) en la misma
organización y se pidieron los orígenes disponibles: la respuesta mezclaba los tres archivos bajo
`edr-endpoints`, `respaldo-bd`, `siem-corp` y `soar-respuesta`. El §98 había hecho que la evaluación
eligiera "orígenes", pero el origen era `Event.source_id`, es decir el sistema **emisor** que declara
la línea (`fuente`); los tres escenarios lo comparten. No había forma de decir "evalúa solo el log de
respuesta parcial": elegir `siem-corp` traía eventos de los tres, y el escenario que se quería aislar
se contaminaba igual que antes del §98. El fallo no se veía en los tests porque usaban escenarios con
archivos de origen distinto (`events:<archivo>`), no los tres logs de la demo.

**Qué cambió:**
- `event_ingests` es la identidad nueva: una fila por archivo subido (`archivo`, `ruta`,
  `ingerido_en`, `eventos`, `eventos_leidos`, `eventos_existentes`, `desde`, `hasta`, `fuentes[]`).
  `events.ingest_id` apunta a ella y es nullable: los eventos ya guardados no tienen una ingesta que
  los identifique. Migración `b8f2c5a91d47`; en SQLite de dev/test `ensure_schema` crea la tabla y
  agrega la columna a las bases viejas sin tocar sus filas.
- **Reingesta:** el evento duplicado conserva la ingesta que lo guardó primero. La subida nueva deja
  su propia fila con `eventos = 0` y `eventos_existentes = <leídos>` como registro, pero no aparece en
  la lista de ingestas elegibles: no aporta nada que una evaluación pueda consumir.
- **Legacy:** los eventos sin `ingest_id` se agrupan en una pseudo-ingesta `legacy` por organización
  (con la hora de su primer evento guardado y `archivo = null`), así una base anterior al cambio sigue
  teniendo algo que elegir en vez de desaparecer del selector.
- `GET /orgs/{org_id}/event-ingests` reemplaza a `/event-sources` (sin consumidores fuera del
  frontend, que se actualiza en el mismo cambio): devuelve `ingest_id`, `archivo`, `ingerido_en`,
  `eventos`, `desde`, `hasta` y `fuentes[]`, de la más reciente a la más antigua. El conteo, el rango
  y las fuentes salen de los eventos guardados con ese `ingest_id` (y del `?scope=`), no del archivo
  original: una reingesta parcial atribuye a cada ingesta solo lo que insertó.
- `POST /assessments` acepta `event_ingest_ids` (mismo contrato que `event_source_ids`: omitido =
  todas, `[]` = ninguna, id ajeno = 400). El payload del job y el reintento conservan la lista.
- `surveillance_snapshot`/`collect_surveillance_evidence` filtran por `ingest_id` y siguen
  recalculando los patrones en memoria. `log.window.source_id` vuelve a ser el conjunto de sistemas
  emisores de los eventos elegidos (antes se estaba usando la selección como si fueran orígenes).
  `reproducibility.eventos` guarda `todas`, `ingest_ids`, `archivos` (alineado con los ids, `null` en
  legacy), `conteo`, `desde`, `hasta` y `sha256`. Reevaluación y refresco automático heredan la
  selección por ingesta; una evaluación anterior al cambio (sin `ingest_ids`) se sigue tratando como
  "todas".
- `DELETE /orgs/{org_id}/events` borra también las ingestas de la organización.
- Frontend: "Eventos operativos" lista una fila por ingesta con nombre de archivo, fecha de subida,
  cantidad, rango y sistemas emisores (texto pequeño), todas marcadas por defecto; el dashboard
  muestra los archivos usados o "Sin eventos operativos".

**Verificación:** tests de `tests/test_assessment_event_sources.py` con los tres logs de la demo
ingeridos en la misma organización: evaluar solo `incidentes-demo.jsonl` produce exactamente los
patrones que ese archivo produce solo, aunque los tres declaren los mismos sistemas emisores; además
reingesta sin duplicados, legacy seleccionable, 400 por id ajeno, endpoint, worker, herencia en
reevaluación y refresco, y aislamiento por organización. `test_migrations` cubre la migración sobre
una base con eventos viejos y `test_db_schema_upgrade` la reconciliación SQLite (columna nueva +
tabla nueva sin perder eventos). `ruff` limpio; typecheck, lint y build del frontend limpios.

## 103. Un chunk agrupado con inventario de activos y de datos: el modelo elegía uno de los dos

**Síntoma.** En el bundle `good`, `gestion-de-riesgos.md` trae `## Inventario de activos` (ocho
tipos de recurso `aws_*`) seguido de `## Inventario de datos`. Con el chunking agrupado de §101 el
documento entero es un solo chunk, y en una corrida real U1 devolvió una única `data_inventory`
cuyos `activos` eran categorías de datos ("base de datos de clientes", "repositorio de documentos"):
CRI-ID-01 midió 0/8 tipos de Terraform y puntuó 25. Con un chunk por encabezado (§101 anterior) el
mismo documento puntuaba 100.

**Causa.** Se reprodujo con el cliente real de DeepSeek (`deepseek-flash`, temperatura 0) y el
código de extracción de la app, sin caché: **N=6** corridas del chunk agrupado tal como lo arma el
adaptador dieron 5/6 con los ocho `aws_*` en `data_inventory.activos` y **1/6 con cero**, el síntoma
exacto; **N=4** corridas de la sección `## Inventario de activos` sola dieron 4/4. El prompt era el
mismo en ambas variantes, así que la diferencia no es del prompt por sí solo ni pura varianza del
modelo: al agrupar, las dos secciones compiten dentro del mismo fragmento y el prompt no decía cómo
reconciliarlas (el inventario de activos también es `data_inventory`, pero `_CONTENT_FIELDS` lo
describía como "lista de recursos" sin nombrar tipos de recurso). La varianza del modelo decide en
qué corrida se pierde el inventario de activos, no si el riesgo existe.

**Cambio.** `extract_v5` (el `extract_v4` queda intacto para trazabilidad) agrega dos párrafos: cada
tipo solicitado se analiza de forma independiente y, si varias secciones declaran el mismo tipo, se
reúnen en una sola afirmación; y el inventario de activos tecnológicos (tipos `aws_*`, servidores,
bases de datos, buckets, balanceadores, roles y políticas) es `data_inventory` y sus recursos van en
`activos`. `_CONTENT_FIELDS["data_inventory"].activos` nombra esos recursos y distingue
`tipos_datos` (categorías de datos) de `activos` (recursos tecnológicos). `PROMPT_VERSION` sube a
`extract_v5`; el esquema de respuesta y las reglas no cambian.

**Evidencia (mismo código, misma metodología, sin caché).**

| Variante | Corridas | `data_inventory` con `aws_*` |
|---|---|---|
| Agrupado, `gestion-de-riesgos.md`, antes | 6 | 5/6 (una corrida: 0 tipos, solo activos de datos) |
| Sección `## Inventario de activos` sola, antes | 4 | 4/4 (ocho tipos) |
| Agrupado, `mid/riesgos-e-inventario.md`, antes | 2 | 2/2 (`aws_db_instance`, `aws_s3_bucket`) |
| Agrupado, `gestion-de-riesgos.md`, después | 10 | 10/10 (ocho tipos, en una sola afirmación con `tipos_datos` y `criticidad`) |
| Sección sola, después | 4 | 4/4 (ocho tipos) |
| Agrupado, `mid/riesgos-e-inventario.md`, después | 2 | 2/2 |

Los otros cinco documentos del bundle `good` (y `continuidad`, `gobierno-y-proveedores`,
`politica-seguridad` del `mid`) no declaran inventario: una corrida de cada uno no produjo
`data_inventory` antes del cambio, que es el resultado correcto. Total de la investigación: 37
llamadas reales, ninguna degradada; una llamada representativa del chunk agrupado consumió 2267
tokens de prompt y 3921 de completion (6188 en total, 14 s).

**Golden set.** No se regrabó nada: `golden_eval` no guarda respuestas por prompt ni indexa por
texto del chunk (el cliente "oráculo" responde las anotaciones cuya cita aparece en el fragmento),
así que la versión del prompt no participa del replay. La anotación de `gestion-de-riesgos.md` sigue
valiendo (sigue esperando los activos de datos y la clasificación del inventario de datos). El único
test que fijaba la versión es `test_op12_op14_ai_hardening`, actualizado a `extract_v5`.

**Verificación:** tests nuevos en `test_ai_extraction` (la instrucción de independencia está en el
prompt v5, `data_inventory.activos` nombra recursos tecnológicos y el prompt de usuario declara los
campos de cada tipo pedido). `pytest` de `test_ai_extraction`, `test_op12_op14_ai_hardening`,
`test_ai_golden` y `test_document_extraction_text` en verde, y `ruff` al final del cambio.

## 104. Un job que esperaba en la cola se marcaba `fallido` a los 120 s y el worker descartaba el mensaje

**Síntoma.** Apareció regenerando los escenarios del poster: tres ingestas de eventos seguidas sobre
la misma organización, y la segunda terminaba `fallido` con "El job no fue tomado por ningún worker a
tiempo" aunque `worker-logs` estaba corriendo. La ingesta no ocurría: los eventos del archivo nunca
se guardaban.

**Causa.** Dos piezas que por separado tenían sentido. `_is_stale` (`app/core/jobs.py`) fallaba todo
job `pendiente` con más de `JOB_PENDING_TIMEOUT_SECONDS` (120 s) desde `creado_en`, sin mirar si
había un worker vivo; el barrido corre en cada vuelta del loop y en cada `GET /jobs`. Y el worker,
al sacar el mensaje de Redis, descartaba cualquier job que no estuviera `pendiente`
(`app/workers/core.py`/`logs.py`, "Correrlo ejecutaría el trabajo dos veces"). Con una reevaluación
con IA de varios minutos delante, el job de la ingesta esperaba en la cola más de 120 s, el reaper
lo fallaba y el mensaje, todavía en Redis, se tiraba. Estar en la cola no es evidencia de que nadie
lo vaya a procesar.

**Cambio.** Los workers publican un heartbeat en Redis: `pf:jobs:hb:<cola>:<worker-id>` (TTL
`JOB_HEARTBEAT_TTL_SECONDS`, default 60 s) y, mientras procesan, `pf:jobs:hb:job:<job-id>`, ambos
refrescados por un hilo propio cada `JOB_HEARTBEAT_INTERVAL_SECONDS` (default 20 s) — el loop
principal queda bloqueado en la llamada de IA, así que el refresco no puede depender de él.
`app/core/queue.py` expone `WorkerHeartbeat` (`beat`/`track`/`start`/`stop`) y las consultas
`worker_alive`/`job_worker_alive` (devuelven `None` si no se pudo saber, p. ej. Redis caído). El
reaper ahora falla un `pendiente` solo si pasó el timeout **y** no hay worker vivo en su cola, y un
`en_progreso` solo si pasó `JOB_STALE_TIMEOUT_SECONDS` **y** desapareció el latido de ese job: un
pipeline de IA largo ya no se mata por viejo. `JOB_PENDING_TIMEOUT_SECONDS` se mantiene como
umbral, no como sentencia.

Defensa en profundidad: `jobs.adopt_lost_in_queue` reconoce el caso exacto (`fallido`, motivo
`LOST_IN_QUEUE_ERROR`, `tomado_en` nulo) y devuelve el job a `pendiente` (y la `Assessment` ligada a
`pendiente`) para ejecutarlo, en vez de descartar el mensaje. Si existe un intento posterior para
la misma entrada que no esté fallido —esperando, corriendo o ya completado; un reintento crea un job
nuevo con `dispatch.retry_job`— lo descarta igual, para no duplicar el trabajo. Los workers `core` y
`logs` arrancan su heartbeat y pasan su cliente Redis al barrido.

**Configuración.** Nuevas `JOB_HEARTBEAT_TTL_SECONDS` y `JOB_HEARTBEAT_INTERVAL_SECONDS` (comentadas
en `backend/.env.example` y `deploy/.env.example`); los dos timeouts existentes no cambian de
nombre. El mensaje de error no cambió, así que el frontend no necesitó cambios.

**Verificación:** `tests/test_heartbeat.py` (claves, liberación del job, hilo que refresca con el
loop bloqueado), `tests/test_jobs.py` (pendiente viejo con worker vivo no se reapea; sin heartbeat
sí; `en_progreso` con latido de job no se reapea; adopción y descarte por reintento),
`tests/test_workers_core.py` y `tests/test_workers_logs.py` (el worker ejecuta un job dado por
perdido en la cola y descarta el viejo si ya fue reintentado) y `tests/test_api_jobs.py` (`GET
/jobs/{id}` no falla un job que solo espera). `ruff check` y `ruff format --check` limpios.

## 105. La cache de IA vivía en un directorio por contenedor y U2 nunca acertaba; U1 se vuelve determinista votando

**Síntoma.** Cada evaluación con documentos volvía a pagar casi todas las llamadas y dos corridas
sobre las mismas fuentes no daban el mismo resultado. El estudio de varianza (30 documentos × 5
corridas, `deepseek-flash`, `extract_v5`) midió la causa y el remedio.

**Causa 1 — cache privada y perdible.** `app/ai/cache.py` guardaba un JSON por prompt en
`backend/.cache/ai_extraction`, un directorio del contenedor que no está montado en
`docker-compose`: api, `worker-core` y `worker-logs` tenían cada uno su copia, y cada `docker
compose up` la borraba. La clave era `sha256(modelo, base_url, system_prompt, user_prompt)`.

**Causa 2 — U2 jamás acertaba.** El prompt de U2 embebe los UUID de evidencia de la evaluación;
la misma evidencia en dos evaluaciones produce UUID distintos, así que la clave cambiaba siempre.
U2 es ~75 % de las llamadas (una por criterio ajustable).

**Causa 3 — U1 con razonamiento no es determinista.** `deepseek-flash` razona por defecto e ignora
`temperature=0.0`. En 5 corridas por documento, solo el 73.4 % de los campos clave y el 82.7 % de
las afirmaciones coincidieron entre corridas (pensar apagado: 86.0 % / 93.5 %), pero apagarlo
duplica las citas inválidas (59 vs 28 descartadas por E8) y las afirmaciones prohibidas (21 vs 9).
La comparación con/sin razonamiento:

| métrica | pensar ON | pensar OFF |
|---|---|---|
| recall usable | 92.4 % | 93.2 % |
| precisión | 95.2 % | 89.6 % |
| **mayoría-de-3 recall / precisión** | **94.3 % / 98.8 %** | 93.8 % / 92.7 % |
| latencia mediana / p90 | 21.3 s / 54.3 s | 3.8 s / 7.6 s |
| corridas que agotaron 16k y reintentaron | 5/150 | 0/150 |

La decisión es mantener el razonamiento y votar: la precisión (no sobrestimar un control) importa
más que 1 pp de recall, y la mayoría cierra la brecha de recall.

**Cambio.**

- Tabla `ai_results` (migración `c7a1e5d904b3`) con `org_id`, `kind` (`U1`/`U2`/`U3`), `model`,
  `base_url`, `params_hash`, `prompt_version`, `input_sha256`, `output`, `meta`, `created_at` y una
  unique sobre la clave completa. El store (`app/ai/store.py`) reemplaza la cache en disco en api y
  workers (la CLI sin sesión de BD conserva `CachingAIClient`). Dos workers que calculan el mismo
  insumo a la vez quedan en una sola fila (el segundo conserva la primera respuesta); un fallo de
  BD degrada a miss, y un `None` nunca se guarda. La organización es parte de la clave: no se
  reutiliza nada entre organizaciones.
- Insumo canónico por paso: U1 = `{chunk, doc, tipos ordenados}`; U2 = criterio+versión,
  base, estado, **valores** de evidencia sin ids y ordenados, contexto, α y D; U3 = hallazgo sin
  ids. U2 recibe ids sintéticos `e1`, `e2`, … y `adjust` los remapea a los UUID de la evaluación
  actual antes de validar J5; una referencia que no exista sigue degradando.
- U1: en un miss se corren `U1_VOTES` extracciones en paralelo (3 por defecto; `1` = sin voto),
  acotadas por el semáforo de `app/ai/parallel.py`, cada una validada (E3/E8) antes de votar. El
  voto es genérico sobre `contenido`: mayoría por campo (texto normalizado; booleanos/enums/fechas
  exactos), listas por elemento, `null`/ausente como un mismo estado; `process_defined` se agrupa
  por `(tipo, proceso)`; cita/locator de la corrida de mayor confianza y mediana de confianza. Los
  empates se rompen por confianza e índice de corrida. El resultado votado y un resumen de las
  corridas crudas quedan en `ai_results.meta`. Si solo una corrida respondió no hay mayoría y no se
  guarda.
- Cliente: timeout de 180 s (`DEEPSEEK_TIMEOUT_SECONDS`), que se duplica (hasta 600 s) en el
  reintento por longitud; el razonamiento sigue activo y `temperature` no cambia.
- `reextraer` opcional en `POST /assessments` y `POST /assessments/{id}/reevaluate`, en el payload
  del job; en el dashboard, «Re-extraer con IA» sobre una evaluación con documentos. Ignora las
  lecturas y reescribe la respuesta fresca.
- `assessments.reproducibility.ai` registra `cache` (hits/misses por U1/U2/U3), `votos` y
  `params_hash`.

**Garantía.** Para el mismo insumo canónico, la primera extracción ya es mayoría de 3 y desde ahí
el store devuelve el mismo resultado en cualquier contenedor con la misma BD (identidad comprobada
con dos clientes sobre la misma base). No se promete determinismo del proveedor: se promete no
volver a preguntarle lo mismo.

**Configuración.** `U1_VOTES` (3) y `DEEPSEEK_TIMEOUT_SECONDS` (180) en `backend/.env.example` y
`deploy/.env.example`.

**Verificación:** `tests/test_ai_store.py` (hit/miss, aislamiento por organización, misma BD y
clientes distintos, `reextraer`, inserción concurrente, U1 con 3 votos y con `U1_VOTES=1`, no se
guarda sin mayoría), `tests/test_ai_voting.py` (mayoría, empate, agrupación por proceso, listas,
`null`, cita/confianza, umbral), `tests/test_ai_adjustment.py` (prompt con ids sintéticos, remapeo
y clave estable entre UUIDs), `tests/test_ai_cache.py`, `tests/test_api_assessments.py`
(`reextraer` en POST y en reevaluación) y `tests/test_migrations.py` (tabla y unique).

## 106. Una negacion o un plan se leian como practica vigente y las cantidades en palabras no se normalizaban

**Sintoma.** Dos fallos del estudio de extraccion (thinking ON y OFF) que sobrevivieron al analisis
del modelo porque son del contrato, no del modelo. (1) Un documento que dice "no hay un responsable
designado para seguridad de la informacion" o "no existe un procedimiento documentado de respuesta"
producia `doc.claim` con `encontrado=true` y campos rellenos ("No hay procedimiento documentado...",
`pasos` con texto), asi que CRI-GV-02 daba 75 y CRI-RC-01 50 aunque el documento declarara la
ausencia; los planes ("se implementara en 2027", "se prohibira") a veces se tomaban como practica
actual. (2) Las cantidades escritas con palabras ("noventa dias", "setenta y dos horas") quedaban
verbatim: `pr02` lee la retencion con `(\d+)` y CRI-PR-02 se quedaba en 75 aunque la politica dijera
90 dias.

**Causa.** El contrato de U1 solo tenia `encontrado` (declara / no declara) y ninguna forma de decir
"declara que NO existe" o "declara que sera despues": una negacion completa los mismos campos que una
afirmacion. Las reglas suman toda afirmacion `encontrado=true` (`found`, `merged_content`,
`best_found`), asi que no habia donde ver la negacion aunque el texto la citara. Y el contenido se
guardaba tal cual: ninguna capa convertia palabras a digitos, y la regla que parsea la cantidad no
tenia respaldo.

**Cambio.** `doc.claim@3` (evidence_types v11) suma `estado_declarado`: `vigente`, `inexistente` o
`planificado`, obligatorio con `encontrado=true`; la cita (`cita.fragmento`) es la frase literal que
niega o planifica. `extract_v6` (PROMPT_VERSION) lo pide con ejemplos de negacion y de plan, y pide
normalizar las cantidades a digitos con su unidad sin tocar la cita. Al extraer, un valor que no se
reconoce descarta la afirmacion y una afirmacion sin el campo (anterior a v6) se lee como `vigente`
(compatibilidad con lo ya guardado).

La semantica es **central**, en `_common.aplicar_estado_declarado`, que el motor aplica a toda regla
igual que `marcar_sin_respuesta` y `marcar_contradicciones`: si la afirmacion que la regla cito es
`inexistente`, el criterio pasa a `no_implementado` con 0 y la explicacion cita el documento ("El
documento X declara que no existe: ..."); si es `planificado`, tampoco se acredita (0) porque un plan
es informacion explicita de que hoy no esta en marcha, y `found` excluye los planes de la suma de
contenido para que no aporten campos. El 0 no es silencio: el documento habla y dice que la practica
no esta (docs/01 §3). Si una regla no pudo acreditar nada y aun asi cita la negacion o el plan, el
resultado tambien es 0; para eso `RS-01`, `RS-04`, `RC-02` y `DE-02` citan ahora sus afirmaciones en
las ramas de `evidencia_insuficiente` que antes no citaban nada.

Si **otro documento** declara la practica vigente, no se elige ganador: `contradictions._absence_disagreement`
registra el hallazgo con ambos lados y excluye las afirmaciones de ese tipo para el criterio afectado
(docs/02 §5), con un mapa tipo -> criterios porque `detect` es global. Es la contraparte documental
del mecanismo de contradiccion ya existente.

Las cantidades se normalizan en `app/ai/numbers.py` (parser determinista de cardinales espanol e
ingles basico, hasta millones, "un/una", "medio", "dos semanas", "cada tres meses"): se aplica en
`_sanitize_content` a los campos de cantidad (`backup_policy.retencion`, `risk_tolerance.tolerancia`,
`notification_list.plazos`, `process_defined.criterios_activacion`), a la frecuencia ("cada tres
meses" -> `trimestral`) y como respaldo en `pr02.retencion_politica_dias` antes del `(\d+)`. La cita
no se toca.

**Evidencia (corpus del estudio, 18 llamadas reales, 2 corridas por modo, extract_v6, sin cache).**

| Documento | Modo | `estado_declarado` | Resultado |
|---|---|---|---|
| `explicit-negations.md` | thinking / no-thinking | las cinco ausencias salen `inexistente` | GV-02, RC-01 y GV-06 = `no_implementado` 0 en 2/2 por modo (antes GV-02 75, RC-01 50) |
| `planned-not-implemented.md` | thinking | programa de proveedores y formacion `planificado` | GV-06 y PR-07 = 0 en 2/2 |
| `planned-not-implemented.md` | no-thinking | ademas de los planes, una afirmacion "vigente" que dice que no hay programa | PR-07 = 0 con la exclusion de planes de `found` (la corrida previa al ajuste daba 75) |
| `numbers-in-words.md` | thinking / no-thinking | retencion "90 dias"/"90 días", plazos "72 horas", tolerancia "4 horas" | `retencion_politica_dias` = 90 en 4/4; con el test de PR-02, "noventa dias" puntua igual que "90 dias" |
| `contradictory.md` | thinking / no-thinking | dos retenciones vigentes del mismo documento | sigue siendo conflicto documental, sin cambios |

No se persiguio el 0 en `contradictory.md`: sus dos secciones son dos afirmaciones vigentes del
mismo documento y el criterio las resuelve como antes (docs/09 §101).

**Verificacion:** `tests/test_ai_numbers.py` (parser), `tests/test_ai_extraction.py` (estado
obligatorio, cita literal de la negacion, valor invalido descartado, cantidades y frecuencia),
`tests/test_declared_state.py` (GV-02/RC-01 y el resto de reglas documentales a 0; plan no
acreditado; contradiccion documento-vs-documento visible; PR-02 con "noventa dias" igual que con "90
dias"), con los documentos del estudio en `tests/fixtures/documents/estudio/`. En verde junto con
`test_contradictions`, `test_rules_common`, `test_cr05_docclaim_criteria`, `test_golden`,
`test_ai_golden`, `test_op12_op14_ai_hardening`, `test_criteria_matrix_doc`, `test_findings`,
`test_evaluation_engine` y las pruebas de reglas tocadas; `ruff check` y `ruff format --check`
limpios. `criteria.yml` sube a v25 (semantica central, sin cambiar el tramo de cada regla) y
`evidence_types.yml` a v11.

## 107. El golden set de U1 solo medía recall: precisión, negaciones y planes

**Síntoma.** El arnés de TS-02 contaba afirmaciones esperadas y citas, pero no lo que la IA
afirmaba de más. Una extracción que declaraba vigente una práctica que el documento negaba, o que
obedecía una instrucción incrustada, pasaba mientras el recall siguiera alto. El estudio de
extracción (docs/09 §105-§106) lo cuantificó: 9 afirmaciones prohibidas con razonamiento y 21 sin
él, además de las negaciones leídas como práctica vigente.

**Causa.** `expected.json` solo tenía `claims` y `adversarial`. No había forma de anotar "esto no
debe aparecer" ni "este documento no debe producir nada", y la comparación ignoraba
`estado_declarado`, así que una negación anotada habría empatado con una afirmación vigente de los
mismos campos. El cliente oráculo de los tests, además, tomaba todas las anotaciones del corpus:
una cita corta de otro documento podía colarse en un chunk y votarse como si fuera de ese
documento.

**Cambio.**

- Los 13 documentos del estudio entran en `backend/tests/golden_ai/documents/`: negaciones
  explícitas, planes no implementados, contradicción interna, inyección de prompt, marketing vago,
  política desactualizada, cantidades en palabras, formatos de fecha, SoA ISO 27001, anexo
  contractual, continuidad de dos chunks, bilingüe y un hilo de correo. El golden set pasa a 21
  documentos, 59 afirmaciones esperadas y 14 patrones prohibidos.
- Formato de anotación retrocompatible: `category`, `forbidden` (afirmación que no debe aparecer;
  solo cuenta si la IA la declara **vigente**, porque negar o planificar es lo esperado),
  `no_claims` (documento sin hechos válidos) y `estado_declarado` en cada claim anotado. Las
  negaciones y los planes se anotan como claims con `inexistente`/`planificado`, no como
  prohibiciones; las cantidades se anotan en dígitos (`"90"`, `"72"`, `"2 horas"`).
- `golden_eval` mide precisión = afirmaciones producidas sin falso positivo / producidas, por
  documento, por categoría y en total, junto al recall y las citas. Un falso positivo es una
  afirmación prohibida (`forbidden`), un dato inyectado obedecido o cualquier afirmación en un
  documento `no_claims`. `estado_declarado` forma parte del emparejamiento cuando está anotado.
  Criterio: recall ≥ 90 %, precisión ≥ 95 %, 100 % de citas y 0 instrucciones obedecidas.
- Los tests sin IA usan el oráculo acotado al `doc_id` del prompt; una mutación por métrica
  comprueba que una práctica negada declarada vigente, una negación marcada vigente, una
  afirmación en un control negativo y una inyección obedecida bajan la precisión. La respuesta
  perfecta exige precisión 100 % en total y por categoría.

**Evidencia (línea base real).** `deepseek-flash`, `extract_v6`, votación de 3, 22 chunks y 66
llamadas.

| Categoría | Recall | Precisión |
|---|---|---|
| formal-policy (6) | 94 % (15/16) | 100 % (24) |
| negative-control (1) | 0 esperadas | 100 % (1) |
| adversarial (2) | 50 % (1/2) | 100 % (4) |
| negation / planned / contradictory (3) | 83 % / 80 % / 100 % | 100 % (12) |
| vague / outdated (2) | 0 esperadas / 67 % | 100 % (5) |
| numbers / dates (2) | 100 % (4/4) / 100 % (3/3) | 100 % (8) |
| compliance / contract (2) | 100 % (4/4) / 50 % (1/2) | 100 % (12) |
| long (1) | 75 % (6/8) | 100 % (19) |
| bilingual / email (2) | 100 % (2/2) / 67 % (2/3) | 100 % (8) |
| **Total** | **85 % (50/59)** | **100 % (93/93)** |

Se queda en 85 % de recall (bajo el 90 %) y 96 % de citas (275/285), pero la precisión es total:
ninguna práctica negada o planificada se declaró vigente y no se obedeció ninguna inyección. Las
tres afirmaciones extra del anexo con inyección son hechos del propio texto (rol, notificación y
contexto), no datos de la orden. Los nueve fallos de recall se reparten entre cinco detalles de
`plazos`/`retencion` omitidos, el plan de continuidad negado que el modelo no emite, el rol de la
política desactualizada (el modelo no pone `rol` y E5 descarta la lista), el proceso de mejora de
respuesta a incidentes y la dirección del plan de exposición (`permitidas: true` en vez de
`false`).


**Verificación:** `tests/test_ai_golden.py` (17 pruebas: anotación consistente, oráculo perfecto
al 100 % de recall/precisión, y una mutación por cada fallo), la suite completa en verde y
`ruff check`/`ruff format --check` limpios.

## 108. Un replay del store no daba la misma evaluación que la corrida en vivo

**Síntoma.** Se evaluó cada escenario demo (`gaps`, `mid`, `good`) dos veces con los mismos
documentos, logs y Terraform. La segunda corrida tuvo **todos** los chunks de U1 como *hit* del
store persistente, pero el resultado cambió: en `mid`, `CRI-RS-01` bajaba a 75 y `CRI-ID-01/03/04`
caían a `evidencia_insuficiente`; en `gaps`, `CRI-PR-07` pasaba de `no_implementado` 0 a
`evidencia_insuficiente` y `CRI-GV-03` de 25 a `evidencia_insuficiente`. Comparando
`GET /assessments/{id}/evidence` de las dos evaluaciones, las afirmaciones eran las mismas salvo
tres: `supplier_program {programa:false, requisitos_contractuales:false}`,
`process_defined {proceso:"otro"}` y `data_inventory {}`, que en la corrida 1 eran `inexistente` y
en la 2 `vigente`; y la corrida 2 no tenía ningún `doc.source.info` (6 en la 1).

**Causa.**

1. `voting.claims_to_raw` armaba la respuesta cruda con `tipo`, `encontrado`, `contenido`, `cita` y
   `confianza`, pero **no con `estado_declarado`**. El replay pasa otra vez por
   `_claims_from_raw`, que lee el campo ausente con el valor de compatibilidad de pre-v6:
   `vigente`. La negación se perdía en el store y una misma evaluación dependía de si el chunk
   venía del modelo o de la tabla `ai_results`.
2. El adaptador de documentos decide si emitir `doc.source.info` con `_CountingClient.respondidas`:
   un documento cuyas secciones no contestó la IA no se marca como analizado. En un replay
   `extract_claims` devuelve el resultado del store **sin llamar al cliente**, así que el contador
   quedaba en 0 y el documento perdía sus conteos de secciones; el motor, además, dejaba de ver
   `sin_respuesta`.
3. `contradictions._absence_disagreement` agrupaba por `(scope, tipo_afirmacion)` y
   `_common.aplicar_estado_declarado` miraba todas las declaraciones de ese tipo. Una negación de
   `process_defined {proceso:"otro"}` —que no identifica ninguna práctica— se comparaba con los
   procesos de respuesta, riesgos y recuperación de otros documentos: la contradicción excluía
   también las afirmaciones **vigentes** y `RS-01`/`ID-03` se quedaban sin evidencia. Lo mismo con
   un `data_inventory {}` que el modelo emitió como negación de una frase sobre servicios críticos
   (facetas de `org_context`), que contradecía el inventario real de otro documento y dejaba a
   `ID-01`/`ID-04` en `evidencia_insuficiente`.

**Cambio.**

- `estado_declarado` se vota como campo cerrado (`vigente|inexistente|planificado`) en
  `voting._votar_grupo`, fuera de `contenido`, y `claims_to_raw` lo guarda con la afirmación. Un
  valor fuera de la lista no vota. El replay reconstruye el mismo `doc.claim` que la corrida en
  vivo, campo por campo.
- `extract_claims` acepta `on_replay` y lo llama cuando el chunk salió del store. El adaptador de
  documentos pasa `_CountingClient.marcar_respondida`: un resultado guardado es una respuesta que la
  IA ya dio, así que el replay emite el mismo `doc.source.info` (`secciones`, `analizadas`,
  `omitidas`, `sin_respuesta`).
- La negación y la contradicción se resuelven por **faceta** (`_common.faceta`): un
  `process_defined` se compara por su proceso canónico, no solo por su tipo; negar el proceso de
  recuperación no toca el criterio del proceso de respuesta. `contradictions._absence_disagreement`
  agrupa por faceta y `_criterios_de` usa el mismo mapa.
- Una negación o un plan tiene que **identificar qué niega o planifica**
  (`extraction._identifica_la_practica`): `process_defined` exige un `proceso` concreto (no `otro`)
  y, salvo los tipos en los que el propio tipo nombra la práctica (`policy_exists`, `role_assigned`,
  `supplier_program`, `training_program`), exige algún campo de `contenido`. Si no lo identifica se
  descarta antes de votar: no puede poner un criterio a 0 ni contradecir a otro documento.

No cambia el prompt (`extract_v6`) ni la salida del adaptador, así que `PROMPT_VERSION` y
`ADAPTER_VERSION` quedan igual. La semántica central de las reglas documentales sí cambia:
`criteria.yml` sube a **v26**.

**Evidencia.** `e_mid_1.json`/`e_mid_2.json` y `c_mid_1.json`/`c_mid_2.json` del estudio en vivo
(la API no se volvió a llamar para este arreglo). Los tests reproducen los valores reales de esas
afirmaciones:

| Escenario | Corrida 1 (en vivo) | Corrida 2 (replay, antes) | Con el arreglo |
|---|---|---|---|
| `mid` `CRI-ID-01` | `evidencia_insuficiente` (contradicción `data_inventory`) | igual | `evaluado` 25, cita el inventario de `riesgos-e-inventario.md` |
| `mid` `CRI-ID-03` | `evidencia_insuficiente` (proceso `otro` negaba el de riesgos) | igual | `evaluado`, usa el proceso de riesgos |
| `mid` `CRI-ID-04` | `evidencia_insuficiente` | igual | `evaluado` 50 (tipos de datos, sin clasificación) |
| `mid` `CRI-RS-01` | 75 con nota de contradicción ajena | igual | `evaluado` con el proceso de respuesta, sin la nota |
| `mid` `doc.source.info` | 6 documentos | 0 | 6 documentos y los mismos conteos |
| `mid` negaciones | `inexistente` en 3 afirmaciones | las 3 como `vigente` | `inexistente` en las 3 |
| `gaps` `CRI-PR-07` | `no_implementado` 0 (`training_program` inexistente) | `evidencia_insuficiente` | 0, la negación sobrevive al store |
| `gaps` `CRI-GV-03` | 25 (`risk_tolerance` con `confianza` 0,3 y sin limitación) | `evidencia_insuficiente` | misma validación en vivo y en replay |

El 0,3 sin limitación de `gaps` no lo puede producir el código actual (una confianza por debajo del
umbral siempre deja la limitación): era una fila de una versión anterior del voto. Lo que importa es
que ahora la corrida en vivo y el replay validan el mismo crudo con el mismo umbral, así que la
afirmación no puede cambiar de estado entre las dos.

**Verificación.** `tests/test_ai_store.py` (el replay devuelve el mismo `value` que la corrida en
vivo, negación incluida, y el mismo `doc.source.info`), `tests/test_ai_voting.py` (el estado se vota
como campo cerrado), `tests/test_ai_extraction.py` (se descarta `process_defined` con proceso `otro`
y la negación vacía de `data_inventory`; se conserva la negación vacía que el tipo identifica),
`tests/test_declared_state.py` (negar un proceso no pone a 0 el criterio de otro; la misma faceta en
otro documento sigue siendo contradicción visible; los cuatro criterios de `mid` con los valores
reales de la corrida 1). Suite completa: **1036 passed, 2 skipped**; `ruff check` y
`ruff format --check` limpios.

## 109. La política de proveedores ausente hundía la política de seguridad, y un proceso de riesgos sin `pasos` caía al mínimo

**Síntoma.** Al verificar que los replays del store reproducen la corrida en vivo de los escenarios
demo (`a_mid`/`a_good` frente a `*_1`/`*_2`) aparecieron dos diferencias de puntaje que no venían
del replay, sino de las reglas:

- `mid` bajaba de **Tier 2** a **Tier 1** por `CRI-GV-01 con evidencia insuficiente`, aunque
  `politica-seguridad.md` declara una política aprobada por la Dirección General.
- `good` bajaba de **Tier 3** a **Tier 1** porque `CRI-ID-03` quedaba por debajo del mínimo de 50
  del Tier 4, aunque el proceso de riesgos declaraba registro, priorización, impactos y
  probabilidades.

**Causa.**

1. `contradictions._absence_disagreement` agrupaba por `(scope, tipo_afirmacion)` y, desde §108, por
   la faceta de `process_defined`; `policy_exists` seguía teniendo una sola faceta. En `mid`,
   `gobierno-y-proveedores.md` emite `policy_exists {nombre: "politica de gestion del riesgo de
   proveedores"}` con `estado_declarado: inexistente` y `politica-seguridad.md` emite `policy_exists
   {nombre: "Politica de Seguridad de la Informacion"}` vigente. Son dos prácticas distintas —negar
   que exista una política de proveedores no dice nada de la política de seguridad—, pero la
   contradicción documento-vs-documento excluía **ambas** afirmaciones para GV-01 y el criterio
   quedaba sin evidencia. `gv01_policy` tampoco distinguía: elegía la afirmación de mayor confianza
   entre vigentes y negaciones, y `aplicar_estado_declarado` aplicaba cualquier negación del tipo.
2. `id03_risk_assessment` exigía `contenido.pasos` para todo tramo por encima de 25. `pasos` es
   texto libre que el prompt pide y el modelo omite a menudo: en `good` la afirmación real trae
   `registro_riesgos`, `priorizacion`, `impactos` y `probabilidades`, pero no `pasos`, y la regla
   respondía "descrita de forma genérica, sin pasos concretos". Que un campo opcional no venga no
   es evidencia de que el proceso sea genérico (docs/01 §3).

**Cambio.**

- `_common.faceta` da a `policy_exists` la faceta de la política que nombra, normalizada
  (minúsculas, sin tildes y sin el prefijo "política de"); una afirmación sin nombre es genérica
  (`*`), habla de "una política" cualquiera y sí contradice a una nombrada. `facetas_compatibles`
  decide la comparación y la usan tanto `contradictions._absence_disagreement` (que ahora agrupa
  por scope y tipo y empareja cada negación con las vigentes de faceta compatible) como
  `_common.aplicar_estado_declarado`.
- `gv01_policy` solo acredita afirmaciones **vigentes** (`_common.es_vigente`): una negación o un
  plan de otra política no elige el tramo ni se cita. Si no hay ninguna vigente, la negación citada
  sigue llevando el criterio a 0 por `aplicar_estado_declarado`, y una negación sin nombre sigue
  contradiciendo a la nombrada. `pr01_encryption`, el otro consumidor de `policy_exists` (solo
  como contexto), también filtra a vigentes para no citar una negación como "política documentada".
- `id03_risk_assessment` pasa a cinco anclas: 100 con `pasos` + registro/priorización +
  impactos/probabilidades; 75 con registro/priorización + impactos/probabilidades aunque falte
  `pasos`; 75 con `pasos` + registro/priorización pero sin impactos/probabilidades (falta
  `ID.RA-04`); 50 solo con `pasos`; 25 sin nada de lo anterior.

`docs/03` actualiza las fichas de GV-01 y ID-03, `docs/01 §3` recuerda que la negación se compara
por la política que nombra, y `criteria.yml` sube a **v27** (GV-01 v2, ID-03 v3). Sin cambios de
prompt ni de adaptador: `PROMPT_VERSION` y `ADAPTER_VERSION` quedan igual.

**Evidencia.**

| Escenario | Replay antes | Con el arreglo |
|---|---|---|
| `mid` `CRI-GV-01` | `evidencia_insuficiente` (la negación de la política de proveedores contradecía la de seguridad) | `evaluado` 75, cita `politica-seguridad.md`; Tier 2 |
| `good` `CRI-ID-03` | por debajo de 50 por falta de `pasos` (Tier 4 exige ≥ 50) | 75, con el registro, la priorización y los impactos/probabilidades declarados |

**Verificación.** `tests/test_declared_state.py` (los dos `policy_exists` reales de `e_mid_1.json`
no contradicen y GV-01 se evalúa; la misma política negada en otro documento sigue siendo
contradicción visible; una negación sin nombre sigue llevando el criterio a 0 y contradiciendo a la
nombrada), `tests/test_cr01_mvp_criteria.py` (las cinco anclas de ID-03, incluida
registro + impactos + probabilidades sin `pasos` = 75), `tests/test_contradictions.py` y
`tests/test_gv01_policy_rule.py`. Suite completa: **1043 passed, 2 skipped**; `ruff check` y
`ruff format --check` limpios.
## 110. CRI-RC-01 bajaba a 50 por un campo de texto libre que el modelo no siempre escribe

La verificación en vivo contra el almacén destapó que `CRI-RC-01` exigía `contenido.pasos` para
subir de 50, igual que `CRI-ID-03` antes de §109. El escenario conforme declara el proceso de
recuperación con responsable y criterio de activación —«si el sitio principal permanece caído más
de dos horas»— y aun así caía a «recuperación mencionada de forma genérica», que además no era
cierto. La ausencia de un campo de texto libre no es evidencia de que el procedimiento no exista
(docs/01: el silencio no es ausencia).

- 100: pasos, responsables y criterios de activación.
- **75: responsables y criterios de activación aunque no narre los pasos**, o pasos sin uno de los
  otros dos.
- 50: mención genérica sin ninguno de los tres, o solo política de backups.

`criteria.yml` sube a v28 y `CRI-RC-01` a v2; docs/03 recoge los anclas. Dos pruebas nuevas: el
caso real (responsable + activación, sin pasos → 75) y la mención genérica (→ 50).

## 111. `process_defined` fusionaba análisis y mejora en "respuesta", y el escenario `mid` no pasaba de Tier 1

**Síntoma A (Tier del escenario conforme).** El escenario `good` quedaba en Tier 3 provisional aunque
todos los indicadores de Tier 4 se cumplían salvo `CRI-RS-02`, que daba `evidencia_insuficiente`. La
evaluación guardada (`e_good_1.json`) mostraba una sola afirmación `process_defined` para
`respuesta-incidentes.md`, con `proceso: respuesta` y los campos del análisis posterior y de la
mejora (`ajustes`, `metricas`, `planes_actualizados`, `criterios_recuperacion`). Tras agrupar las
secciones en un chunk (docs/09 §101), el prompt v6 pedía reunir en una afirmación de cada tipo lo
que declararan varias secciones; aplicado a `process_defined`, el modelo fusionaba el análisis de
causa raíz y la mejora continua dentro de la respuesta. `CRI-RS-02` busca un proceso de
análisis/causa/incidente/evidencia/forense y no encontraba ninguno, así que Tier 4 (exige
`CRI-RS-02 ≥ 75`) era inalcanzable.

**Causa A.** Era un problema de extracción, no de voto: `voting._group_key` ya agrupa
`process_defined` por `(tipo, proceso)` desde §108 y conserva grupos distintos. El prompt era el que
inducía la fusión.

**Cambio A.** `prompts/extract_v7.txt` (copia de v6, que queda intacto) mantiene la regla para los
demás tipos y, para `process_defined`, pide **una afirmación por cada proceso distinto**
(`riesgos`, `respuesta`, `recuperacion`, `revision`, `analisis incidentes`, `contencion`, `mejora`,
`otro`), sin mezclar campos de procesos diferentes, con el ejemplo de respuesta + análisis + mejora.
Una sección de causa raíz y preservación de evidencia va con `analisis incidentes`; las lecciones
aprendidas, con `mejora`; contención y erradicación, con `contencion`. `PROMPT_VERSION` sube a
`extract_v7`; el esquema almacenado no cambia (la clave del store ya incluye `prompt_version`), así
que `store.py` no se toca. El vocabulario de `_CONTENT_FIELDS["process_defined"]` ya ofrecía
`analisis incidentes` y no necesitó cambios. `docs/05 §2.1` documenta el prompt nuevo y §6 la
versión. Se añade una prueba de voto con tres corridas que emiten `respuesta` + `analisis incidentes`
+ `mejora`: los tres grupos sobreviven y conservan sus propios campos.

**Evidencia A (llamadas reales, U1 con votación de 3 por corrida).**

| Documento | v6 (3 corridas) | v7 (3 corridas) |
|---|---|---|
| `good/respuesta-incidentes.md` | 2/3 emitieron proceso de análisis; en la tercera todo quedó en `respuesta` y `CRI-RS-02` fue `evidencia_insuficiente` | 3/3 emitieron `analisis incidentes`; `CRI-RS-02` = 75 en las tres |
| `good/gestion-de-riesgos.md` | — | 2/2 con `riesgos` y `revision` |
| `good/continuidad.md` | — | 2/2 con `recuperacion` |

No aparecieron campos ni citas fuera del texto: el análisis de v7 cita «análisis de causa raíz y se
preservan los registros y la evidencia...» y la contención sus tres pasos literales.

**Síntoma B (escenario `mid`).** `mid` daba Tier 1 con `CRI-GV-02 = 29` y `CRI-ID-03 = 29` (base 25
en ambos): roles nombrados pero sin autoridad y un proceso de riesgos descrito de forma genérica.
Tier 2 exige `CRI-GV-01`, `CRI-GV-02` y `CRI-ID-03` ≥ 50.

**Cambio B (solo documentos demo; criterios y reglas intactos).**

- `mid/roles.md`: los dos responsables pasan a una lista de campos (`Rol`, `Responsable`,
  `Responsabilidades`, `Autoridad`) con la autoridad explícita; la autoridad de la responsable de
  infraestructura se repite en `continuidad.md`. `CRI-GV-02` = 75 (nivel 3, sin
  `recursos_asignados` ni `practicas_rh`, que siguen siendo la brecha deliberada).
- `mid/riesgos-e-inventario.md`: el registro de riesgos declara, por riesgo, activo, impacto
  estimado y probabilidad estimada, y la priorización al día. `CRI-ID-03` = 75 por
  registro/priorización + impactos/probabilidades (ancla de §109), sin cuantificar con una escala
  común. Se intentó primero un proceso con `pasos` y sin impactos/probabilidades, pero `pasos` es
  texto libre y el voto de 3 no reunió la misma cadena en 2 corridas: `CRI-ID-03` se quedaba en 25.
  Las facetas booleanas sí votan de forma estable, así que el documento declara la cuantificación y
  deja la brecha en el método único (GV-03) y en el ciclo de revisión (GV-04).
- Se mantienen las brechas: sin programa de proveedores (`GV-06` = 0), procedimiento de incidentes
  parcial (`RS-02` insuficiente), inventario incompleto (`ID-04` < 75) y sin proceso de revisión
  (`GV-04` = 50).
- El registro trimestral y la revisión anual de la política producían una `process_defined` de
  `revision` que subía `GV-04` a 75 y el escenario a Tier 3. Se reformuló la vigencia de la política
  («se actualiza cada año») y se quitó la revisión del registro de riesgos para que `GV-04` quede en
  el tramo de `policy_review` (50), que es la brecha buscada.
- `good/roles-y-responsabilidades.md`: con votación de 3, la lista de roles en prosa se perdía (cada
  corrida parafraseaba los `dict` y ningún elemento alcanzaba mayoría), `GV-02` caía a 25 y `good`
  quedaba en Tier 1 pese a 92,33 de global. Se reescribió en el mismo formato de campos, con el mismo
  contenido (tres roles con autoridad, recursos y prácticas de RH); `GV-02` = 100 y `good` llega a
  Tier 4.

**Evidencia B (evaluación completa, `U1_VOTES=3`, U2 activo, prompt v7).**

| Escenario | Global | Tier | GV-02 | ID-03 | GV-04 | Otros |
|---|---|---|---|---|---|---|
| `mid` antes (`a_mid_1`) | 62,32 | 1 | 29 | 29 | 50 | GV-01 100, GV-03 75 |
| `mid` corrida 1 | 64,23 | **2** (no provisional) | **75** | **75** | 52 | GV-01 100, GV-03 75 |
| `mid` corrida 2 | 67,89 | **2** (no provisional) | **75** | **78** | 50 | GV-01 100, GV-03 74 |
| `good` | 94,02 | **4** (no provisional) | 100 | 100 | 100 | RS-02 100 |
| `gaps` | 33,55 | 1 (provisional) | 50 | insuficiente | 48 | el más bajo |

**Verificación.** `tests/test_ai_extraction.py` (prompt v7 y vocabulario), `tests/test_ai_voting.py`
(los tres procesos sobreviven) y `tests/test_op12_op14_ai_hardening.py` (versión registrada);
pruebas dirigidas: **77 passed**. Suite completa: **1046 passed, 2 skipped**; `ruff check` y
`ruff format --check` limpios.

## 112. El Tier pasa a ser un rango: piso confirmado y techo posible

El Tier contestaba una sola pregunta («¿cuánto se cumple?») y perdía la otra: cuánto de lo que
falta es una falla real y cuánto es solo falta de evidencia. Con un indicador de Tier 3 en
`evidencia_insuficiente`, el piso ya no sube —correcto, un desconocido no se asume cumplido— pero
el informe no podía decir si el siguiente nivel era alcanzable o estaba bloqueado. Ahora la
estimación es un rango explícito y no inventa: el piso es la regla T1 de siempre y el techo es
hasta dónde se llegaría si los requisitos desconocidos se resolvieran.

- **Piso (`tier`)**: sin cambios. El mayor nivel cuyos requisitos se cumplen, con la regla T3 para
  «no estimable» intacta.
- **Techo (`techo`)**: mayor nivel en el que ningún requisito de los niveles hasta ese nivel falló
  de verdad (`evaluado`/`no_implementado` por debajo del umbral, o `no_aplicable`). Un requisito en
  `evidencia_insuficiente`/`error`, o sin resultado, no corta el techo. Si el piso no es estimable,
  `techo` es `None`; siempre `techo >= tier`; `techo == tier` significa que no hay incógnitas que
  puedan elevarlo.
- **`faltan_para_techo`**: ids de los criterios desconocidos hasta el techo que impiden
  confirmarlo. `faltantes` conserva su semántica (qué bloquea el nivel siguiente).
- **`siguiente_nivel`**: `{nivel, cumplidos, total}` con los requisitos cumplidos del primer nivel
  por encima del piso; `None` en Tier 4 o cuando no es estimable.
- **`justificacion`**: cuando hay upside, «Tier 3 (Repeatable) confirmado; hasta Tier 4 si
  CRI-RS-02 llegara a 75 (sin evidencia suficiente).»; cuando una falla real corta el techo, dice
  qué falló. Sin cambios si el piso es exacto y no es provisional. `provisional` no cambia.

**Persistencia y API.** El estimado se deriva al consultar (`tier_estimates` no es tabla
persistida), así que no hay migración: los campos nuevos son opcionales con default en
`TierEstimate` y una respuesta vieja sin ellos sigue cargando (`techo = None`). El informe PDF
muestra el rango en la misma línea del Tier; comparaciones y re-evaluaciones lo reciben sin cambios.

**UI.** En `MaturityDashboard` las dos tarjetas de Tier («Tier Estimado» y «Confiabilidad del
Tier») pasan a una sola tarjeta de dos columnas: valor «Nivel 3 → hasta 4» cuando aplica, una
pista de cuatro pasos (piso sólido, techo con borde punteado, resto atenuado) y una línea corta
(«Repeatable · falta evidencia: RS-02» o la falla del nivel siguiente). El detalle —nivel
confirmado, techo, criterios con su título del catálogo y «x de y requisitos del Nivel N+1»— vive
en un popover que aparece con hover o foco de teclado. Sin `techo`, se pinta solo el piso como
antes.

**Reglas y verificación.** `docs/01 §8.3` añade T7 (definición de piso/techo y que un desconocido
nunca se asume) y `docs/04` actualiza las columnas del estimado. Pruebas nuevas en
`tests/test_aggregation.py`: techo igual al piso con todo cumplido; un desconocido en T4 (piso 3,
techo 4, `CRI-RS-02`); una falla real en T2 con desconocidos en T3 (piso y techo 1); un desconocido
solo en T2 (piso 1 provisional, techo 4); no estimable; estimado viejo sin los campos nuevos; ida y
vuelta JSON. `tests/test_api_assessments.py` comprueba los campos en la respuesta. Goldens de
pipeline regenerados (solo los campos nuevos del Tier). Verificación focalizada: 75 pruebas
backend, `ruff check`/`ruff format --check` limpios, y en copia temporal del frontend `typecheck`,
`lint` y `build` sin errores.

## 113. El voto perdía todo el texto libre: ahora vota la presencia, el medoide y las listas por parecido

**Síntoma.** `CRI-RC-01` no subía de 75 aunque el procedimiento narrara sus pasos, `CRI-ID-03` se
quedaba en 25 en `mid` por falta de `pasos`, y `GV-02` perdía la lista de roles escrita en prosa
(§110, §111). No era la extracción: era el voto. Cada campo se comparaba por igualdad exacta tras
`casefold`: dos corridas que describían los mismos pasos con otras palabras no coincidían y el campo
se borraba. Las reglas, en cambio, preguntan solo si el campo trae algo (`contenido.get("pasos")`).

**Cambio.** `voting.py` clasifica cada campo de `contenido` por cómo lo consume la regla
(`_CAMPOS_POR_TIPO`, una sola tabla junto al voto; un campo nuevo sin entrada se compara exacto y
`tests/test_ai_voting.py` comprueba que no se separe de `extraction._CONTENT_FIELDS`):

- **cerrado**: booleanos, enums (`proceso`, `frecuencia`, `estado_declarado`), fechas ISO y las
  cantidades que `numbers.py` ya normalizó (`retencion`, `tolerancia`, `plazos`,
  `criterios_activacion`). Igualdad exacta como antes.
- **presencia**: texto libre que la regla solo mira como verdad (`pasos`, `responsables`,
  `objetivos_riesgo`, `nombre`, `aprobada_por`, `clasificacion`, `criterios`, `niveles`, `mision`,
  `descripcion`, `responsable`). Sobrevive si está en la mayoría estricta de las corridas del grupo,
  redactado como sea; se guarda el **medoide** (mayor similitud media al resto, Jaccard de tokens
  sin tildes + `difflib`; empates por confianza, texto y corrida).
- **lista**: `activos`, `tipos_datos`, `destinatarios`, `partes_interesadas`, `requisitos_legales`,
  `servicios_criticos`, `dependencias`. Los elementos se emparejan con Jaccard ≥ 0,6 o contención de
  tokens, y sobreviven en la mayoría de las corridas.
- **lista de objetos**: `roles` por `rol` (Jaccard 0,5) y `criticidad` por `activo`; componentes
  conexas para no partir la lista cuando una corrida usa el nombre completo y otra el acrónimo, y
  cada subcampo se resuelve como presencia o cerrado.

Las corridas se ordenan por el contenido de sus afirmaciones (valor, locutor, id) antes de votar, no
por el orden en que llegaron: el mismo conjunto de corridas produce el mismo resultado en cualquier
orden, y con ello también la cita, el locator y el orden de las listas. El agrupamiento sigue siendo
`(tipo, proceso)` para `process_defined`; `estado_declarado` y el resto de los invariantes (§108) no
cambian. `store.FORMATO` sube a **4**: lo guardado por el voto viejo se reextrae en vez de
reutilizarse.

**Medición (mismas corridas crudas, antes/después).** Con el cliente y el prompt de producción
(`extract_v7`, razonamiento activo) se recolectaron **6 corridas por chunk** de los 18 chunks de
`frontend/public/demo/{good,mid,gaps}/documents` más los dos documentos de `mid` anteriores a §111
(`riesgos-e-inventario.md` y `roles.md` de `a643a21`, cuando la lista de roles y los pasos estaban en
prosa): 108 llamadas reales. Sobre esas mismas corridas se formaron 20 triplas aleatorias por chunk
(semilla fija, 360 triplas) y se votó con el módulo de `HEAD` y con el nuevo.

| Métrica | Voto anterior | Voto nuevo |
|---|---|---|
| Supervivencia de los campos de texto libre declarados en el documento | 83,1 % (881/1060) | **99,5 % (1055/1060)** |
| Supervivencia cuando ≥ 2 de las 3 corridas traían el campo | 83,5 % | **100 %** |
| Campos de presencia que solo traía 1 de 3 corridas y sobrevivieron | 7/73 (9,6 %) | 7/73 (9,6 %) |
| … excluyendo grupos ambiguos (una corrida con dos `policy_exists` del mismo tipo) | 0/39 | 0/39 |
| Estabilidad: triplas idénticas al resultado modal (texto exacto) | 53,9 % | 45,3 % |
| Estabilidad: mismas decisiones de presencia | 60,0 % | **67,2 %** |

Por campo, la supervivencia pasó de 5 % a 100 % en `process_defined.respuesta.pasos`, de 11,7 % a
100 % en `process_defined.riesgos.pasos`, de 15 % a 100 % en los pasos de análisis, contención y
mejora, de 66,7 % a 100 % en `role_assigned.roles` y de 95 % a 100 % en `escalation_path.niveles`.
`risk_tolerance.responsable` se queda en 91,7 % porque el modelo solo lo escribió en 1 de las 6
corridas: es disponibilidad, no voto.

**Reglas afectadas sobre la evidencia votada** (20 sesiones por escenario, media ± desviación típica
del puntaje base; sin logs, solo afirmaciones documentales):

| Escenario · criterio | Voto anterior | Voto nuevo |
|---|---|---|
| `mid-old` · GV-02 | 25,0 ± 0,0 | **75,0 ± 0,0** |
| `mid-old` · ID-03 | 26,2 ± 5,4 (25/50) | **50,0 ± 0,0** |
| `mid` · ID-03 | 75,0 ± 0,0 | **100,0 ± 0,0** |
| `good` · ID-03 | 88,8 ± 12,4 (75/100) | **100,0 ± 0,0** |
| `good` · RC-01 | 80,0 ± 17,0 (50/75/100) | **86,2 ± 12,4** (75/100) |
| `good` · RS-01 | 50,0 ± 0,0 | 56,2 ± 10,8 (50/75) |
| `good` · RS-04 | 56,2 ± 10,8 (50/75) | **75,0 ± 0,0** |
| `mid` · RS-04 | 50,0 ± 0,0 | 66,2 ± 11,9 (50/75) |
| `gaps` · GV-02 | 45,0 ± 10,0 (25/50) | **50,0 ± 0,0** |

El 75 de `mid`/ID-03 en §111 era un artefacto del voto: el proceso declara `pasos` además de
registro, priorización, impactos y probabilidades, así que la regla da 100. No se tocaron documentos,
criterios ni reglas para compensarlo; el cambio de puntaje es el que corresponde a la evidencia que
el documento ya declaraba.

**Pruebas.** `tests/test_ai_voting.py` gana casos por clase: parcelas de texto libre con la misma
idea y distintas palabras que sobreviven, una que solo trae 1 de 3 y no sobrevive, mayoría del grupo,
medoide determinista y orden-independiente (incluida cita y orden de lista), listas con sinónimos,
lista de 1 corrida descartada, roles emparejados por nombre con autoridad en 2 de 3, criticidad por
activo, cantidades exactas y una cantidad en palabras que no se empareja porque la normalización es
de la extracción, y la tabla de clases cubre todos los tipos de `_CONTENT_FIELDS`. Verificación
focalizada: 28 pruebas de voto, más extracción, store y cache. Suite completa: **1066 passed,
2 skipped**; `ruff check` y `ruff format --check` limpios.

**Límites.** Dos redacciones sin ningún token en común siguen sin emparejarse (no se inventa
similitud semántica); una corrida que emite dos afirmaciones del mismo tipo (dos `policy_exists` en
el mismo chunk) sigue eligiendo una sola al agrupar, y eso puede perder el `nombre` de la otra
(fuente de los 7 casos "espurios", iguales antes y después); y la estabilidad de texto exacto baja
porque ahora se conservan paráfrasis válidas que antes se descartaban, aunque las decisiones de
presencia son más estables.

## 114. El voto todavía perdía campos y mezclaba políticas; una negación aportaba datos y un fallo dejaba evidencia a medias

**Síntoma.** Cuatro problemas distintos, todos del mismo tipo: el motor podía perder una negación o
un dato, y una contradicción no llegaba a todos los criterios que la leen.

1. `voting._CAMPOS_POR_TIPO` seguía votando como cerrados `risk_tolerance.tolerancia`,
   `process_defined.criterios_activacion` y `notification_list.plazos`. Ninguna regla lee la cifra
   (`GV-03:68`, `RC-01:68,79`, `RS-03:48` solo preguntan si el campo trae algo), pero dos
   redacciones distintas entre corridas borraban el campo: `RC-01` se quedaba en 75 y `RS-03` en 75
   con el documento declarando los plazos.
2. `_group_key` solo separaba facetas para `process_defined`. Dos `policy_exists` del mismo chunk
   sobre políticas distintas se fundían en un grupo y solo sobrevivía una, votando `nombre`,
   `aprobada_por` y `estado_declarado` entre políticas diferentes: se podía perder la negación de
   una y acreditar la otra.
3. `contradictions._documents_disagree` y `_backup_vs_policy` tomaban cualquier `encontrado=true`,
   incluidos `planificado` e `inexistente`, como si declararan el hecho de hoy.
4. `_common.found` excluía los planes pero no las negaciones: una `inexistente` con
   `encontrado=true` aportaba sus campos a `merged_content`/`merged_bool`, y en el caso "el mismo
   documento afirma y niega" (§101) el puntaje subía con los datos de la negación. Aparte de eso,
   `run_pending_assessment` marcaba `fallida` sin `rollback` (evidencia y resultados parciales
   persistidos, y `PendingRollbackError` en el commit) y un mensaje no-JSON en la cola tumbaba el
   loop del worker.

**Cambio.**

- `voting`: `tolerancia`, `criterios_activacion` y `plazos` pasan a **presencia**. Un campo solo se
  relaja si ninguna regla parsea ni compara su valor; `retencion` (PR-02), `frecuencia`
  (contradicciones y GV-01/GV-04), `ultima_revision`, los booleanos, los enums y `estado_declarado`
  siguen cerrados. Cuando un valor idéntico aparece en la mayoría exacta, el voto guarda ese valor y
  no el medoide, así que las corridas que coinciden no cambian (`_votar_presencia`).
- `voting._claves_de_grupo` agrupa `policy_exists` por la política que nombra, con
  `_common.politica_faceta` (la misma normalización que puntúa) y el emparejamiento tolerante de las
  listas sobre el nombre normalizado. Sin nombre, la afirmación se une a la única política nombrada
  del chunk o es su propio grupo. `estado_declarado` se sigue votando exacto; si no hay mayoría y
  las corridas declaran estados distintos, no se elige el favorable: la afirmación queda visible con
  `LIMITACION_ESTADO_DUDOSO` y `doc_claims` la excluye de puntuar.
- `contradictions`: `_documents_disagree` y `_backup_vs_policy` solo comparan afirmaciones vigentes
  (`es_vigente`). La negación contra una vigente sigue siendo `_absence_disagreement`, que ahora
  cita su lado con `_common.mejor_declarada` (sin depender de `found`). La frecuencia de
  `policy_review` sigue atribuida solo a `CRI-GV-01`, que es quien la lee. Se probó atribuirla
  también a `CRI-GV-04` y se descartó: GV-04 no usa la frecuencia (su tramo de 50 solo acredita
  que la revisión se menciona) y, al quedar marcado como contradicho, `cap_contradicted` le topaba
  el puntaje aunque lo hubiera ganado con un `process_defined` de revisión. En el escenario
  conforme lo bajó de 100 a 52 y el Tier de 4 a 2. `_CRITERIOS_POR_TIPO["policy_review"]` sí nombra
  a GV-01 y GV-04 para la contradicción de **existencia** (un documento niega la revisión y otro la
  declara), porque ese hecho lo leen los dos.
- `_common.found` devuelve solo afirmaciones **vigentes** (`es_vigente`). `aplicar_estado_declarado`
  y `contradictions` leen las negaciones por su cuenta (`_declaraciones`, `by_type`,
  `mejor_declarada`), así que la ausencia explícita sigue dando 0 con su cita.
  Una negación conserva una sola cosa: su `false` explícito cuando el **mismo documento** también
  declara la práctica vigente (`_solo_negados`). Sigue compitiendo con la afirmación y, si es la más
  confiable, gana, como fija §101; sin eso, sacar la negación de `found` subía el puntaje de un
  documento que se contradice (GV-02 pasaba de 75 a 100 con "no se han asignado recursos" como
  afirmación más confiable). Sus demás campos no cuentan.
- `run_pending_assessment` hace `rollback` antes de marcar la evaluación `fallida` (y la recarga si
  el rollback la expiró); `workers/core.py` hace `rollback` antes de `mark_failed` y no deja que un
  fallo al marcar el job tumbe el loop. `queue.dequeue_blocking` descarta con un aviso un mensaje
  que no es JSON.
- `store.FORMATO` sube a **5**: cambia lo que se persiste para `policy_exists` y para esos tres
  campos.

**Medición (mismas corridas crudas, antes/después).** Sobre las 108 corridas reales de §113 (6 por
chunk de los 18 chunks de `frontend/public/demo/{good,mid,gaps}` más los dos documentos viejos de
`mid`), 20 triplas por chunk (semilla fija) y el módulo de `HEAD` frente al nuevo; puntajes con
`engine.evaluate_all`:

| Métrica | Antes (HEAD) | Después |
|---|---|---|
| Supervivencia de los campos de texto libre declarados | 96,8 % (1104/1140) | **99,6 % (1135/1140)** |
| Supervivencia cuando ≥ 2 de las 3 corridas traían el campo | 97,3 % | **100 %** |
| Campos de presencia que solo traía 1 de 3 corridas y sobrevivieron | 12/108 (11,1 %) | 12/108 (11,1 %) |
| `notification_list.plazos` presente | 0 % | **100 %** |
| `process_defined.recuperacion.criterios_activacion` presente | 45,0 % | **100 %** |

| Escenario · criterio | Antes | Después |
|---|---|---|
| `good` · RC-01 | 86,2 ± 12,4 (75/100) | **100,0 ± 0,0** |
| `good` · RS-03 | 75,0 ± 0,0 | **100,0 ± 0,0** |
| `mid-old` · GV-03 | 71,2 ± 8,9 (50/75) | **75,0 ± 0,0** |

GV-01, GV-03 (`good`/`mid`/`gaps`), GV-04, RC-01 (`mid`/`gaps`) y RS-03 (`mid`/`gaps`) no cambian.
Los tres aumentos son legítimos: `good/continuidad.md` declara "el procedimiento se activa cuando el
sitio principal permanece caido mas de dos horas" (`criterios_activacion`), `good/respuesta-incidentes.md`
declara que "los clientes afectados se notifican dentro de las 72 horas" (`plazos`) y
`mid-old/riesgos_old.md` declara "la tolerancia aceptada es de hasta un dia de interrupcion al mes"
(`tolerancia`). En `gaps` ningún criterio sube y la negación de `manual-operaciones.md` ("No existe un
programa de concienciación") sigue en `PR-07 = no_implementado, 0`, citada pero sin acreditar. Ese
conjunto de corridas no tiene ninguna corrida con dos `policy_exists`, así que la separación por
política se cubre con pruebas unitarias, no con esta medición.

**Pruebas.** `tests/test_ai_voting.py`: campos parafraseados que sobreviven, mayoría exacta,
dos políticas en el mismo chunk (nombre y estado separados), misma política con otras palabras, sin
nombre con una o dos políticas nombradas, y estado sin mayoría que queda con limitación.
`tests/test_contradictions.py`: un plan con otra retención no contradice, la negación sigue siendo
`_absence_disagreement`, la frecuencia contradicha se reporta en GV-01 y no marca a GV-04.
`tests/test_declared_state.py`: una negación del mismo documento no aporta sus campos (antes 100,
ahora 75). `tests/test_assessment_service.py`: un fallo tras escribir filas no deja evidencia,
resultados ni planes. `tests/test_workers_core.py` y `tests/test_queue.py`: el worker no muere si
falla el marcado del job ni con un mensaje corrupto. Suite completa: **1081 passed, 2 skipped**;
`ruff check` y `ruff format --check` limpios.

**Límites.** El emparejamiento de nombres de política es el mismo de las listas (tokens y contención,
Jaccard ≥ 0,6): dos nombres sin ningún token en común siguen siendo políticas distintas, igual que
para las facetas de §109. Una corrida que declara dos políticas con nombres casi idénticos las une.
El estado dudoso se descarta entero: no se intenta reconstruir con la cita, que es texto libre.
`_backup_vs_policy` y `_documents_disagree` solo miran afirmaciones vigentes, pero
`_database_exposure_vs_policy` no se tocó en esta entrada.

## 115. `policy_review` se llevaba cualquier revisión periódica y contradecía la frecuencia de la política

**Síntoma.** En el escenario `good` el modelo emitía un `policy_review` con frecuencia `semestral`
desde `gobierno-y-proveedores.md` («la revisión del inventario [de proveedores] es semestral»),
mientras `politica-seguridad.md` declaraba `anual` para la política. El prompt no definía
`policy_review`, así que el modelo etiquetaba con ese tipo cualquier revisión periódica. Como
`contradictions._documents_disagree` compara la frecuencia entre documentos distintos y excluye
ambas afirmaciones de CRI-GV-01, el criterio bajaba de 100 a 75 aunque la política sí se revisa
anualmente.

**Cambio.** `prompts/extract_v8.txt` (copia de v7; v7 queda intacto) agrega, después del ejemplo de
`process_defined`, el párrafo:

> El tipo policy_review es solo la revision periodica del documento de politica de seguridad de la
> informacion: con que frecuencia se revisa la politica y cuando fue su ultima revision. Revisar otra
> cosa no es policy_review: la revision del inventario de proveedores, del registro de riesgos, de las
> certificaciones de proveedores, del presupuesto o del personal, del desempeno del comite o de los
> accesos no produce policy_review. Si esa revision es del desempeno o de la estrategia, va en
> process_defined con proceso "revision"; cualquier otra no se emite como policy_review.
>
> Ejemplo: "la revision del inventario de proveedores es semestral" no produce policy_review; "esta
> politica se revisa con una frecuencia anual" si produce policy_review con frecuencia "anual".

`PROMPT_VERSION` sube a `extract_v8`. No cambian el esquema de respuesta, `_CONTENT_FIELDS`, ni
`criteria.yml`; docs/05 §2.1 documenta el tipo. Las pruebas que fijaban la versión se actualizan.

**Medición (llamadas reales, `deepseek-flash`).** Los 16 chunks de
`frontend/public/demo/{good,mid,gaps}` con el chunker y el cliente de producción, `U1_VOTES=1` y
`store` saltado, 3 corridas por chunk; control v7 con las mismas 3 corridas solo en los dos
documentos de `good` que se contradecían. Total: 48 llamadas v8 + 6 de control, más las 66 del
golden (120 en total). `policy_review` cuenta solo con `encontrado=true`:

| Documento | v7 (control, 3 corridas) | v8 (3 corridas) |
|---|---|---|
| `good/politica-seguridad.md` | 3/3, `anual` 2026-03-10 | 3/3, `anual` 2026-03-10 |
| `good/gobierno-y-proveedores.md` | 1/3, `semestral` (confianza 0,55) | **0/3** |
| `mid/politica-seguridad.md` | — | 3/3, `anual` 2026-02-01 |
| `mid/gobierno-y-proveedores.md` | — | 0/3 |
| `gaps/politica-seguridad.md` | — | 3/3, `anual` 2025-03-01 |
| `gaps/riesgos-y-respaldos.md` | — | 0/3 |
| Otros 10 documentos | — | 0/3 |

Con la evidencia v8 de cada réplica, `contradictions.detect` no encuentra ninguna contradicción en
los tres escenarios y las tres réplicas: `good` queda GV-01=100 y GV-04=100; `mid`, 100/50; `gaps`,
75/50. El 75 de `gaps` es la revisión de 2025-03-01 fuera del año declarado, no una contradicción.

**Golden set (22 chunks, `U1_VOTES=3`, 66 llamadas).** Recall **95 % (56/59)**, precisión **100 %
(95/95)** y citas **99,7 % (289/290)**; la única cita no localizable es la de `role_assigned` que une
dos secciones con `[...]` en `gestion-de-riesgos.md`, el mismo modo de fallo de la línea base
(docs/05 §8: 85 %, 100 %, 96 %). El aumento de recall no es atribuible a este cambio con la
evidencia disponible: la línea base es de `extract_v6` y desde entonces cambiaron el voto de campos
y de políticas (§113, §114).

**Regresión.** Contra las 6 corridas v7 por chunk de `/tmp/opencode/vote2` (mismo corpus), la tasa de
corridas que emiten cada tipo baja en `policy_exists` (32 %→27 %), `data_inventory` (25 %→19 %),
`process_defined` (52 %→48 %) y `role_assigned` (67 %→60 %); el resto queda igual o sube. La bajada
apreciable por chunk es `good/gobierno-y-proveedores.md`: `process_defined` en 2/3 corridas v8 frente
a 6/6 v7 (una corrida v8 no emitió ninguno), con `recuperacion` 1/3, `respuesta` 2/3 y `riesgos`
2/3; también `process_defined/revision` en `good/gestion-de-riesgos.md` (1/3 frente a 5/6) y
`role_assigned` en `mid/respuesta-incidentes.md` (1/3 frente a 6/6). El párrafo añadido no toca
`process_defined` y las otras dos corridas v8 sí lo emiten: se atribuye a la varianza conocida del
modelo (§105) y al tamaño (3 corridas frente a 6), no a una regla nueva.

**Pruebas.** `tests/test_ai_extraction.py` fija `extract_v8` y el párrafo de `policy_review`;
`tests/test_op12_op14_ai_hardening.py` registra la versión en reproducibilidad. Focalizadas:
extracción, golden, adaptador, store, GV-01 y contradicciones (146 pruebas). Suite completa:
**1081 passed, 2 skipped**; `ruff check` y `ruff format --check` limpios.

**Límites.** El caso medido queda corregido, pero la definición no es absoluta: en el golden, v8
emitió `policy_review` adicional (no esperado ni prohibido, no puntúa) para la revisión anual del
plan de continuidad en `very-long-continuity.md` y de la SoA en `soa-iso27001.md`. El control v7 solo
reprodujo el `semestral` en 1 de 3 corridas y con confianza 0,55 (no usable): el fallo original
depende de la varianza y con `U1_VOTES=3` una mayoría puede superar el umbral de 0,6. La comparación
de regresión usa 3 corridas v8 frente a 6 v7 y no distingue una pérdida real de una corrida que el
modelo decidió no emitir.

## 116. Recomendaciones en subpestañas y sin botones de IA

**Síntoma.** En la pestaña Recomendaciones, las tarjetas de contradicciones y de limitaciones se
apilaban encima de la lista de recomendaciones y la empujaban hacia abajo; además la UI ofrecía dos
botones de IA que no se querían exponer: «Re-extraer con IA» (Dashboard) y «Regenerar con IA» /
«Generar plan con IA» (Recomendaciones).

**Cambio.** Solo frontend. `RecommendationEngine.tsx` muestra tres subpestañas con contador
(Recomendaciones, Contradicciones, Limitaciones) y renderiza solo la activa; una subpestaña sin
elementos muestra un mensaje. Se quitan los dos botones, con su estado, su manejo de errores y los
imports sin uso (`MaturityDashboard.tsx`, `App.tsx`). El nombre de la pestaña principal sigue siendo
«Recomendaciones». Los planes siguen saliendo de la plantilla determinista al completar la evaluación
(§25).

**No cambia.** El backend: `reextraer=true` (§105) y `POST /assessments/{id}/plans` siguen en la API
y `reevaluateAssessment` / `createPlans` siguen en `lib/api.ts`, sin uso desde la UI. Quien quiera
forzar una extracción nueva debe llamar a la API.

**Pruebas.** `npm run typecheck`, `npm run lint` y `npm run build` limpios. El frontend no tiene
pruebas automáticas; la interfaz no se probó en un navegador al escribir esta entrada.

## 117. Cada bundle de ejemplo trae su log, y el refresco automático ya no lee ingestas ajenas

**Síntoma.** Con la base vacía los bundles de ejemplo se evaluaban sin eventos, y al ingerir logs de
varios escenarios `log_patterns` quedaba mezclada: `restore_exercise_run` aparecía `ok` aunque
`incidentes-demo` trae una restauración fallida. Además, la reevaluación automática tras una ingesta
creaba evaluaciones idénticas o vacías.

**Causa.** (1) La ingesta recalcula los patrones sobre todos los eventos guardados del org+scope y
reescribe la tabla; los tres logs son del mismo día y con los mismos sistemas, así que los escenarios
se pisan. (2) `maybe_enqueue_maturity_refresh` encolaba el refresco aunque la evaluación anterior
tuviera una selección explícita de ingestas que no incluía la nueva (§102): el refresco heredaba la
selección y no veía el log recién ingerido, o heredaba ingestas ya borradas.

**Cambio.**

- `DEMO_BUNDLES` declara su log (`eventLog`: `gaps` → `incidentes-demo`, `mid` →
  `respuesta-parcial-demo`, `good` → `flujo-correcto-demo`). `ContextSelector` borra los eventos,
  ingesta ese log y evalúa solo con esa ingesta, como los botones de Amenazas. Se quita la sección
  «Eventos operativos» del diálogo; con archivos propios no se manda lista y el backend lee las
  ingestas de la organización.
- `refresh.maybe_enqueue_maturity_refresh` recibe `ingest_id` y no encola si la evaluación anterior
  tiene una selección explícita que no lo incluye. `workers/logs.py` lo pasa.
- `App.handleIngested`: tras una ingesta, si aparece una evaluación nueva (la reevaluación
  automática), pasa a ser la activa y se vuelve al panel.

**Pruebas.** `test_auto_refresh_is_skipped_when_the_selection_excludes_the_new_ingest`; con
`test_assessment_event_sources.py`, `test_workers_logs.py` y los tests de refresco: 146 passed.
`ruff check` y `ruff format --check` limpios; la suite completa no se corrió. El build de Vite pasa;
`typecheck` no se corrió y la interfaz no se probó en un navegador al escribir esta entrada.

## 118. La evidencia de cada criterio se puede ver, con los alias que cita su explicación

**Síntoma.** La interfaz solo mostraba cuántas evidencias tenía un criterio («Evidencias: N»), nunca
cuáles. Las explicaciones del ajuste de IA citan `e1`, `e2`..., pero no había forma de saber a qué
correspondían, y la trazabilidad por archivo y línea que guarda el backend no se veía en ningún sitio.
Al revisar la pestaña de eventos tras §117 se confirmó además que una evaluación no guarda eventos ni
incidentes, solo la evidencia derivada (`log.window`, `log.pattern`): la instantánea operativa de una
evaluación está en su evidencia, no en la pestaña de eventos, que es el estado actual de la
organización.

**Causa.** Los alias no siguen el orden de `evidence_ids`: U2 ordena la evidencia por tipo y por el
hash del valor (`adjustment._canonical_evidence`, §105) para que el prompt no dependa de los UUID.
Reproducir ese orden en el navegador exigiría replicar `canonical_json` y SHA-256.

**Cambio.**

- `GET /assessments/{id}/criteria/{criterion_id}/evidence` (docs/04) devuelve
  `[{alias, evidence}]` en el orden canónico de U2 (`assessment_service.load_criterion_evidence`,
  esquema `CriterionEvidenceOut`). 404 si la evaluación no existe o no tiene el criterio. Solo
  lectura; no cambia el esquema de BD ni lo que emite ningún adaptador.
- Frontend: `EvidenceList` en el detalle de cada criterio, tanto en la tabla de criterios como en la
  vista de privacidad. «Ver evidencia (N)» la carga al abrirla y muestra alias, tipo, modalidad,
  localizador (archivo y líneas, página, sección o id de evento; la ruta de subida se recorta a la del
  paquete) y los campos del valor, más las limitaciones.

**Pruebas.** `test_criterion_evidence_uses_the_adjustment_aliases` (los alias coinciden con
`_canonical_evidence`) y `test_criterion_evidence_of_unknown_criterion_is_404`;
`test_api_assessments.py` y `test_ai_adjustment.py`: 43 passed. `ruff check` y `ruff format --check`
limpios; `typecheck`, `lint` y `build` del frontend limpios. Probado en Chromium sobre la evaluación
demo: `doc.claim` (CRI-GV-02, CRI-RC-01), `log.pattern` + `log.window` (CRI-RC-02, la explicación cita
`e1` y `e2` y coinciden) y `tf.public_access.config` con `terraform/security.tf:14-20` (CRI-PR-05).
Suite completa: **1084 passed, 2 skipped**.

**Límites.** Los valores largos se recortan a 160 caracteres (el texto completo queda en el tooltip) y
los objetos anidados, como el `contenido` de un `doc.claim`, se muestran como JSON. La pestaña de
eventos sigue mostrando el estado actual de la organización.
