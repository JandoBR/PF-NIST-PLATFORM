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
| **Estados** | `evaluado`, `no_implementado`, `evidencia_insuficiente`, `no_aplicable`, `error` |

Reglas transversales:

- La rúbrica genérica de 0/25/50/75/100 está en `01-modelo-de-evaluacion.md §4`.
- La observación técnica prevalece sobre la documental (D7).
- `unknown` produce `evidencia_insuficiente` para el recurso afectado, nunca un valor inventado.
- Las recomendaciones son plantillas; la IA las adapta y explica, sin ejecutar nada.

Resumen de cobertura del catálogo:

| Función | Criterios | MVP total | MVP parcial |
|---|---|---|---|
| Govern | 4 | 3 | 0 |
| Identify | 4 | 3 | 0 |
| Protect | 6 | 6 | 0 |
| Detect | 3 | 1 | 1 |
| Respond | 3 | 1 | 0 |
| Recover | 3 | 2 | 1 |
| **Total** | **23** | **16** | **2** |

> **Estado de implementación:** **23 de 23** criterios implementados (CR-01…CR-05, docs/11 §C).
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
  - 0: el documento no declara política alguna (`encontrado: false` en todos los documentos).
  - Sin documentos analizados → `evidencia_insuficiente`.
- **Recomendación:** formalizar/aprobar la política; definir ciclo de revisión (anual sugerido) y registrar la última revisión.

### CRI-GV-02 — Roles y responsabilidades definidos
- **Subcategorías:** GV.RR-01, GV.RR-02 · **Tipo:** Proceso · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Tier:** T2
- **Evidencias:** `doc.claim(tipo=role_assigned)`
- **Regla:**
  - 100: responsables nombrados por rol (CISO/responsable de seguridad, dueños de activos), con responsabilidades y autoridad descritas.
  - 75: responsables definidos sin autoridad explícita.
  - 50: roles genéricos (“el área de TI”) sin asignación.
  - 0: no se declara.
- **Recomendación:** designar responsable de seguridad y dueños de activos con responsabilidades y autoridad explícitas.

### CRI-GV-03 — Objetivos de riesgo y tolerancia establecidos
- **Subcategorías:** GV.RM-01, GV.RM-02 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** sí · **Tier:** T3
- **Evidencias:** `doc.claim(tipo=risk_tolerance)`
- **Regla:**
  - 100: objetivos de gestión de riesgo y declaración de tolerancia/apetito documentados y con responsable.
  - 75: objetivos definidos sin tolerancia explícita.
  - 50: declaración genérica de “gestionar riesgos”.
  - 0: no se declara.
- **Recomendación:** documentar objetivos de riesgo y una declaración de tolerancia usada en decisiones operativas.

### CRI-GV-04 — Revisión del desempeño y mejora de la estrategia
- **Subcategorías:** GV.OV-01, GV.OV-03 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** no · **Tier:** T3/T4
- **Evidencias:** `doc.claim(tipo=policy_review)`, `doc.claim(tipo=process_defined)`
- **Regla:**
  - 100: existe proceso de revisión con métricas/resultados y evidencia de ajustes realizados.
  - 75: revisión periódica definida sin evidencia de ajustes.
  - 50: revisión mencionada informalmente.
  - 0: no se declara.
- **Recomendación:** institucionalizar una revisión periódica de la estrategia basada en resultados y registrar los ajustes.

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
  - 0: no existe inventario documentado.
  - La cobertura se calcula sobre tipos de recurso, y se registra como limitación que solo se evalúan tipos soportados.
- **Recomendación:** mantener un inventario de activos que incluya los recursos desplegados y su responsable.

### CRI-ID-02 — Priorización de activos por criticidad
- **Subcategorías:** ID.AM-05 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** sí
- **Evidencias:** `doc.claim(tipo=data_inventory)`, `ctx.profile(activos_criticos)`
- **Regla:**
  - 100: clasificación de criticidad documentada y consistente con los activos críticos declarados en contexto.
  - 50: clasificación mencionada sin criterios.
  - 0: no se declara.
