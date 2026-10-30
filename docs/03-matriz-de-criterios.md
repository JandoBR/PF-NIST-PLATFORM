# 03 — Matriz de Criterios

Catálogo inicial de criterios. Es la especificación común del motor de evaluación, los adaptadores
y los prompts de IA. Cada criterio define: subcategorías NIST, tipo, evidencias requeridas, regla de
puntaje, peso, ajustabilidad por IA y recomendación base.

## 0. Convenciones

| Campo | Valores |
|---|---|
| **Tipo** | `Técnico` (manda evidencia declarada), `Proceso` (manda evidencia documental), `Mixto` (ambas) |
| **Peso** | Entero 1–5; relativo dentro de la categoría |
| **Ajuste IA** | `sí` / `no`; si `no`, el modelo no puede mover el puntaje (puede explicar) |
| **MVP** | `sí` = entra al prototipo; `parcial` = versión reducida; `no` = primera ampliación |
| **Estados** | `evaluado`, `no_implementado` (todo puntaje 0; la UI lo muestra como "Ausente o fallido"), `evidencia_insuficiente`, `no_aplicable`, `error` |

Reglas transversales:

- La rúbrica genérica de 0/25/50/75/100 está en `01-modelo-de-evaluacion.md §4`.
- La observación técnica prevalece sobre la documental (D7).
- `unknown` produce `evidencia_insuficiente` para el recurso afectado, nunca un valor inventado.
- **Silencio documental:** que los documentos analizados no declaren algo da `evidencia_insuficiente`, no 0
  (docs/09 §60). Un 0 exige evidencia explícita de ausencia, que en la práctica solo da la configuración
  técnica (p. ej. cifrado `disabled`) o un escenario de eventos (una falla observada).
- Una afirmación cuya cita no aparece en el documento no cuenta para ningún criterio (docs/05 §2.3 E8).
- Las recomendaciones son plantillas; la IA las adapta y explica, sin ejecutar nada.

Resumen de cobertura del catálogo:

| Función | Criterios | MVP total | MVP parcial |
|---|---|---|---|
| Govern | 6 | 3 | 0 |
| Identify | 6 | 3 | 0 |
| Protect | 7 | 6 | 0 |
| Detect | 3 | 1 | 1 |
| Respond | 4 | 1 | 0 |
| Recover | 3 | 2 | 1 |
| **Total** | **29** | **16** | **2** |

> **Estado de implementación:** **29 de 29** criterios implementados (CR-01…CR-05 y las Oleadas A, B
> y C, docs/11 §C). Cobertura del marco medida por el propio sistema en `GET /methodology`
> (`cobertura_implementacion`): **75 de 106 subcategorías (70,8 %) y las 22 categorías del CSF 2.0**,
> es decir `categorias_sin_criterio` vacía, con la **función Gobernar completa (31/31)**.
> **Las reglas de esta matriz describen el código** (`backend/app/evaluation/rules/`): si una regla cambia, se
> actualiza aquí en el mismo commit. Revisado contra el código el 2026-10-24 (docs/09 §77); en esa
> revisión se escribieron las fichas de `CRI-GV-05`, `CRI-GV-06` y `CRI-PR-07`, que la Oleada A
> había dejado sin documentar.
> Detalle del código en `09-registro-de-implementacion.md §31–§34`.

---

## 1. GOVERN (GV)

### CRI-GV-01 — Política de ciberseguridad establecida y revisada
- **Subcategorías:** GV.PO-01, GV.PO-02 · **Tipo:** Proceso · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Tier:** T2/T3
- **Evidencias:** `doc.claim(tipo=policy_exists)`, `doc.claim(tipo=policy_review)`
- **Regla:**
  - 100: política existe, aprobada por dirección, con frecuencia de revisión declarada y última revisión dentro de la frecuencia.
  - 75: existe y aprobada, sin evidencia de revisión reciente.
  - 50: existe en borrador o sin aprobación identificada.
  - 25: mención informal de “políticas” sin documento concreto.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
  - Sin documentos analizados → `evidencia_insuficiente`.
- **Recomendación:** formalizar/aprobar la política; definir ciclo de revisión (anual sugerido) y registrar la última revisión.

### CRI-GV-02 — Roles y responsabilidades definidos
- **Subcategorías:** GV.RR-01, GV.RR-02, GV.RR-03, GV.RR-04 · **Tipo:** Proceso · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Tier:** T2
- **Evidencias:** `doc.claim(tipo=role_assigned)`
- **Regla:**
  - 100: rol con **responsable nombrado**, **responsabilidades** y **autoridad** descritas, **más** `recursos_asignados` (presupuesto/personal acordes a la estrategia de riesgo, `GV.RR-03`) y `practicas_rh` (la ciberseguridad en contratación, inducción, cambios de rol y salida, `GV.RR-04`).
  - 75: hay autoridad declarada, pero falta el responsable nombrado, las responsabilidades, los recursos o las prácticas de RH. La explicación nombra lo que falta. Nombrar a un CISO no es dotar a la función.
  - 50: roles definidos sin autoridad explícita.
  - 25: roles genéricos (“el área de TI”) o sin un responsable nombrado.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** designar responsable de seguridad y dueños de activos con autoridad explícita, asignarles recursos acordes a la estrategia de riesgo e incorporar la ciberseguridad a las prácticas de personal.

