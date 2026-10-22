# 00 — Visión y Contexto

## 1. Problema

En organizaciones que usan infraestructura como código, la información de seguridad está repartida entre:

- Archivos de infraestructura (Terraform).
- Automatización de servidores (Ansible).
- Documentos de políticas y procedimientos (PDF, Markdown, texto).
- Logs y registros operativos.

Evaluar la madurez de ciberseguridad de forma manual es lento, difícil de repetir y queda obsoleto rápido.
Los reportes estáticos no muestran qué evidencia respalda cada conclusión ni cómo verificar una mejora.

## 2. Propuesta

Una plataforma que:

1. **Ingesta evidencia** de múltiples fuentes y la normaliza bajo un contrato común.
2. **Evalúa** esa evidencia contra un catálogo de criterios propios mapeados a NIST CSF 2.0.
3. **Calcula** un puntaje por función, cobertura de evidencia y un Tier organizacional estimado.
4. **Interpreta y recomienda** con IA, dentro de límites explícitos y con trazabilidad completa.

> Diferenciador: responder *¿qué encontramos, con qué evidencia, qué objetivo afecta, qué desconocemos
> y cómo comprobamos la mejora?* — no solo “usar RAG”.

## 3. Alcance y Límites

| Dentro del alcance | Fuera del alcance (prototipo) |
|---|---|
| NIST CSF 2.0 completo como estructura de despliegue | Evaluar todas las subcategorías de NIST |
| Subconjunto de 25 criterios definidos (16 MVP + 2 parciales), 46 de 106 subcategorías | Cobertura exhaustiva del framework |
| Privacidad secundaria vía solapamiento con Identify-P y Protect-P | Evaluación integral de privacidad (PF 1.0 completo) |
| Terraform (AWS), Ansible, documentos y logs simulados | Múltiples nubes, agentes reales, SIEM |
| Configuración declarada y prácticas documentadas | Estado real de la infraestructura desplegada |
| Asesoría y planes de mejora/recovery | Ejecución automática de acciones o remediación |
| Logs simulados reproducibles | Vigilancia de sistemas reales en tiempo real |
| Motor operativo mínimo (incidentes y planes por escenario) | Detección continua, correlación avanzada, SIEM |
| Desplegable con Docker + Redis | Orquestación con Kubernetes, alta disponibilidad |
| Multitenancy con login (varias organizaciones por despliegue) | Registro por el cliente, panel de administración, OAuth/SSO |

**El sistema no certifica.** Emite una estimación metodológica propia, con evidencia trazable y límites declarados.

## 4. Decisiones de Diseño

| # | Decisión | Razón |
|---|---|---|
| D1 | CSF 2.0 con sus 6 funciones (GV, ID, PR, DE, RS, RC) | Estructura principal del producto. |
| D2 | Privacidad secundaria: solo la intersección con ciberseguridad | El solapamiento PROTECT-P ↔ DETECT/RESPOND/RECOVER. |
| D3 | Las prácticas documentadas se asumen ciertas | El sistema no audita la veracidad de los documentos. |
| D4 | Evidencias con contrato predefinido e inmutable | Permite cambiar recolectores sin tocar la evaluación. |
| D5 | Los criterios son fijos; la IA extrae evidencia (U1), matiza con contexto (U2) y redacta planes (U3), pero nunca crea criterios | Evita criterios ambiguos generados por el modelo. |
| D6 | Un único puntaje visible por criterio, con ajuste de IA acotado | Simplicidad para el usuario, trazabilidad interna. |
| D7 | La observación técnica prevalece sobre la documental | Un recurso explícito en Terraform contradice una política genérica. |
| D8 | Tier mediante rúbrica propia inspirada en NIST, separado del puntaje | NIST no define una fórmula oficial puntaje → Tier. |
| D9 | La IA nunca inventa hechos ni ejecuta acciones | Principio de asesoría. |
| D10 | Logs simulados con tiempo de evento, no de reproducción | Permite evaluar ventanas temporales de forma reproducible. |
| D11 | Monolito modular en Python | Velocidad de desarrollo para 5 semanas; sin microservicios. |
| D12 | Nodo operativo de primera clase sobre el mismo stream de eventos | Separa asesoría en vivo (incidentes/planes) de la evaluación de madurez. |
| D13 | Redis para la cola de eventos y trabajos (la caché de extracción IA es en disco) | Simplifica el desacoplamiento sin añadir mucha complejidad. |
| D14 | Despliegue con Docker + docker-compose | Todo el prototipo es reproducible con `docker compose up`. |
| D15 | Multitenancy con login: varias organizaciones por despliegue, aisladas por usuario | El cliente ve solo su organización; las cuentas las crea el proveedor (seed). Ver doc 10. |

