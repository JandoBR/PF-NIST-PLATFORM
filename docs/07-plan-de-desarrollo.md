# 07 — Plan de Desarrollo

Prototipo académico, 4 integrantes, 5 semanas. El objetivo es un **recorrido vertical completo**,
no cobertura exhaustiva. La ampliación dentro de esas semanas consiste en agregar criterios, tipos de
evidencia y escenarios **sin cambiar los contratos**.

## 1. Criterio de Éxito del Prototipo

1. Se analiza un entorno sintético (Terraform + Ansible + documentos + logs) y produce evidencias trazables.
2. El motor calcula puntajes por función/categoría, cobertura y Tier estimado.
3. La IA extrae evidencia documental con citas y ajusta puntajes dentro de límites.
4. Se generan planes de mejora y de recovery, sin ejecutar acciones.
5. Un escenario de eventos abre un incidente y genera un plan de respuesta, y sus hechos alimentan la madurez.
6. Una corrección de brechas produce una nueva evaluación comparable que muestra la mejora.
7. El flujo completo es reproducible con fixtures y tests, y levanta con `docker compose up`.

## 2. Cronograma de 5 Semanas

| Semana | Objetivo | Entregables | Criterio de salida |
|---|---|---|---|
| **1** | Cimientos | Catálogo YAML (`criteria.yml`, `evidence_types.yml`, `settings.yml`), modelo de datos + migraciones, API básica (`POST/GET assessments`), ingesta de fuentes con checksum, Redis y esqueleto Docker (`deploy/`, `backend/docker/`). | `docker compose up` levanta API, workers, Postgres y Redis; un caso sintético mínimo produce una evaluación vacía persistida y consultable. |
| **2** | Adquisición | Adaptador Terraform (RDS, S3, SG, CloudTrail), adaptador Ansible (SSH, logs, permisos), extracción documental con IA + validación, evidencias `doc.claim` con citas. | Las cuatro fuentes generan evidencias bajo el mismo contrato, sin IA en el camino crítico de Terraform/Ansible. |
| **3** | Evaluación | Motor de criterios, rúbricas, agregación jerárquica, cobertura, Tier estimado, ajuste IA acotado, endpoints de scores/criteria. | La API devuelve score único por criterio con desglose coherente, cobertura y versiones registradas. |
| **4** | Eventos, motor operativo y planes | Pipeline Redis Streams + patrones, entidad `incident` y disparadores determinísticos, criterios de DE/RS/RC alimentados por logs, planes (mejora y recovery) con IA y plantillas, compare entre evaluaciones. | Un escenario E1–E3 actualiza los criterios pertinentes; un escenario de fallo abre incidente y genera plan; corregir brechas mejora el score en la evaluación nueva. |
| **5** | Validación y cierre | Tests golden, evaluación de la IA (extracción y ajuste), manejo de fallos, documentación final, guion de demo, datos de demo estables. | Demo completa extremo a extremo; límites documentados; suite de tests repetible. |

## 3. Backlog Priorizado

### MVP obligatorio (semanas 1–4)

- [ ] Cargador de metodología YAML con validación Pydantic.
- [ ] Tablas + migraciones del modelo de datos.
- [ ] Ingesta de archivos (tipo, checksum, tamaño, errores).
- [ ] Adaptador Terraform: `aws_db_instance`, `aws_s3_bucket`, `aws_security_group`, `aws_cloudtrail`.
- [ ] Adaptador Ansible: módulos declarativos del alcance.
- [ ] Extracción documental: chunking + prompt v1 + validación + citas.
- [ ] Motor de evaluación: 16–19 criterios MVP con reglas.
- [ ] Agregación + cobertura + Tier estimado.
- [ ] Ajuste IA con `α`, `D` y degradación controlada.
- [ ] Simulador de eventos + 3 escenarios + patrones publicados en Redis Streams.
- [ ] Entity `incident` + disparadores determinísticos + cooldown (motor operativo mínimo).
- [ ] Planes de mejora y de recovery (plantillas + IA), un plan por incidente.
- [ ] Endpoints: assessments, sources, run, jobs, scores, criteria, evidence, findings, plans, events, incidents, reevaluate, compare, methodology.
- [ ] Cola/stream y caché en Redis; workers `core` y `logs` (evita Celery).
- [ ] `deploy/docker-compose.yml`, `deploy/.env.example` y Dockerfiles funcionando.

### Ampliación si alcanza el tiempo

- [ ] Criterios MVP `parcial` y `no` (GV-04, DE-03, RS-02, RS-03, RC-03, ID-04).
- [ ] Comparación visual de evaluaciones (React).
- [ ] Más tipos de recursos Terraform (IAM, VPC, RDS snapshots).
- [ ] Recuperación semántica sobre el catálogo NIST (embeddings).
- [ ] Exportación PDF del informe ejecutivo.