### CRI-GV-03 — Estrategia de gestión del riesgo
- **Subcategorías:** GV.RM-01 … GV.RM-07 (las siete) · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** sí · **Tier:** T3
- **Evidencias:** `doc.claim(tipo=risk_tolerance)`
- **Regla:** objetivos y tolerancia son la puerta (`GV.RM-01`/`GV.RM-02`); el tramo alto se decide por **amplitud** sobre las otras cinco facetas: `integracion_empresarial` (`GV.RM-03`), `opciones_respuesta` (`GV.RM-04`), `lineas_comunicacion` (`GV.RM-05`), `metodo_estandarizado` (`GV.RM-06`) y `oportunidades_estrategicas` (`GV.RM-07`).
  - 100: objetivos + tolerancia + **≥3** de las cinco facetas.
  - 75: objetivos + tolerancia, sin desarrollar la estrategia. La explicación nombra las que faltan.
  - 50: objetivos definidos sin tolerancia explícita.
  - 25: declaración genérica de “gestionar riesgos”.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** desarrollar la estrategia de riesgo: objetivos y tolerancia, un método único de cálculo y priorización, las opciones de respuesta admitidas y las líneas de comunicación del riesgo.

### CRI-GV-04 — Revisión del desempeño y mejora de la estrategia
- **Subcategorías:** GV.OV-01, GV.OV-02, GV.OV-03 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** no · **Tier:** T3/T4
- **Evidencias:** `doc.claim(tipo=policy_review)`, `doc.claim(tipo=process_defined)`
- **Regla:**
  - 100: proceso de revisión (`process_defined` con `proceso` de revisión/mejora/desempeño) con métricas o con evidencia de ajustes realizados.
  - 75: proceso de revisión definido, sin métricas ni ajustes.
  - 50: solo la revisión periódica de la política (`policy_review`). Revisar un documento no es revisar la estrategia (GV.OV), y ese mismo claim ya cuenta para GV-01: no debe cubrir dos requisitos de Tier 3 (docs/09 §60).
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** institucionalizar una revisión periódica de la estrategia basada en resultados y registrar los ajustes.

### CRI-GV-05 — Contexto organizacional
- **Subcategorías:** GV.OC-01 … GV.OC-05 (las cinco) · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** no
- **Evidencias:** `doc.claim(tipo=org_context)`
- **Regla:** un campo del contenido por subcategoría —`mision` (`GV.OC-01`), `partes_interesadas` (`GV.OC-02`), `requisitos_legales` (`GV.OC-03`), `servicios_criticos` (`GV.OC-04`), `dependencias` (`GV.OC-05`)—, así que cada una se declara solo si su dato viene.
  - 100: los cinco campos. · 75: tres o cuatro. · 50: uno o dos.
  - La explicación nombra siempre los que faltan. Una afirmación de contexto sin ninguno de los cinco datos → `evidencia_insuficiente`.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Nota de alcance:** `GV.OC-03` nombra los requisitos de privacidad, pero eso es **Govern-P** del PF 1.0 y el cruce declarado del prototipo son Identify-P, Protect-P y los eventos, así que este criterio **no** entra en `PRIVACY_CRITERIA` (AMP-08 en docs/12 §5).
- **Recomendación:** documentar misión, partes interesadas, requisitos legales, servicios críticos y dependencias externas, y usarlos como entrada de la gestión de riesgo.

### CRI-GV-06 — Programa de riesgo de la cadena de suministro
- **Subcategorías:** GV.SC-01 … GV.SC-10 (las diez) · **Tipo:** Proceso · **Peso:** 2 · **IA:** sí · **MVP:** no
- **Evidencias:** `doc.claim(tipo=supplier_program)`
- **Regla:** `programa` es la puerta (`GV.SC-01`); el puntaje lo decide **cuántas de las nueve prácticas** declara el documento, una por subcategoría: `roles` (`GV.SC-02`), `integracion_riesgo` (`GV.SC-03`), `proveedores_priorizados` (`GV.SC-04`), `requisitos_contractuales` (`GV.SC-05`), `debida_diligencia` (`GV.SC-06`), `riesgos_monitoreados` (`GV.SC-07`), `en_respuesta_incidentes` (`GV.SC-08`), `monitoreo_ciclo_vida` (`GV.SC-09`) y `terminacion` (`GV.SC-10`).
  - 100: programa + ≥7 prácticas. · 75: + 4–6. · 50: + 1–3. · 25: el programa y nada más.
  - La explicación siempre nombra las prácticas que faltan.
  - Mencionar proveedores sin declarar un programa → `evidencia_insuficiente` (no 0): mencionar no es tener.
