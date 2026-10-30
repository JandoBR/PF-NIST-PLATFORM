# 02 — Catálogo de Evidencias

Contratos de evidencia del prototipo, reglas de extracción de cada adaptador y tratamiento de
contradicciones y valores desconocidos.

## 1. Familias de Evidencia

| Prefijo | Familia | Origen | Modalidad |
|---|---|---|---|
| `tf.*` | Terraform | Adaptador HCL | `declarada` |
| `an.*` | Ansible | Adaptador YAML | `declarada` |
| `doc.*` | Documentos | Extracción con IA | `documental` |
| `log.*` | Logs / eventos | Ingesta y correlación | `operativa` |
| `ctx.*` | Contexto organizacional | Formulario / carga manual | `contexto` |

## 2. Contrato Completo de un Tipo

```yaml
id: <prefijo>.<nombre>          # inmutable junto con la versión
version: 1
descripcion: >
  Significado exacto de la observación.
valor_schema: <JSON Schema>     # estructura del campo value
modalidad_permitida: [declarada | documental | operativa | contexto]
requiere_locator: true|false    # si exige archivo+líneas / página / id de evento
estado: draft | published | deprecated
publicado: <fecha>
notas: >
  Límites conocidos del tipo (qué NO puede afirmarse con esta evidencia).
```

Ejemplo completo:

```yaml
id: tf.security_group.rules
version: 1
descripcion: >
  Reglas de ingress/egress declaradas en un security group, normalizadas por protocolo,
  rango de puertos y CIDR de origen/destino.
valor_schema:
  type: array
  items:
    type: object
    required: [direccion, protocolo, puerto_desde, puerto_hasta, cidr]
    properties:
      direccion: { enum: [ingress, egress] }
      protocolo: { type: string }        # tcp, udp, icmp, -1
      puerto_desde: { type: [integer, "null"] }
      puerto_hasta: { type: [integer, "null"] }
      cidr: { type: string }             # 0.0.0.0/0, ::/0, 10.0.0.0/16, sg-xxx
modalidad_permitida: [declarada]
requiere_locator: true
estado: published
publicado: 2026-09-30
notas: >
  Una regla permisiva NO demuestra accesibilidad efectiva: la conectividad depende de
  subredes, rutas, NACLs y del recurso destino. Solo afirma intención de configuración.
```

## 3. Catálogo Inicial

### 3.1 Terraform (`tf.*`)

| ID | value (resumen) | Uso principal |
|---|---|---|
| `tf.resource.present` | `{ tipo, nombre, entorno? }` | Inventario y existencia de recursos soportados. |
| `tf.attr.value` | `{ recurso, atributo, valor\|unknown, motivo_unknown? }` | **No se emite** (docs/09 §57): el adaptador produce tipos específicos por tema (cifrado, backup, acceso…) y un volcado genérico de atributos no lo consume ningún criterio. Los atributos no resueltos van en `tf.expression.unresolved`. |
| `tf.encryption.config` | `{ estado, mecanismo?, llave? }` | Cifrado en reposo (RDS, S3). |
| `tf.public_access.config` | `{ bloqueo_publico: bool\|unknown, nivel? }` | Acceso público a almacenamiento (S3). |
| `tf.db_exposure.config` | `{ publico: bool\|unknown }` | Accesibilidad pública de bases de datos (`publicly_accessible`); ausente o expresión → `unknown`. |
| `tf.backup.config` | `{ retencion_dias?: int, habilitado?: bool, ventana? }` | Retención de backups (RDS). |
| `tf.logging.config` | `{ habilitado: bool\|unknown, multi_region?, destino? }` | CloudTrail / logging declarado. |
| `tf.security_group.rules` | reglas normalizadas (ver §2) | Exposición de red de grupos de seguridad. |
| `tf.versioning.config` | `{ habilitado: bool\|unknown }` | Versionado de almacenamiento. |
| `tf.resilience.config` | `{ mecanismo, habilitado?, capacidad_minima?, capacidad_maxima?, estado }` | Resiliencia declarada. `multi_az`/`replica` son alta disponibilidad (PR.IR-03); `autoescalado` es capacidad elástica (PR.IR-04) y su `habilitado` es cierto solo si `max_size > min_size`. Un `multi_az` ausente da `estado: no_declarado`, **no** `unknown`: `unknown` está reservado a un valor que el parser no pudo leer y genera hallazgo de limitación. |
| `tf.identity.config` | `{ tipo, longitud_minima?, requiere_simbolos?, requiere_numeros?, rotacion_dias?, reutilizacion_bloqueada?, mfa_requerido?, estado }` | Autenticación de la cuenta. `tipo: politica_de_contrasenas` trae los atributos de `aws_iam_account_password_policy`; `tipo: mfa` dice si el documento de una política IAM exige `aws:MultiFactorAuthPresent` (en AWS no hay atributo para eso). Un documento no literal → `estado: unknown`, nunca `mfa_requerido: false`. |
| `tf.module.source` | `{ nombre, source?, version?, origen, fijada, estado }` | Procedencia de un bloque `module`. `origen`: `registry`/`git`/`externo`/`local`/`desconocido`; `local` es código del propio repositorio, que no se adquiere y por tanto no se fija. `fijada` es cierto con `version` (registry) o con `?ref=<tag\|sha>` en el `source` (git). |
| `tf.provider.version` | `{ proveedor, restriccion?, fijada, estado }` | Restricción de versión de un proveedor en `terraform { required_providers }`. Declarado sin `version` → `restriccion: null`: no es lo mismo que no declararlo. |
| `tf.expression.unresolved` | `{ recurso, atributo, expresion, motivo }` | Limitación explícita del parser. |

