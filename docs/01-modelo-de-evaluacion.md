# 01 — Modelo de Evaluación

Este documento define cómo se representa la evidencia, cómo se evalúan los criterios, cómo se calcula
el puntaje final (con ajuste acotado de IA), cómo se agrega por función, cómo se mide la cobertura y
cómo se estima el Tier.

## 1. Dos Jerarquías Relacionadas

```text
Jerarquía del marco (taxonomía NIST):
  Marco → Función → Categoría → Subcategoría

Jerarquía de evaluación (metodología propia):
  Criterio → Evidencias requeridas → Resultado → Agregados
```

- Un **criterio** se mapea a una o más **subcategorías** NIST (ej. `CRI-PR-01` → `PR.DS-01`).
- Las **evidencias** alimentan criterios, nunca puntajes directamente.
- Los **resultados de criterio** se agregan hacia subcategoría → categoría → función → global.

### Nota: evidencia operativa y motor operativo

Los eventos en vivo **no modifican la madurez directamente**. El motor operativo (doc 08) genera
incidentes y planes, y **emite hechos operativos** (declarado, escalado, verificado). Esos hechos
entran al pipeline de eventos y se convierten en `log.pattern`/`log.window` por ventana; solo entonces
alimentan criterios de Detect, Respond y Recover. La evaluación consulta una ventana de la organización;
nunca recibe un “puntaje” del motor operativo.

## 2. Contrato de Evidencia

Se distinguen dos conceptos:

### 2.1 Definición del tipo de evidencia (inmutable)

```yaml
id: tf.encryption.config
version: 1
descripcion: "Configuración de cifrado en reposo declarada para un recurso de almacenamiento o base de datos."
valor_schema:
  type: object
  required: [estado]
  properties:
    estado: { enum: [enabled, disabled, unknown] }
    mecanismo: { type: [string, "null"] }   # ej. AES256, aws:kms
    llave: { type: [string, "null"] }        # ej. alias/aws/rds
modalidad_permitida: [declarada]
publicado: 2026-09-30
estado: published
```

Reglas:

- Una versión publicada **no se modifica jamás**. Si cambia el significado o el esquema, se publica `version: 2`.
- Los criterios y adaptadores referencian `id@version`.
- Las versiones antiguas permanecen para reproducir evaluaciones históricas.

### 2.2 Instancia de evidencia (append-only)

Cada observación concreta es una instancia con estos campos:

| Campo | Descripción |
|---|---|
| `type_id`, `type_version` | Tipo y versión del contrato. |
| `subject_type`, `subject_ref` | Sujeto observado (ej. `aws_db_instance.principal`, `doc:politica-seguridad`). |
| `scope` | Alcance (ej. `entorno:produccion`, `sistema:pagos`). |
| `value` | Dato estructurado según el esquema del tipo. |
| `source_id`, `locator` | Fuente y localización exacta (archivo+líneas, página+sección, evento id). |
| `observed_at` | Momento de la observación (o tiempo de evento). |
| `modality` | `declarada` \| `documental` \| `operativa` \| `contexto`. |
| `limitations` | Información incompleta, cobertura parcial, expresión no resuelta. |
| `created_by` | `adapter:terraform` \| `adapter:ansible` \| `ai:extraction` \| `surveillance` (evidencia operativa de eventos) \| `manual`. |

Las instancias **nunca se sobrescriben**. Una nueva recolección crea instancias nuevas en una evaluación nueva.

## 3. Estados de un Resultado de Criterio

| Estado | Significado | ¿Aporta puntaje? |
|---|---|---|
| `evaluado` | Evidencia suficiente; se calcula puntaje. | Sí |
| `no_implementado` | Evidencia explícita de ausencia (ej. `disabled`) o una falla observada en los eventos. Todo puntaje 0 tiene este estado (lo fija el motor, docs/09 §63); la UI lo muestra como “Ausente o fallido”. | Sí, 0 |
| `evidencia_insuficiente` | No se puede concluir (falta de evidencia o `unknown`). | No; resta cobertura |
| `no_aplicable` | Exclusión justificada por contexto (con motivo registrado). | No; no resta cobertura |
| `error` | El análisis no pudo completarse (parser, IA inválida, etc.). | No; resta cobertura |