- **Nota de amplitud:** si el 100 dependiera solo de que exista un programa, las diez subcategorías se sostendrían en una sola frase. `GV.SC-07` se evidencia por vía documental; la señal técnica de procedencia de módulos de Terraform sigue siendo AMP-07 en docs/12 §5, ahora como mejora de calidad y no de cobertura.
- **Recomendación:** formalizar el programa de proveedores: roles acordados, inventario priorizado, requisitos en contratos, debida diligencia previa, seguimiento del riesgo durante la relación y disposiciones de cierre.

---

## 2. IDENTIFY (ID)

### CRI-ID-01 — Inventario de activos
- **Subcategorías:** ID.AM-01, ID.AM-02 · **Tipo:** Mixto · **Peso:** 4 · **IA:** no · **MVP:** sí
- **Evidencias:** `tf.resource.present` (agregado por tipo/entorno), `doc.claim(tipo=data_inventory)`
- **Regla:**
  - Se contrasta el inventario declarado en documentos con los recursos presentes en Terraform.
  - 100: documento de inventario cubre todos los tipos de recurso soportados que existen en Terraform.
  - 75: cubre la mayoría (≥ 75 %).
  - 50: cubre parcialmente (25–74 %).
  - 25: existe mención de inventario sin cobertura verificable.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
  - La cobertura se calcula sobre tipos de recurso, y se registra como limitación que solo se evalúan tipos soportados. Los recursos que solo configuran a otro (cifrado, versionado o bloqueo público de un bucket) no cuentan como activos.
- **Recomendación:** mantener un inventario de activos que incluya los recursos desplegados y su responsable.

### CRI-ID-02 — Priorización de activos por criticidad
- **Subcategorías:** ID.AM-05 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** sí
- **Evidencias:** `doc.claim(tipo=data_inventory)`, `ctx.profile(activos_criticos)`
- **Regla:**
  - 100: clasificación de criticidad documentada y consistente con los activos críticos declarados en contexto.
  - 50: clasificación mencionada sin criterios.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** clasificar activos por criticidad y usarlo para priorizar controles y esfuerzo.

### CRI-ID-03 — Identificación y evaluación de riesgos
- **Subcategorías:** ID.RA-01, ID.RA-03, ID.RA-04, ID.RA-05, ID.RA-06 · **Tipo:** Proceso · **Peso:** 4 · **IA:** sí · **MVP:** sí · **Tier:** T2
- **Evidencias:** `doc.claim(tipo=process_defined)`
- **Regla:**
  - 100: proceso documentado con pasos, registro/priorización **y** los impactos o probabilidades de cada riesgo registrados (`impactos`/`probabilidades`). Esto último es lo que sostiene `ID.RA-04`.
  - 75: proceso con registro y priorización, pero sin impactos ni probabilidades.
  - 50: proceso definido sin registro ni priorización de riesgos (evidencia `ID.RA-01` y nada más).
  - 25: evaluación descrita de forma genérica, sin pasos concretos.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** establecer una evaluación de riesgos repetible con registro y priorización.

### CRI-ID-04 — Inventario de datos y metadatos *(privacidad, secundaria)*
- **Subcategorías:** ID.AM-07 · **Tipo:** Proceso · **Peso:** 2 · **IA:** sí · **MVP:** no · **Tier:** T4
- **Evidencias:** `doc.claim(tipo=data_inventory)`
- **Regla:**
  - 100: inventario de datos con tipos, ubicación y clasificación (incluye datos personales).
  - 50: inventario parcial o sin clasificación.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** documentar qué datos existen, dónde residen y su clasificación, incluyendo datos personales.

### CRI-ID-05 — Mejora continua a partir de evaluaciones y ejercicios
- **Subcategorías:** ID.IM-01, ID.IM-02, ID.IM-03, ID.IM-04 · **Tipo:** Mixto · **Peso:** 3 · **IA:** sí · **MVP:** no · **Tier:** T4
- **Evidencias:** `doc.claim(tipo=process_defined)` con `contenido.proceso` de mejora/lecciones aprendidas, `log.pattern(restore_exercise_run)`, `log.window`
- **Regla:**
  - 100: ciclo de mejora documentado con métricas o ajustes, un ejercicio observado en una ventana completa **y** `planes_actualizados` (los planes se mantienen con lo aprendido, `ID.IM-04`).
  - 75: lo anterior sin `planes_actualizados`; ciclo documentado con métricas/ajustes sin ejercicio observado; o proceso documentado y ejercicio observado pero sin métricas ni ajustes.
  - 50: mejora descrita de forma genérica; o ejercicio observado sin ningún ciclo de mejora documentado.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
  - Sin documentos ni ejercicio → `evidencia_insuficiente`.