- **Recomendación:** clasificar activos por criticidad y usarlo para priorizar controles y esfuerzo.

### CRI-ID-03 — Identificación y evaluación de riesgos
- **Subcategorías:** ID.RA-01, ID.RA-05 · **Tipo:** Proceso · **Peso:** 4 · **IA:** sí · **MVP:** sí · **Tier:** T2
- **Evidencias:** `doc.claim(tipo=process_defined)`
- **Regla:**
  - 100: proceso de evaluación de riesgos documentado, con registro de riesgos y priorización por impacto/probabilidad.
  - 75: proceso definido sin registro de riesgos.
  - 50: evaluación descrita de forma genérica.
  - 0: no se declara.
- **Recomendación:** establecer una evaluación de riesgos repetible con registro y priorización.

### CRI-ID-04 — Inventario de datos y metadatos *(privacidad, secundaria)*
- **Subcategorías:** ID.AM-07 · **Tipo:** Proceso · **Peso:** 2 · **IA:** sí · **MVP:** no · **Tier:** T4
- **Evidencias:** `doc.claim(tipo=data_inventory)`
- **Regla:**
  - 100: inventario de datos con tipos, ubicación y clasificación (incluye datos personales).
  - 50: inventario parcial o sin clasificación.
  - 0: no se declara.
- **Recomendación:** documentar qué datos existen, dónde residen y su clasificación, incluyendo datos personales.

---

## 3. PROTECT (PR)

### CRI-PR-01 — Cifrado de datos en reposo
- **Subcategorías:** PR.DS-01 · **Tipo:** Técnico · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Privacidad:** Protect-P
- **Evidencias:** `tf.encryption.config` (RDS, S3), `doc.claim(tipo=policy_exists)`
- **Regla (por recurso soportado):**
  - Todos `enabled` → 100.
  - Alguno `disabled` → 25 (prevalece sobre la política).
  - `unknown` → el recurso pasa a `evidencia_insuficiente`; se puntúa sobre los resueltos y se registra la limitación.
  - Sin recursos del tipo → `no_aplicable` con motivo.
  - Política documental sin recursos: no eleva el puntaje técnico; alimenta contexto y el hallazgo.
- **Recomendación:** habilitar cifrado gestionado por KMS en RDS y S3; verificar mecanismo y llave.

### CRI-PR-02 — Backups configurados y protegidos
- **Subcategorías:** PR.DS-11 · **Tipo:** Técnico · **Peso:** 5 · **IA:** sí · **MVP:** sí
- **Evidencias:** `tf.backup.config` (retención), `doc.claim(tipo=backup_policy)`
- **Regla:**
  - 100: retención configurada ≥ política documentada y backups con cifrado (instancia RDS con cifrado `enabled`; si no está confirmado, tope 75).
  - 75: retención configurada ≥ 7 días sin otros detalles.
  - 50: backups habilitados con retención < política.
  - 25: retención en 0 o backups deshabilitados explícitamente.
  - `unknown` → insuficiente.
- **Recomendación:** alinear retención de backups con la política y asegurar su cifrado.

### CRI-PR-03 — Acceso administrativo restringido
- **Subcategorías:** PR.AA-05, PR.IR-01 · **Tipo:** Técnico · **Peso:** 4 · **IA:** no · **MVP:** sí · **Privacidad:** Protect-P
- **Evidencias:** `tf.security_group.rules`
- **Regla:**
  - 100: sin reglas que expongan SSH (22) o RDP (3389) desde `0.0.0.0/0` o `::/0`, y SSH con acceso restringido.
  - 25: cualquier regla que exponga administración a Internet.
  - Se registra que es configuración declarada; no demuestra accesibilidad efectiva.
  - Sin security groups evaluables → insuficiente.
- **Recomendación:** restringir puertos administrativos a rangos corporativos/VPN y eliminar reglas `0.0.0.0/0`.