### Sobre los Tiers

NIST describe los Tiers (Partial, Risk Informed, Repeatable, Adaptive) como una caracterización del **rigor
de la gobernanza y gestión del riesgo**, no como niveles de madurez con fórmula oficial. Por eso:

- El puntaje y la cobertura son **índice propio**.
- El Tier es una **estimación propia** derivada de un subconjunto de criterios “indicadores de Tier”.
- La documentación del producto siempre distingue “inspirado en NIST” de “oficial de NIST”.

## 5. Fuentes de Evidencia

| Fuente | Qué aporta | Modalidad de evidencia |
|---|---|---|
| Terraform (AWS) | Recursos declarados: RDS, S3, security groups, CloudTrail | Configuración declarada |
| Ansible | Tareas declarativas: SSH, logs, permisos, servicios | Configuración declarada |
| Documentos | Políticas, roles, procedimientos, frecuencias | Afirmación documental (extraída por IA) |
| Logs / eventos | Actividad operativa: detección, escalamiento, restauración (flujos A y B) | Evento observado (simulado en el prototipo) |
| Contexto de la organización | Sector, activos críticos, datos, perfil objetivo | Contexto declarado (formulario) |

## 6. Relación con NIST

```text
CSF 2.0 (principal)                  Privacy Framework 1.0 (secundario)
┌─────────────────────────┐          ┌──────────────────────────────┐
│ GOVERN    IDENTIFY      │          │ IDENTIFY-P    GOVERN-P       │
│ PROTECT   DETECT        │◄────────►│ CONTROL-P   COMMUNICATE-P    │
│ RESPOND   RECOVER       │          │ PROTECT-P                    │
└─────────────────────────┘          └──────────────────────────────┘
                   intersección evaluada:
       PROTECT-P  ↔  DETECT / RESPOND / RECOVER (eventos de privacidad
                    derivados de incidentes de ciberseguridad)
```

- No existen funciones `DETECT-P` ni `RESPOND-P` en PF 1.0.
- La dimensión de privacidad del prototipo se limita a: protección de datos personales
  (cifrado, acceso) y tratamiento de incidentes que afecten información personal.
- Esta delimitación se declara explícitamente en todo reporte del sistema.

## 7. Principios

1. **Determinismo primero:** el resultado base se calcula con reglas y evidencia, no con IA.
2. **IA acotada:** interpreta, explica y propone ajustes limitados; nunca sustituye hechos.
3. **Evidencia trazable:** cada hallazgo apunta a origen, regla, versión y limitaciones.
4. **Instantáneas:** cada evaluación es inmutable; reevaluar genera una nueva versión comparable.
5. **Abstención:** sin evidencia suficiente el sistema declara “no evaluable”, no inventa un puntaje.
6. **Asesoría:** nunca ejecuta acciones sobre infraestructura o sistemas.

## 8. Glosario

| Término | Significado |
|---|---|
| **Evidencia** | Observación normalizada sobre un sujeto y alcance, con procedencia. |
| **Tipo de evidencia** | Contrato versionado que define el significado y esquema de una observación. |
| **Criterio** | Condición evaluable con regla, rúbrica y evidencias requeridas. |
| **Resultado de criterio** | Estado y puntaje de un criterio para una evaluación concreta. |
| **Puntaje base (B)** | Puntaje determinístico del criterio antes del ajuste de IA. |
| **Puntaje ajustado (S)** | Resultado final tras el ajuste contextual acotado de IA. |
| **Cobertura de implementación** | Porcentaje del framework para el que existe al menos un criterio. |
| **Cobertura de evidencia** | Porcentaje de criterios aplicables con evidencia suficiente. |
| **Tier estimado** | Clasificación 1–4 propia derivada de indicadores de gobernanza y gestión. |
| **Hallazgo** | Brecha o contradicción detectada, vinculada a criterios y evidencia. |
| **Plan** | Conjunto de acciones priorizadas con condición de verificación. |
| **Evaluación** | Instantánea completa: fuentes, evidencias, resultados, ajustes y planes. |
| **Incidente** | Entidad operativa que agrupa eventos correlacionados y dispara un plan. |
| **Motor operativo** | Consumidor continuo del stream que genera incidentes y planes (flujo B). |
| **Flujo A / B** | A: madurez (evidencia por ventana). B: operativo (incidentes y planes). |
| **Organización (tenant)** | Cliente del servicio; agrupa sus evaluaciones, eventos e incidentes. |
| **Usuario** | Cuenta con login, pertenece a una organización; ve solo la suya. |
| **Sesión / token** | Token firmado que el usuario presenta en `Authorization` para autenticarse. |