- **Nota de mapeo:** `ID.IM-02` ("mejoras a partir de pruebas y ejercicios") solo se declara porque la regla consume el ejercicio observado; sin ese patrón sería una afirmación documental sin verificar. `ID.IM-04` entró en la Oleada B con el campo `planes_actualizados`, que es condición del 100: un ciclo que mide y ajusta pero no toca los planes no la evidencia.
- **Recomendación:** cerrar el ciclo de mejora: registrar las lecciones de evaluaciones y ejercicios y seguir los ajustes con métricas.

---

## 3. PROTECT (PR)

### CRI-ID-06 — Procedencia e integridad del software adquirido
- **Subcategorías:** ID.RA-09 · **Tipo:** Técnico · **Peso:** 2 · **IA:** no · **MVP:** no · **Privacidad:** —
- **Evidencias:** `tf.module.source`, `tf.provider.version`
- **Regla:**
  - 100: todos los proveedores con restricción de versión **y** todos los módulos de terceros fijados.
  - 75: proveedores fijados, algún módulo de terceros sin fijar.
  - 50: módulos de terceros fijados, pero ningún proveedor con restricción (o sin `required_providers`).
  - 25: ni proveedores con restricción ni módulos de terceros fijados.
  - Sin bloques `module` ni `required_providers` → no aplicable.
- **Notas:** un módulo `local` (`./modulos/x`) no se cuenta como "sin fijar": es código del mismo
  repositorio, no una adquisición, y no hay versión que fijar. El piso es **25 y no 0** porque un
  `source` sin versión es silencio sobre la procedencia, no una negación explícita (mismo criterio
  que docs/09 §60); en HCL no existe forma de declarar "no controlo esto". Un `source` que el parser
  no puede leer cuenta como de terceros: no se puede suponer propio.
- **Recomendación:** fijar la procedencia del código de terceros — `version` en cada módulo del
  registry, `?ref=<tag|sha>` en los de git, y una restricción de versión por proveedor.

### CRI-PR-01 — Cifrado de datos en reposo
- **Subcategorías:** PR.DS-01 · **Tipo:** Técnico · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Privacidad:** Protect-P
- **Evidencias:** `tf.encryption.config` (RDS, S3), `doc.claim(tipo=policy_exists)`
- **Regla (por recurso soportado):**
  - Todos los recursos aplicables con evidencia `enabled` → 100.
  - Alguno `disabled` y alguno `enabled` → 25: implementación parcial (prevalece sobre la política).
  - Ningún recurso resuelto cifra (todos `disabled`) → 0: ausencia explícita.
  - Un recurso aplicable **sin evidencia de cifrado** o con estado `unknown` (p. ej. un bucket sin
    `aws_s3_bucket_server_side_encryption_configuration` explícito) → `evidencia_insuficiente`: no
    se puede afirmar el 100. Un `disabled` explícito sí prevalece (0/25) y se informa.
  - Sin recursos del tipo → `no_aplicable` con motivo.
  - Política documental sin recursos: no eleva el puntaje técnico; alimenta contexto y el hallazgo.
- **Recomendación:** habilitar cifrado gestionado por KMS en RDS y S3; verificar mecanismo y llave.

### CRI-PR-02 — Backups configurados y protegidos
- **Subcategorías:** PR.DS-11 · **Tipo:** Técnico · **Peso:** 5 · **IA:** sí · **MVP:** sí
- **Evidencias:** `tf.backup.config` (retención), `doc.claim(tipo=backup_policy)`
- **Regla:**
  - 100: retención configurada ≥ política documentada y backups con cifrado (instancia RDS con cifrado `enabled`; si no está confirmado, tope 75).
  - 75: retención configurada ≥ 7 días sin otros detalles.
  - 50: backups habilitados con retención < política. La política sigue contando (fija el requisito) y además se informa como hallazgo de contradicción (docs/09 §64).
  - 25: alguna base con retención en 0 y otras con backups.
  - 0: ninguna base resuelta tiene backups (retención en 0 en todas).
  - La retención de la política se lee con unidades (días, semanas, meses ≈ 30 días, años ≈ 365).
  - `unknown` → insuficiente.
- **Recomendación:** alinear retención de backups con la política y asegurar su cifrado.

### CRI-PR-03 — Acceso administrativo restringido
- **Subcategorías:** PR.AA-05, PR.IR-01 · **Tipo:** Técnico · **Peso:** 4 · **IA:** no · **MVP:** sí · **Privacidad:** Protect-P
- **Evidencias:** `tf.security_group.rules`
- **Regla:**
  - 100: sin reglas que expongan SSH (22) o RDP (3389) desde `0.0.0.0/0` o `::/0`, y SSH con acceso restringido.
  - 0: cualquier regla que exponga administración a Internet. Es una exposición explícita, no una implementación parcial (como una base pública en PR-05).
  - Se registra que es configuración declarada; no demuestra accesibilidad efectiva.
  - Sin exposición confirmada, una regla de entrada que podría exponer administración y no se puede resolver → `evidencia_insuficiente` (ni 0 ni 100): abierta a Internet con el puerto sin resolver (`var.ssh_port`), o en un puerto administrativo con el CIDR sin resolver. Un CIDR sin resolver en un puerto no administrativo no afecta.
  - Sin security groups evaluables → insuficiente.