### CRI-PR-04 — Configuración segura del servidor (SSH)
- **Subcategorías:** PR.PS-01 · **Tipo:** Técnico · **Peso:** 3 · **IA:** no · **MVP:** sí
- **Evidencias:** `an.task.config` (sshd_config: `PermitRootLogin`, `PasswordAuthentication`), `an.file.permissions`
- **Regla:**
  - 100: `PermitRootLogin no` y `PasswordAuthentication no` declarados.
  - 75: solo uno de los dos endurecido.
  - 50: SSH configurado sin opciones explícitas de endurecimiento.
  - 25: `PermitRootLogin yes` o `PasswordAuthentication yes` explícito.
  - `an.file.permissions` sobre `sshd_config` con escritura para grupo/otros → tope 25.
  - Sin tareas de SSH interpretadas → insuficiente.
- **Recomendación:** deshabilitar login de root y autenticación por contraseña; usar claves.

### CRI-PR-05 — Almacenamiento protegido contra acceso público
- **Subcategorías:** PR.DS-01 · **Tipo:** Técnico · **Peso:** 3 · **IA:** no · **MVP:** sí · **Privacidad:** Protect-P
- **Evidencias:** `tf.public_access.config`, `tf.versioning.config` (informativa), `tf.db_exposure.config`
- **Regla:**
  - 100: bloqueo de acceso público en los 4 modos (ACL, política, ignorar, restringir) declarado.
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

---

## 4. DETECT (DE)

### CRI-DE-01 — Monitoreo de red y cómputo
- **Subcategorías:** DE.CM-01, DE.CM-09 · **Tipo:** Mixto · **Peso:** 5 · **IA:** no · **MVP:** sí · **Tier:** T3 · **Privacidad:** apoyo Detect
- **Evidencias:** `tf.logging.config`, `an.service.state`, `log.window` (¿hubo actividad observable?)
- **Regla:**
  - 100: fuentes de log habilitadas y recolección/centralización declarada.
  - 75: fuentes habilitadas sin centralización declarada.
  - 50: parcialmente habilitadas.
  - 0: sin monitoreo declarado.
  - Si no existe ventana de observación ni configuración → insuficiente, no 0.
- **Recomendación:** centralizar logs y definir fuentes mínimas de monitoreo (red, sistema, nube).

### CRI-DE-02 — Análisis de eventos y declaración de incidentes
- **Subcategorías:** DE.AE-02, DE.AE-08 · **Tipo:** Mixto · **Peso:** 4 · **IA:** sí · **MVP:** parcial · **Privacidad:** Protect-P + apoyo Detect
- **Evidencias:** `doc.claim(tipo=process_defined)`, `log.pattern(alert_raised|incident_declared)`
- **Regla:**
  - 100: criterios de declaración documentados + evidencia operativa de alerta/declaración en el escenario.
  - 75: criterios documentados sin evidencia operativa (o viceversa).
  - 50: análisis descrito sin criterios de declaración.
  - 0: no se declara.
  - Sin regla conocida aplicable al escenario → no se penaliza (ver doc 06 §5).
- **Recomendación:** definir criterios de declaración de incidentes y registrar alertas con su análisis.

### CRI-DE-03 — Información de eventos a personal y herramientas
- **Subcategorías:** DE.AE-06 · **Tipo:** Mixto · **Peso:** 3 · **IA:** sí · **MVP:** no
- **Evidencias:** `log.pattern(alert_raised)`, `doc.claim(tipo=notification_list)`
- **Regla:**
  - 100: alertas llegan a destinatarios definidos y el escenario lo evidencia.
  - 75: destinatarios definidos sin evidencia operativa.
  - 0: sin definición ni evidencia.
- **Recomendación:** definir destinatarios de alertas y verificar la entrega.

---

## 5. RESPOND (RS)