Reglas:

- **La ausencia de evidencia no es una falla**: es `evidencia_insuficiente`. Esto incluye el **silencio documental**: que los documentos analizados no declaren algo (o el modelo lo marque como no encontrado) no es `no_implementado`, porque la organización puede no haber aportado el documento correspondiente (docs/09 §60).
- `no_aplicable` exige un motivo explícito y queda auditado.
- Un estado `error` es visible y no se oculta promediando.

## 4. Rúbrica de Puntaje por Criterio

Escala 0–100 con anclas (adaptable por criterio en la metodología):

| Valor | Ancla |
|---|---|
| 0 | Sin implementación; evidencia explícita de ausencia en todo el alcance (ningún recurso cifra, administración expuesta a Internet) o falla observada. |
| 25 | Implementación parcial, aislada o incompleta en la mayoría del alcance. |
| 50 | Implementada en parte del alcance, con brechas relevantes. |
| 75 | Implementada en todo el alcance evaluado, sin verificación completa. |
| 100 | Implementada, verificada y con evidencia completa (incluye registro de revisión/ejercicio cuando aplique). |

Cada criterio en `03-matriz-de-criterios.md` define su regla concreta para asignar el valor.
La rúbrica genérica es el marco; la regla específica manda.

## 5. Puntaje Final de un Criterio (Ajuste de IA)

### 5.1 Fórmula

```text
B         = puntaje base determinístico (0..100)
A         = puntaje contextual propuesto por IA (0..100)
D         = divergencia máxima permitida (configurable; inicial: 20)
α         = peso de la IA (configurable; inicial: 0.25)

A_acotado = clamp(A, B - D, B + D)
S         = round(clamp((1 - α) · B + α · A_acotado, 0, 100))
```

El valor **visible y agregable es `S`**. `B`, `A`, `A_acotado` y la justificación se conservan
internamente para auditoría y explicación (“ajuste contextual: +5”).

### 5.2 Ejemplo

```text
B = 60, A = 90, D = 20, α = 0.25
A_acotado = 80
S = 0.75·60 + 0.25·80 = 65
```

### 5.3 Restricciones

| # | Restricción |
|---|---|
| R1 | Solo criterios marcados `ai_adjustable: true` admiten ajuste. |
| R2 | El ajuste debe justificarse con evidencias identificables (IDs) y contexto declarado. |
| R3 | La IA no altera hechos: no cambia el valor de una evidencia ni el estado `no_implementado`. |
| R4 | La IA no convierte `evidencia_insuficiente` en `evaluado` ni sube desde ese estado. |
| R5 | Si la respuesta es inválida o vacía: ajuste = 0, criterio marcado `degradado`, evaluación continúa. |
| R6 | Los parámetros `D` y `α` pertenecen a la metodología versionada; la IA no los elige. |
| R7 | El contexto de negocio (p. ej. criticidad) puede matizar el **ajuste de IA (U2, docs/05 §3)**, pero no decide por sí solo la **prioridad** de un plan: hoy la prioridad sale de la severidad del hallazgo (OP-01, docs/12 §3). |
| R8 | Todo ajuste queda registrado con modelo, versión de prompt, entrada y salida. |

## 6. Agregación Jerárquica

```text
Criterios ──► Subcategoría ──► Categoría ──► Función ──► Global (opcional)
```

- Cada nivel es un **promedio ponderado por criterio**, con el `Peso` de la matriz, de los criterios que
  pertenecen a ese nivel: una subcategoría promedia los criterios mapeados a ella, una categoría los
  criterios que la listan y una función todos sus criterios. **No** se promedian promedios (una categoría
  no es la media de sus subcategorías): así un criterio pesa lo mismo esté donde esté (regla A4), y un
  criterio que cubre dos subcategorías no cuenta doble dentro de su categoría.
- **Global** = promedio ponderado de las 6 funciones con puntaje (inicial: pesos iguales; configurable en
  `settings.yml`).