- **Recomendación:** restringir puertos administrativos a rangos corporativos/VPN y eliminar reglas `0.0.0.0/0`.

### CRI-PR-04 — Configuración segura del servidor (SSH)
- **Subcategorías:** PR.PS-01 · **Tipo:** Técnico · **Peso:** 3 · **IA:** no · **MVP:** sí
- **Evidencias:** `an.task.config` (sshd_config: `PermitRootLogin`, `PasswordAuthentication`), `an.file.permissions`
- **Regla:**
  - 100: `PermitRootLogin no` y `PasswordAuthentication no` declarados.
  - 75: solo uno de los dos endurecido.
  - 50: SSH configurado sin opciones explícitas de endurecimiento.
  - 25: `PermitRootLogin yes` o `PasswordAuthentication yes` explícito; o permisos de
    `sshd_config` con escritura para grupo/otros (incluye modo simbólico absoluto traducible).
  - Un modo simbólico **relativo** (`u+rwx`, que depende de los permisos actuales) no es
    interpretable: `evidencia_insuficiente`, nunca 100.
  - 0: los dos en `yes` explícito.
  - El valor se lee de `line` (lo que queda escrito), nunca de `regexp`.
  - `an.file.permissions` sobre `sshd_config` con escritura para grupo/otros → tope 25.
  - Sin tareas de SSH interpretadas → insuficiente.
- **Recomendación:** deshabilitar login de root y autenticación por contraseña; usar claves.

### CRI-PR-05 — Almacenamiento protegido contra acceso público
- **Subcategorías:** PR.DS-01 · **Tipo:** Técnico · **Peso:** 3 · **IA:** no · **MVP:** sí · **Privacidad:** Protect-P
- **Evidencias:** `tf.public_access.config`, `tf.versioning.config` (informativa), `tf.db_exposure.config`
- **Regla:**
  - 100: bloqueo de acceso público en los 4 modos (ACL, política, ignorar, restringir) declarado en **todos** los buckets.
  - Sin exposición ni bloqueo parcial, un bucket sin bloque declarado → `evidencia_insuficiente`.
  - 50: bloqueo parcial (alguno de los 4).
  - 0: `block_public_acls = false` o equivalente explícito, **o** una base de datos con
    `publicly_accessible = true` (exposición explícita; prevalece sobre una política que diga lo contrario).
  - Solo bases de datos, todas no públicas → 100; sin buckets ni bases → no aplicable.
  - `unknown` → insuficiente.
- **Recomendación:** habilitar `aws_s3_bucket_public_access_block` completo.

### CRI-PR-06 — Generación de logs para monitoreo
- **Subcategorías:** PR.PS-04 · **Tipo:** Técnico · **Peso:** 4 · **IA:** no · **MVP:** sí
- **Evidencias:** `tf.logging.config` (CloudTrail), `an.service.state` (servicio de syslog)
- **Regla:**
  - 100: CloudTrail habilitado multirregión + logs de sistema declarados en servidores.
  - 75: CloudTrail habilitado (sin multirregión) o logs de sistema completos.
  - 50: alguna fuente de log declarada.
  - 0: sin logging declarado.
  - Sin recursos evaluables → insuficiente.
- **Recomendación:** habilitar CloudTrail multirregión y logging de sistema con retención definida.

### CRI-PR-07 — Concienciación y formación
- **Subcategorías:** PR.AT-01, PR.AT-02 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** no
- **Evidencias:** `doc.claim(tipo=training_program)`
- **Regla:** `programa` es la puerta (`PR.AT-01`); `roles_especializados` es lo que sostiene `PR.AT-02` (formación específica para roles con acceso privilegiado o funciones de seguridad).
  - 100: programa con frecuencia reconocida **y** formación diferenciada por rol.
  - 75: programa con frecuencia sin formación especializada; o formación por rol sin periodicidad del programa general.
  - 50: programa declarado sin periodicidad ni alcance por rol.
  - Mencionar la formación sin declarar un programa → `evidencia_insuficiente`, no 0.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0** (docs/09 §60).
- **Recomendación:** formalizar el programa de concienciación con frecuencia definida y formación específica para los roles privilegiados.

---

## 4. DETECT (DE)