Alcance del adaptador: recursos **`aws_db_instance`, `aws_s3_bucket` (+ `aws_s3_bucket_*`),
`aws_security_group`, `aws_cloudtrail`**. Todo otro recurso produce `tf.resource.present` si se
reconoce el bloque, o se ignora registrando la limitación.

> Un bucket sin `aws_s3_bucket_server_side_encryption_configuration` explícito no se asume
> cifrado: `tf.resource.present` lo delata y PR-01 lo trata como `unknown`/insuficiente
> (docs/03 §3). El adaptador no inventa un `tf.encryption.config` que el usuario no declaró.

### 3.2 Ansible (`an.*`)

| ID | value (resumen) | Uso principal |
|---|---|---|
| `an.playbook.present` | `{ archivo, plays, hosts }` | Detectar automatización existente. |
| `an.task.config` | `{ modulo, parametros, tarea, archivo }` | Tareas declarativas interpretadas. |
| `an.file.permissions` | `{ ruta, modo, owner? }` | Permisos sobre archivos sensibles. |
| `an.service.state` | `{ servicio, estado }` | Servicios de seguridad habilitados. |
| `an.task.uninterpreted` | `{ tarea, motivo }` | Tareas con `command`, `shell`, plantillas complejas o condicionales no resolubles. |

Alcance inicial: módulos `lineinfile`, `copy`, `template` (solo rutas), `file`, `service`,
`ufw`/`iptables` (parámetros básicos). **No se ejecuta ningún playbook ni comando.**

### 3.3 Documentos (`doc.*`)

| ID | value (resumen) | Uso principal |
|---|---|---|
| `doc.claim` | `{ tipo_afirmacion, contenido, encontrado, confianza, cita }` | Afirmación estructurada extraída por IA. **v2** guarda la cita textual; si la cita no aparece en el texto analizado, la afirmación se guarda con una limitación y no cuenta para puntuar (docs/05 E8). v1 queda para evaluaciones anteriores. |
| `doc.source.info` | `{ titulo, archivo, secciones, analizadas, omitidas, sin_respuesta }` | Marca de documento analizado (E6): cuántas secciones tenía y cuántas contestó la IA. No se emite si la IA no contestó ninguna. Se muestra en el informe. (`version_documento`/`fecha` no se extraen: el texto del documento no los garantiza.) |

Tipos de afirmación (`tipo_afirmacion`) usados por los criterios:

| tipo_afirmacion | Campos esperados en `contenido` |
|---|---|
| `policy_exists` | `{ nombre, aprobada_por?, fecha? }` |
| `policy_review` | `{ frecuencia, ultima_revision? }` |
| `role_assigned` | `{ roles: [{ rol, responsable, responsabilidades, autoridad }] }` |
| `risk_tolerance` | `{ objetivos_riesgo, tolerancia?, responsable? }` |
| `process_defined` | `{ proceso, pasos, responsables?, criterios_activacion?, criterios_declaracion?, registro_riesgos?, priorizacion?, metricas?, ajustes? }` |
| `escalation_path` | `{ niveles: string, criterios?: string\|null }` (extraído por U1 desde CR-05) |
| `notification_list` | `{ destinatarios[], criterios?, plazos? }` |
| `backup_policy` | `{ respaldo, verificacion_integridad?, retencion? }` |
| `exposure_policy` | `{ bases_publicas_permitidas: bool\|null, descripcion? }` (PR-05; contradicción con `tf.db_exposure.config`) |
| `training_program` | `{ alcance, frecuencia }` *(declarado; aún no extraído por U1)* |
| `data_inventory` | `{ activos[], tipos_datos[], clasificacion?, criticidad? }` |

Reglas de extracción:

- Cada afirmación exige **fragmento textual y localización** (página/sección). Sin cita → se descarta.
- `encontrado: false` es válido: significa “el documento no lo declara”, no “no existe”.
- La confianza baja (`< umbral`) se marca como limitación y no se usa como evidencia suficiente.
- No se piden ni se persisten credenciales, claves ni datos personales: el modelo solo extrae los campos declarados. La **redacción de secretos antes de enviar** está pendiente para uso real (docs/12 SEC-07).

### 3.4 Logs (`log.*`)

| ID | value (resumen) | Uso principal |
|---|---|---|
| `log.event` | evento individual normalizado (ver doc 06) | **No se emite como evidencia** (docs/09 §57): los eventos viven en la tabla `events` y las evaluaciones consumen sus ventanas y patrones (`log.window`, `log.pattern`; docs/08 §3). |
| `log.pattern` | `{ patron, resultado, desde, hasta, conteo, fuentes }` | Evidencia operativa agregada. `fuentes` (v2) son los orígenes de los eventos que forman el patrón: es lo único que permite afirmar correlación entre sistemas y no solo detección (DE.AE-03, docs/09 §75). Lista vacía = ningún evento declaró origen, **no** "un solo origen". |
| `log.window` | `{ desde, hasta, completo: bool }` | Completitud de la ventana observada. |

Patrones iniciales: `auth_failures_burst`, `alert_raised`, `incident_triaged`, `containment_done`,
`incident_declared`, `escalation_done`, `restore_exercise_run`, `restore_verified`,
`recovery_communicated` (docs/06 §3, docs/09 §53).

### 3.5 Contexto (`ctx.*`)

| ID | value (resumen) |
|---|---|
| `ctx.profile` | `{ sector, tamano, activos_criticos[], tipos_datos[], nube, perfil_objetivo }` |
| `ctx.exclusions` | `{ recurso_o_criterio, motivo, aprobado_por }` (alimenta `no_aplicable`) |

## 4. Valores Desconocidos y Expresiones

| Situación | Tratamiento |
|---|---|
| Atributo con expresión simple resoluble (variable local literal) | **No se resuelve** (decisión deliberada, docs/09 §54): una variable cuenta como expresión no resuelta (fila siguiente) y el criterio decide con `unknown`. Lo único que el adaptador resuelve es la referencia directa de un recurso S3 de configuración a su `aws_s3_bucket` local; la evidencia queda ligada al bucket (`subject_ref`), sin marca aparte. |
| Atributo con función, `for_each`, `count`, módulo o referencia remota | `unknown` + `tf.expression.unresolved` con motivo (emitido por el adaptador sobre los atributos que deciden un puntaje; docs/09 §36). Un bloque `dynamic "ingress"/"egress"` se emite además como regla con `cidr: unknown`, no se omite. |
| Ansible con `command`, `shell`, plantilla compleja, `when` no evaluable | `an.task.uninterpreted`. |
| Atributo simplemente ausente | **No** se asume `false`; produce `unknown` con motivo `atributo_ausente`, salvo default documentado del proveedor. |
| Default conocido del proveedor (ej. S3 cifra nuevas cargas por defecto) | Se registra como `unknown` y el criterio decide; no se asume cumplimiento automático. |

> `unknown` nunca equivale a `disabled` ni a `enabled`. Alimenta `evidencia_insuficiente`.

## 5. Precedencia de Fuentes y Contradicciones