Reglas de agregación:

| # | Regla |
|---|---|
| A1 | Solo entran al promedio los resultados `evaluado` y `no_implementado`. |
| A2 | `no_aplicable` no entra en el denominador. |
| A3 | `evidencia_insuficiente` y `error` no entran al promedio, pero reducen la cobertura. |
| A4 | Si una subcategoría tiene más criterios que otra, se pondera por criterio, no por cantidad de criterios. |
| A5 | Si una categoría no tiene ningún criterio evaluado, se muestra “no evaluable”. |
| A6 | Si todas las funciones están no evaluables, no existe puntaje global. |

Cada agregado reporta: `puntaje`, `cobertura`, y conteo de estados.

## 7. Cobertura

Se reportan dos métricas distintas — nunca se mezclan:

```text
Cobertura de implementación (metadata del producto):
  subcategorías con ≥1 criterio implementado
  ─────────────────────────────────────────────
  106 subcategorías del núcleo de CSF 2.0

Cobertura de evidencia (por evaluación):
  criterios aplicables con estado evaluado/no_implementado
  ─────────────────────────────────────────────────────────
  criterios aplicables totales (incluye evidencia_insuficiente y error)
```

La cobertura global usa esta misma fórmula sobre **todos** los criterios de la evaluación; no es el promedio
de las coberturas por función (eso pesaría igual una función de 3 criterios que una de 6). Corregido en
docs/09 §59.

La **cobertura de implementación** se calcula en `app/methodology/coverage.py` sobre
`methodology/csf_subcategories.yml` (las 106 subcategorías) y se expone en `GET /methodology`;
hoy son **74/106 (69,8 %)**, las **22 categorías** tienen criterio (`categorias_sin_criterio`
vacía desde la Oleada A) y **10 están completas**, entre ellas las seis de la función Gobernar,
que queda en 31/31 (docs/09 §68, §73, §77). Es metadato del producto: constante para una versión de
metodología y sin efecto sobre ningún puntaje. La **cobertura de evidencia** es la de abajo, por
evaluación, y es la única que marca un puntaje como provisional. No se mezclan ni se suman.

- `criterios aplicables` = todos menos `no_aplicable`.
- Un puntaje de 80/100 con cobertura 30% se muestra como **provisional**: `Aggregate.provisional` es
  verdadero cuando la cobertura es menor que `cobertura.umbral_provisional` (`settings.yml`, 0.5) y
  hay puntaje. Aplica a cada agregado y al global; el Tier tiene su propia marca (T2).
- La UI/API siempre devuelve puntaje y cobertura juntos.

## 8. Tier Estimado

### 8.1 Naturaleza

- El Tier es **organizacional** (no por función).
- Es una estimación propia basada en indicadores del catálogo, inspirada en las descripciones de NIST
  (SP 1302), no una traducción oficial de puntajes.
- Puede ser `provisional` si faltan indicadores esenciales.

### 8.2 Indicadores por Tier (inicial)

> La fuente canónica de estos umbrales es `methodology/settings.yml` (ver `04-arquitectura-backend.md §8`).
> La tabla siguiente es una copia ilustrativa para lectura humana; en caso de discrepancia, manda el YAML.

| Tier | Nombre | Requisitos mínimos (criterios y umbrales) |
|---|---|---|
| 1 | Partial | Base: sin requisitos. Se asigna si no se alcanza Tier 2. |
| 2 | Risk Informed | `CRI-GV-01 ≥ 50` (política o gestión aprobada), `CRI-GV-02 ≥ 50` (roles), `CRI-ID-03 ≥ 50` (riesgos) |
| 3 | Repeatable | Requisitos de T2 + `CRI-GV-01 ≥ 75`, `CRI-GV-03 ≥ 75` (tolerancia), `CRI-GV-04 ≥ 75` (revisión), `CRI-DE-01 ≥ 75` (monitoreo), `CRI-RS-01 ≥ 75` (plan de respuesta), `CRI-RC-01 ≥ 75` (recuperación), `CRI-RC-02 ≥ 75` (backups probados) |
| 4 | Adaptive | Requisitos de T3 + `CRI-GV-04 = 100` (mejora basada en resultados), `CRI-RS-02 ≥ 75` (análisis de incidentes), `CRI-RC-03 ≥ 75` (restauración verificada y comunicada), `CRI-ID-04 ≥ 75` (inventario de datos), `CRI-ID-05 ≥ 75` (ciclo de mejora continua) |