### CRI-DE-01 — Monitoreo de red y cómputo
- **Subcategorías:** DE.CM-01, DE.CM-09 · **Tipo:** Mixto · **Peso:** 5 · **IA:** no · **MVP:** sí · **Tier:** T3 · **Privacidad:** apoyo Detect
- **Evidencias:** `tf.logging.config`, `an.service.state`, `log.window` (¿hubo actividad observable?)
- **Regla:**
  - 100: CloudTrail habilitado **multirregión** **y** logs de sistema declarados (servicio de syslog habilitado en Ansible). El bucket de destino no cuenta como centralización: es obligatorio y siempre está.
  - 75: alguna fuente habilitada (CloudTrail o logs de sistema) sin las dos condiciones anteriores.
  - 0: CloudTrail declarado pero ninguna fuente habilitada.
  - Sin configuración de monitoreo evaluable → `evidencia_insuficiente`, no 0. Un CloudTrail con estado sin resolver no puntúa.
  - Si hay ventana de observación (`log.window`) se cita como actividad observable; no cambia el puntaje.
  - (No hay tramo de 50: "parcialmente habilitadas" cae en 75.)
- **Recomendación:** centralizar logs y definir fuentes mínimas de monitoreo (red, sistema, nube).

### CRI-DE-02 — Análisis de eventos y declaración de incidentes
- **Subcategorías:** DE.AE-02, DE.AE-03, DE.AE-08 · **Tipo:** Mixto · **Peso:** 4 · **IA:** sí · **MVP:** parcial · **Privacidad:** Protect-P + apoyo Detect
- **Evidencias:** `doc.claim(tipo=process_defined)`, `log.pattern@2(alert_raised|incident_declared)`
- **Regla:**
  - Sin ventana de eventos completa (igual que RC-02): 75 si hay criterios de declaración documentados, 50 si solo se describe el análisis, `evidencia_insuficiente` si no hay nada documentado.
  - Con ventana completa:
    - 0: hubo actividad que debía alertar (`auth_failures_burst`) y no hubo alerta ni declaración: falla de detección (docs/06 §5).
    - 100: criterios de declaración documentados + evidencia operativa de alerta/declaración **desde dos orígenes distintos** (`log.pattern@2.fuentes`). Es lo que sostiene DE.AE-03: un solo sistema que alerta es detección, no correlación.
    - 75: criterios documentados sin evidencia operativa; evidencia operativa sin criterios documentados; o los dos pero con la alerta vista por un solo origen.
    - 50: análisis de eventos descrito sin criterios de declaración concretos.
    - Ventana completa sin ningún patrón aplicable ni criterios documentados → `evidencia_insuficiente` (sin oportunidad, no se penaliza).
- **Recomendación:** definir criterios de declaración de incidentes y registrar alertas con su análisis.

### CRI-DE-03 — Información de eventos a personal y herramientas
- **Subcategorías:** DE.AE-06 · **Tipo:** Mixto · **Peso:** 3 · **IA:** sí · **MVP:** no
- **Evidencias:** `log.pattern(alert_raised)`, `doc.claim(tipo=notification_list)`
- **Regla:**
  - 100: alertas llegan a destinatarios definidos y el escenario lo evidencia.
  - 75: destinatarios definidos sin evidencia operativa.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** definir destinatarios de alertas y verificar la entrega.

---

## 5. RESPOND (RS)

### CRI-RS-01 — Plan de respuesta con clasificación y escalamiento
- **Subcategorías:** RS.MA-01, RS.MA-02, RS.MA-03, RS.MA-04, RS.MA-05 · **Tipo:** Mixto · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Tier:** T3 · **Privacidad:** Protect-P + apoyo Respond
- **Evidencias:** `doc.claim(tipo=process_defined)`, `doc.claim(tipo=escalation_path)`, `log.pattern(escalation_done|incident_declared)`
- **Regla:**
  - Plan completo = `process_defined` de respuesta con pasos, responsables **y** `criterios_recuperacion` (cuándo se cierra la respuesta y empieza la recuperación, `RS.MA-05`). El escalamiento documentado (`escalation_path`) cuenta como plan parcial.
  - 100: plan completo + `escalation_done` **posterior** al `incident_declared` (docs/08 §5, D3). Un escalamiento anterior a la declaración no es respuesta a ese incidente.
  - 75: plan completo sin escalamiento asociado; o plan parcial con escalamiento posterior; o escalamiento observado sin plan documentado (tope 75).
  - 50: plan parcial sin evidencia operativa.
  - 0: incidente declarado en una ventana completa sin escalamiento posterior: falla de respuesta (docs/06 §5, docs/08 §5), con o sin plan.
  - Sin plan ni evidencia operativa → `evidencia_insuficiente`.
- **Nota de mapeo:** `RS.MA-05` usa un campo propio y **no** `criterios_activacion`: en un proceso de respuesta ese campo son los criterios para activar la respuesta, y además es el que `CRI-RC-01` ya lee del proceso de recuperación.
- **Recomendación:** documentar y ensayar el plan de respuesta incluyendo escalamiento y criterios de prioridad.