### CRI-RS-01 — Plan de respuesta con clasificación y escalamiento
- **Subcategorías:** RS.MA-01, RS.MA-02, RS.MA-03, RS.MA-04 · **Tipo:** Mixto · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Tier:** T3 · **Privacidad:** Protect-P + apoyo Respond
- **Evidencias:** `doc.claim(tipo=process_defined)`, `doc.claim(tipo=escalation_path)`, `log.pattern(escalation_done|incident_declared)`
- **Regla:**
  - 100: plan documentado con triaje, categorización, priorización y escalamiento + evidencia operativa de escalamiento en el escenario.
  - 75: plan completo sin evidencia operativa.
  - 50: plan parcial (p. ej. sin escalamiento).
  - 0: no se declara plan.
  - Sin escenario operativo disponible → se evalúa solo lo documental y se registra la limitación.
- **Recomendación:** documentar y ensayar el plan de respuesta incluyendo escalamiento y criterios de prioridad.

### CRI-RS-02 — Análisis de incidentes y preservación de evidencia
- **Subcategorías:** RS.AN-03, RS.AN-07 · **Tipo:** Mixto · **Peso:** 3 · **IA:** sí · **MVP:** no · **Tier:** T4
- **Evidencias:** `doc.claim(tipo=process_defined)`, `log.pattern(incident_declared)`
- **Regla:**
  - 100: proceso de análisis de causa raíz y conservación de evidencia documentado y evidenciado en el escenario.
  - 75: documentado sin evidencia operativa.
  - 0: no se declara.
- **Recomendación:** definir análisis de causa raíz y preservación de evidencia con registros.

### CRI-RS-03 — Notificación a partes interesadas
- **Subcategorías:** RS.CO-02 · **Tipo:** Proceso · **Peso:** 3 · **IA:** sí · **MVP:** no · **Privacidad:** Protect-P + apoyo Respond
- **Evidencias:** `doc.claim(tipo=notification_list)`
- **Regla:**
  - 100: lista de notificación interna/externa con criterios y plazos.
  - 75: lista definida sin plazos.
  - 0: no se declara.
- **Recomendación:** definir a quién, cuándo y cómo se notifica un incidente.

---

## 6. RECOVER (RC)

### CRI-RC-01 — Procedimiento de recuperación definido y ejecutable
- **Subcategorías:** RC.RP-01, RC.RP-02 · **Tipo:** Proceso · **Peso:** 5 · **IA:** sí · **MVP:** sí · **Tier:** T3 · **Privacidad:** Protect-P + apoyo Recover
- **Evidencias:** `doc.claim(tipo=process_defined)`, `doc.claim(tipo=backup_policy)`
- **Regla:**
  - 100: procedimiento con pasos, responsables, prioridades y criterios de activación.
  - 75: procedimiento definido sin criterios de activación.
  - 50: recuperación mencionada de forma genérica.
  - 0: no se declara.
- **Recomendación:** documentar el procedimiento de recuperación con responsables y criterios de inicio.

### CRI-RC-02 — Verificación de integridad de backups
- **Subcategorías:** RC.RP-03 · **Tipo:** Mixto · **Peso:** 4 · **IA:** sí · **MVP:** sí · **Tier:** T3
- **Evidencias:** `doc.claim(tipo=backup_policy)`, `log.pattern(restore_exercise_run|restore_verified)`
- **Regla:**
  - 100: política exige verificación de integridad + evidencia operativa de restauración verificada.
  - 75: verificación documentada sin evidencia operativa reciente.
  - 50: pruebas de restauración mencionadas sin periodicidad.
  - 0: no se declara verificación.
- **Recomendación:** verificar integridad de backups antes de restaurar y registrar la prueba.

### CRI-RC-03 — Restauración verificada y comunicación de recuperación
- **Subcategorías:** RC.RP-05, RC.CO-03 · **Tipo:** Mixto · **Peso:** 3 · **IA:** sí · **MVP:** parcial · **Tier:** T4
- **Evidencias:** `log.pattern(restore_verified)`, `doc.claim(tipo=notification_list)`
- **Regla:**
  - 100: restauración confirmada en el escenario + comunicación a stakeholders definida/evidenciada.
  - 75: restauración verificada sin comunicación.
  - 50: recuperación ejecutada sin verificación final.
  - 0: sin evidencia de restauración ni procedimiento.
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