### Fuera de alcance (documentar como trabajo futuro)

- Múltiples nubes y proveedores.
- Agentes reales / integración con nube o SIEM.
- Ejecución de remediaciones.
- Multiusuario, OIDC, multi-tenant.

## 4. Estrategia de Validación

| Nivel | Qué se prueba | Herramienta | Evidencia de éxito |
|---|---|---|---|
| Unitario | Parsers, reglas de criterio, fórmulas (α, D, agregación, cobertura, tier) | pytest | Casos borde: unknown, n/a, estados mixtos |
| Golden files | Terraform/Ansible → evidencias esperadas | pytest + fixtures | Diff vacío contra resultados anotados |
| Motor | Conjuntos de evidencias → puntajes esperados | pytest | Cálculo reproducible por caso |
| IA extracción | Golden set de documentos anotados | script de evaluación | ≥ 90 % afirmaciones correctas, 0 invenciones, citas localizables |
| IA ajuste | Límites y degradación | tests con respuestas simuladas (válidas, vacías, malformadas) | `S` siempre acotado; degradado sin crash |
| Contradicciones | Técnico vs documental | fixtures | Prevalece técnica; hallazgo registrado una sola vez |
| Vigilancia | Escenarios E1–E3 y variante E3-b | fixtures JSONL | Patrones y criterios actualizados como se espera |
| Motor operativo | Flujo correcto y fallos (D1, D3, D4) | fixtures JSONL | Incidente solo con disparador; un plan por incidente; sin ruido |
| E2E | Flujo completo | test de integración | Evaluación inicial → corrección → mejora demostrada |
| Demo | Estabilidad del guion | ejecución repetida | Resultados idénticos entre corridas |

## 5. Riesgos y Mitigaciones

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| La IA introduce inconsistencias | Alta | Medio | Validación estricta, citas obligatorias, degradación, comparación con/sin IA |
| Terraform con expresiones que el parser no resuelve | Alta | Bajo | `unknown` explícito + limitación visible; no bloquea |
| Extracción documental pobre en PDFs reales | Media | Medio | Documentos de demo controlados; umbral de confianza; fixtures anotados |
| Tiempo insuficiente para toda la matriz | Media | Alto | MVP fijo (16 criterios); ampliación opcional; contratos estables |
| Redis no disponible en la demo | Baja | Alto | Compose con healthcheck y reintentos; ejecución síncrona de respaldo |
| Confusión entre madurez y motor operativo | Media | Medio | Contratos y flujos separados (A/B); tests que verifican que los eventos no alteran scores directamente |
| Costos de API | Baja | Bajo | Caché por `sha256`, límites de chunks y tokens |
| Dependencia del proveedor IA | Media | Medio | Interfaz interna `ai/client`; el sistema funciona con `S = B` |
| Subcategorías NIST mal citadas | Baja | Medio | Catálogo verificado contra fuente; nota de interpretación propia |

## 6. Guion de Demo (10–12 min)

1. **Contexto (1 min):** empresa ficticia, sistema pequeño, perfil objetivo.
2. **Carga inicial (1 min):** Terraform + Ansible + políticas + escenario de logs.
3. **Evaluación (2 min):** hallazgos; desglose por función/categoría/subcategoría; cobertura; Tier estimado.
4. **IA (2 min):** extracción con citas (mostrar una afirmación y su fragmento); ajuste contextual visible (+5) y su justificación.
5. **Plan de mejora (2 min):** acciones priorizadas con verificación.
6. **Corrección (1 min):** aplicar cambios en los fixtures de Terraform/Ansible.
7. **Re-evaluación y comparación (2 min):** nueva evaluación, diff de puntajes, mejora demostrada.
8. **Eventos y motor operativo (1–2 min):** cargar E3-b; disparador D4 abre un incidente y genera un plan de recovery; mostrar los hechos operativos alimentando los criterios; aclarar que nada se ejecuta.

## 7. Definición de Terminado

- Código con tests pasando (`pytest`) y lint configurado.
- Cada criterio implementado tiene al menos un test golden.
- Sin secretos en el repositorio; `.env.example` documentado.
- `docker compose -f deploy/docker-compose.yml up` levanta todo el sistema sin pasos manuales.
- Documentación de límites actualizada (qué no cubre el prototipo).
- El guion de demo corre de punta a punta sin intervención manual sobre la base de datos.

## 8. Trabajo Futuro

- Cobertura completa de CSF 2.0 y ampliación del cruce con Privacy Framework.
- Evidencia observada en vivo (consultas de solo lectura a AWS) junto a la declarada.
- Agentes de recolección para Ansible con hechos reales.
- Recuperación semántica y explicaciones más ricas sobre referencias NIST.
- Calibración de α, D y umbrales de Tier con datos de validación.
- Frontend React completo con vistas ejecutiva y técnica.