### CRI-RS-02 — Análisis de incidentes y preservación de evidencia
- **Subcategorías:** RS.AN-03, RS.AN-06, RS.AN-07 · **Tipo:** Mixto · **Peso:** 3 · **IA:** sí · **MVP:** no · **Tier:** T4
- **Evidencias:** `doc.claim(tipo=process_defined)`, `log.pattern(incident_declared)`
- **Regla:**
  - 100: proceso de análisis de causa raíz y conservación de evidencia documentado y evidenciado en el escenario.
  - 75: documentado sin evidencia operativa.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** definir análisis de causa raíz y preservación de evidencia con registros.

### CRI-RS-03 — Notificación a partes interesadas
- **Subcategorías:** RS.CO-02 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** no · **Privacidad:** Protect-P + apoyo Respond
- **Evidencias:** `doc.claim(tipo=notification_list)`
- **Regla:**
  - 100: lista de notificación interna/externa con **destinatarios, criterios y plazos**.
  - 75: lista con destinatarios, pero sin criterios o sin plazos (no hay tramo 50: docs/09 §47).
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
- **Recomendación:** definir a quién, cuándo y cómo se notifica un incidente.

### CRI-RS-04 — Contención y erradicación del incidente
- **Subcategorías:** RS.MI-01, RS.MI-02 · **Tipo:** Mixto · **Peso:** 4 · **IA:** sí · **MVP:** no · **Tier:** —
- **Evidencias:** `log.pattern(containment_done)`, `log.pattern(incident_declared)`, `log.window`, `doc.claim(tipo=process_defined)` con `contenido.proceso` de contención/erradicación/mitigación
- **Regla:**
  - 100: contención observada en una ventana completa **y** procedimiento documentado con pasos.
  - 75: contención observada sin procedimiento documentado (tope 75); o procedimiento con pasos sin incidentes que contener.
  - 50: contención descrita de forma genérica, sin pasos.
  - 0: incidente declarado en una ventana completa sin contención: falla de mitigación (docs/06 §5).
  - Ventana completa sin incidentes ni procedimiento, o sin ventana ni documento → `evidencia_insuficiente`.
- **Nota de mapeo:** `RS.MI-01` (contener) la evidencia el patrón `containment_done`, que hasta ahora se agregaba sin consumidor (docs/09 §53). `RS.MI-02` (erradicar) descansa en la parte documental: ningún evento del contrato declara la erradicación por sí solo.
- **Recomendación:** documentar los pasos de contención y erradicación y registrar la contención de cada incidente declarado.

---

## 6. RECOVER (RC)

### CRI-RC-01 — Procedimiento de recuperación definido y ejecutable
- **Subcategorías:** RC.RP-01, RC.RP-02 · **Tipo:** Proceso · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Tier:** T3 · **Privacidad:** Protect-P + apoyo Recover
- **Evidencias:** `doc.claim(tipo=process_defined)`, `doc.claim(tipo=backup_policy)`
- **Regla:**
  - 100: procedimiento de recuperación con pasos, responsables y criterios de activación.
  - 75: procedimiento con pasos, sin criterios de activación o sin responsables.
  - 50: recuperación mencionada de forma genérica (sin pasos), o solo una política de backups sin procedimiento de recuperación.
  - Los documentos analizados no lo declaran (o lo marcan como no encontrado) → `evidencia_insuficiente`, **no 0**: el silencio de un documento no prueba que la práctica falte. Se informa como hallazgo `limitacion` (docs/09 §60).
  - Sin afirmaciones de proceso ni de backups → `evidencia_insuficiente`.
- **Recomendación:** documentar el procedimiento de recuperación con responsables y criterios de inicio.

### CRI-RC-02 — Verificación de integridad de backups
- **Subcategorías:** RC.RP-03 · **Tipo:** Mixto · **Peso:** 4 · **IA:** sí · **MVP:** sí · **Tier:** T3
- **Evidencias:** `doc.claim(tipo=backup_policy)`, `log.pattern(restore_exercise_run|restore_verified)`
- **Regla:**
  - Sin ventana de eventos completa: 75 si la política de backups exige verificación de integridad; si no, `evidencia_insuficiente`.
  - Con ventana completa:
    - 0: ejercicio de restauración fallido (`restore_exercise_run` con resultado `fail`).
    - 100: la política exige verificación + restauración verificada (`restore_verified`).
    - 75: restauración verificada sin política documentada, o política que exige verificación sin evidencia operativa.
    - 50: ejercicio de restauración exitoso sin verificación final.
    - Sin ningún patrón aplicable ni política de verificación → `evidencia_insuficiente` (sin oportunidad, no se penaliza).
- **Recomendación:** verificar integridad de backups antes de restaurar y registrar la prueba.