### 8.3 Reglas

| # | Regla |
|---|---|
| T1 | Tier estimado = el mayor Tier cuyos requisitos se cumplen plenamente. |
| T2 | Si un requisito está en `evidencia_insuficiente` o `error`, el Tier es `provisional`. |
| T3 | Si no se puede evaluar ningún requisito de T2, el Tier se reporta como “no estimable”. “Evaluar” significa que el criterio dio puntaje (`evaluado` o `no_implementado`): todo criterio tiene siempre un resultado, así que un requisito en `evidencia_insuficiente`/`error` no cuenta. |
| T4 | Los umbrales son parámetros de metodología versionada; se recalibran con datos, no con opiniones. |
| T5 | El informe muestra qué falta para alcanzar el siguiente Tier (ruta de mejora). |
| T6 | Los umbrales se comparan contra el puntaje **final** `S` (con el ajuste de IA, si lo hubo), no contra el base: el sistema es tan determinista como se puede sin descartar el matiz que aporta la IA. Como los puntajes base caen en las anclas, en la práctica un ajuste puede hacer perder un umbral (75 → 74) pero no ganarlo. |

### 8.4 Niveles por función (opcional, no NIST)

Para lectura ejecutiva se puede mostrar la banda del puntaje por función, siempre con nombre propio:

| Banda | Rango | Etiqueta propia |
|---|---|---|
| A | 85–100 | Consolidado |
| B | 70–84 | Gestionado |
| C | 50–69 | En desarrollo |
| D | 0–49 | Inicial |

> Estas bandas **no son** los Tiers de NIST y no deben rotularse como tales.

## 9. Ejemplo Trabajado: Cifrado en Reposo (CRI-PR-01)

Entradas:

```text
Evidencias:
  E1: tf.encryption.config@1  RDS "principal"        estado=enabled   fuente: main.tf L40-42
  E2: tf.encryption.config@1  S3 "documentos"       estado=disabled  fuente: storage.tf L12-15
  E3: doc.claim@1             "Política exige cifrado en reposo"     fuente: politica-datos.pdf p.3

Regla del criterio:
  - Todos enabled → 100
  - Alguno disabled → 25 (la observación técnica prevalece)
  - unknown → insuficiente para ese recurso; se puntúa sobre los resueltos
  - Sin recursos del tipo → no_aplicable

Cálculo base:
  E2 (disabled) prevalece sobre E3 (documental genérica) → B = 25
  estado = evaluado

Ajuste IA:
  A = 35 (reconoce política formal y recurso no crítico)
  D = 20, α = 0.25 → A_acotado = 35 (dentro de [B-D, B+D] = [5, 45]) → S = 0.75·25 + 0.25·35 ≈ 28
```

Salida visible: `CRI-PR-01 = 28`, con explicación “ajuste contextual: +3” y referencia a E1–E3.

## 10. Reproducibilidad

Una evaluación registra:

- `methodology_version` (versión de criterios, de tipos de evidencia, de settings —pesos,
  umbrales, α, D— y del núcleo CSF).
- Versiones de tipos de evidencia usadas.
- Versión de adaptadores/parsers.
- Modelo y versión de prompt de IA (para ajustes y extracción).

Implementado en `assessments.reproducibility` (adaptador y parser por fuente; modelo y prompt de
IA solo si participó), docs/09 §37. `methodology_version` se fija al ejecutar el pipeline (no al
encolar), para que la evaluación registre la versión que realmente usó (docs/09 §85). Con eso, dos
evaluaciones son comparables y un cambio de puntaje se puede atribuir a: nueva evidencia, nuevo
criterio, nuevo parser o nuevo modelo.