Regla base (D7): **una observación técnica explícita prevalece sobre una afirmación documental
cuando ambas hablan del mismo recurso, propiedad y alcance.**

| Caso | Tratamiento | Efecto |
|---|---|---|
| Política dice “BD no pública”; Terraform dice `publicly_accessible = true` | Prevalece Terraform. Se registra contradicción. | El criterio usa el valor técnico; se crea hallazgo de coherencia. |
| Política dice “backups 7 días”; Terraform dice `backup_retention_period = 1` | La política fija un requisito que la configuración incumple. | La política sigue contando: el criterio puntúa retención < política (50) y se crea el hallazgo. |
| Política dice “hay responsable de incidentes”; Terraform no aporta nada | Se acepta la evidencia documental. | Sin contradicción; el criterio de proceso usa `doc.claim`. |
| Terraform tiene expresión no resuelta | No contradice al documento; es limitación. | Criterio → `evidencia_insuficiente` para ese recurso. |
| Fuentes de entornos o momentos distintos | No se comparan ni contradicen. | Requieren mismo `scope` y ventana compatible. |
| Dos documentos se contradicen | Se registran ambos; el criterio decide con su regla (usualmente gana la fuente más reciente o específica). | Hallazgo de contradicción documental. |

Las contradicciones se registran como **hallazgos** con ambos lados citados (evidencia + locator).
No penalizan doble: el hallazgo referencia el criterio afectado una sola vez.

**Efecto en el puntaje:** una afirmación documental que afirma un **hecho** que otra fuente desmiente
(“hay respaldos” con retención 0, “la base no es pública” siendo pública, dos documentos con valores
distintos) **no cuenta** para puntuar el criterio de la contradicción; ese criterio se evalúa como si no existiera, y queda el hallazgo
más una nota en su explicación. La exclusión es por criterio: otros criterios que leen la misma afirmación
por otra propiedad (p. ej. `RC-02` y la verificación de integridad de una política cuya retención contradice
a Terraform) la siguen usando. Una política que fija un **requisito** que la configuración no alcanza
(retención menor que la documentada) no se excluye: es un incumplimiento, lo puntúa la regla del criterio. En documento-vs-documento no cuenta ninguno de los dos (no se elige un ganador). La
evidencia técnica nunca se excluye.

**Tope de puntaje:** mientras un criterio tenga una contradicción sin resolver, su puntaje final **no
puede subir** respecto a la evaluación anterior del mismo org+scope (puede bajar). No penaliza: solo no
premia una mejora técnica que la documentación contradice. El tope se levanta cuando política e
infraestructura dejan de contradecirse. Sin evaluación anterior, o sin puntaje anterior para ese
criterio, no hay tope. El `base_score` (lo que dicen las reglas) no cambia; solo el `final_score`.

Implementado en `app/recommendations/contradictions.py` (docs/09 §38, §40): backup de la política vs
`tf.backup.config`, "BD no pública" (`doc.claim(exposure_policy)`) vs `tf.db_exposure.config`, y dos
documentos con retención o frecuencia de revisión distintas.

## 6. Versionado e Inmutabilidad en la Práctica

| Cambio | Acción |
|---|---|
| Mejora del parser que produce el mismo significado | Nueva versión de adaptador; tipos de evidencia iguales. |
| Cambia el significado de una observación | Nuevo `version` del tipo de evidencia. |
| Cambia la regla de un criterio | Nuevo `version` del criterio; nueva `methodology_version`. |
| Error en una evaluación pasada | No se edita: se crea una evaluación nueva (la anterior queda como histórica). |

## 7. Límites Declarados del Prototipo

- Solo AWS y solo 4 tipos de recurso principales.
- No resuelve módulos remotos de Terraform ni expresiones complejas.
- No ejecuta Ansible ni Terraform; no consulta la nube.
- No interpreta imágenes, escaneos ni PDFs sin capa de texto (se puede declarar límite si aparece).
  Un PDF cifrado con contraseña se omite (cero secciones), no tumba la evaluación.
- Acepta BOM UTF-8 y los tags `!vault`/`!unsafe` de Ansible como valores opacos; no descifra vaults.
  Un encabezado Markdown dentro de un bloque de código no se trata como sección.
- Los logs son simulados; su valor está en demostrar el flujo, no en vigilar un sistema real.