### CRI-RC-03 — Restauración verificada y comunicación de recuperación
- **Subcategorías:** RC.RP-05, RC.CO-03 · **Tipo:** Mixto · **Peso:** 3 · **IA:** sí · **MVP:** parcial · **Tier:** T4
- **Evidencias:** `log.pattern(restore_verified)`, `doc.claim(tipo=notification_list)`
- **Regla** (exige una ventana de eventos completa; sin ella → `evidencia_insuficiente`):
  - 100: restauración verificada en el escenario + comunicación de recuperación observada (`recovery_communicated`).
  - 75: restauración verificada sin comunicación observada. Una lista de notificación documentada (con destinatarios) se cita, pero no sustituye a la comunicación: saber a quién avisar no prueba que se avisó.
  - 50: recuperación ejecutada (ejercicio exitoso) sin verificación final.
  - Ventana completa sin ningún patrón aplicable → `evidencia_insuficiente` (sin oportunidad, no se penaliza). No hay tramo de 0.
- **Recomendación:** confirmar operación normal tras restaurar y comunicar el estado a los interesados.

---

## 7. Cruce con Privacidad (Secundario)

La dimensión de privacidad se limita a eventos de ciberseguridad que afectan información personal.
No evalúa minimización, retención, finalidades ni derechos de los titulares.

| Criterio | Relación PF/CSF | Justificación |
|---|---|---|
| CRI-ID-04 | Identify-P | Saber qué datos existen es prerrequisito de protección. |
| CRI-PR-01 | Protect-P | Protección de datos personales en reposo. |
| CRI-PR-03 | Protect-P | Acceso autorizado a datos. |
| CRI-PR-05 | Protect-P | Evitar exposición de datos almacenados. |
| CRI-DE-02 | Protect-P + CSF Detect | Detección de eventos que pueden derivar en brecha. |
| CRI-RS-01, CRI-RS-03 | Protect-P + CSF Respond | Respuesta y notificación de brechas. |
| CRI-RC-01, CRI-RC-02, CRI-RC-03 | Protect-P + CSF Recover | Recuperación y verificación tras una brecha. |

> En el informe se muestra una sección “Privacidad (relacionada con ciberseguridad)” construida con
> estos criterios, siempre con la aclaración de alcance.

## 8. Recomendaciones Base (Plantillas)

| Criterio | Acción principal sugerida |
|---|---|
| CRI-GV-01 | Aprobar y versionar la política; calendarizar su revisión. |
| CRI-GV-02 | Nombrar responsables por rol con responsabilidades y autoridad. |
| CRI-GV-03 | Documentar tolerancia al riesgo alineada al negocio. |
| CRI-GV-04 | Establecer revisión periódica con métricas y registro de ajustes. |
| CRI-ID-01 | Completar inventario de activos incluyendo recursos desplegados. |
| CRI-ID-02 | Clasificar activos por criticidad. |
| CRI-ID-03 | Crear registro de riesgos con priorización. |
| CRI-ID-04 | Inventariar datos y clasificarlos (incluye personales). |
| CRI-PR-01 | Cifrado KMS en RDS y S3. |
| CRI-PR-02 | Ajustar retención de backups a la política y cifrar. |
| CRI-PR-03 | Cerrar puertos administrativos a Internet. |
| CRI-PR-04 | Endurecer SSH (sin root, sin contraseña). |
| CRI-PR-05 | Bloqueo completo de acceso público en S3. |
| CRI-PR-06 | CloudTrail multirregión + logs de sistema centralizados. |
| CRI-DE-01 | Centralizar logs y definir fuentes mínimas. |
| CRI-DE-02 | Definir criterios de declaración de incidentes. |
| CRI-DE-03 | Definir y probar la entrega de alertas. |
| CRI-RS-01 | Documentar y ensayar el plan de respuesta. |
| CRI-RS-02 | Definir causa raíz y preservación de evidencia. |
| CRI-RS-03 | Definir notificaciones y plazos. |
| CRI-RC-01 | Documentar procedimiento de recuperación. |
| CRI-RC-02 | Verificar integridad de backups periódicamente. |
| CRI-RC-03 | Confirmar operación normal y comunicar la recuperación. |

## 9. Indicadores de Tier

Indicadores y umbrales por Tier: ver `01-modelo-de-evaluacion.md §8.2` (tabla de lectura humana) y
`methodology/settings.yml` (fuente canónica, `04-arquitectura-backend.md §8`). No se repiten aquí para
evitar que la matriz de criterios y la metodología se desincronicen.

## 10. Trazabilidad de Referencias NIST

Todas las subcategorías citadas corresponden a NIST CSF 2.0 (CSWP 29, febrero 2024), verificadas
contra la referencia pública `csf.tools`. Al publicar el catálogo se debe conservar:

- Versión del framework (`CSF 2.0`).
- Fuente de cada subcategoría.
- Fecha de última verificación del mapeo.
- Nota de que el mapeo criterio → subcategoría es interpretación propia, no de NIST.
