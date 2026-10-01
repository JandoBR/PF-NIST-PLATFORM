# 10 — Multitenancy y Autenticación

Diseño de la separación por organización mediante login. Un despliegue atiende a **varias
organizaciones**; cada usuario pertenece a una y solo ve su organización. El proveedor (nosotros)
crea las cuentas fuera de la app; el cliente no se registra.

> Reemplaza la decisión anterior "una organización por despliegue" (doc 04 §10). Sigue fuera de
> alcance un panel de administración web: la administración se hace por seed/CLI.

## 1. Alcance

| Dentro | Fuera (prototipo) |
|---|---|
| Usuarios con login (usuario/contraseña), sesión por token | Registro de cuentas por el cliente |
| Aislamiento de datos por organización en toda la API | Panel de administración web |
| Cuentas precreadas (seed) para la demo | Recuperación de contraseña, cambio de contraseña |
| `GET /auth/me` para restaurar sesión | OAuth/SSO, MFA, roles granulares |
| El cliente ve solo su organización | Rate limiting de login, refresh tokens |

## 2. Modelo de datos

Nueva tabla `users` (una organización tiene N usuarios):

| Campo | Descripción |
|---|---|
| `id` | UUID. |
| `org_id` | FK a `organizations` — la organización a la que pertenece el usuario. |
| `username` | Único, usado para login. |
| `password_salt`, `password_hash` | PBKDF2-HMAC-SHA256 (200 000 iteraciones). Nunca contraseña en claro. |
| `role` | `"client"` por ahora (reservado para `"admin"` futuro). |
| `creado_en` | Timestamp. |

`organizations` no cambia; se le agrega la relación `users`.

## 3. Sesión y token

- `POST /auth/login` con `username`/`password` verifica y devuelve:
  ```json
  { "token": "...", "user": { "id": "...", "username": "demo", "org_id": "...", "org_nombre": "Organización Demo", "role": "client" } }
  ```
- El token es **firmado y stateless**: `base64url(payload).base64url(HMAC-SHA256(payload))`, con
  `payload = { sub: user_id, org: org_id, exp }`. Se firma con `SECRET_KEY` (env).
  - Se eligió stateless para no depender de Redis ni de una tabla de sesiones, y para que
    `api`/workers compartan el mismo secreto sin estado compartido.
  - `AUTH_TOKEN_TTL_HOURS` (env, default 72) controla la expiración.
- El cliente manda `Authorization: Bearer <token>` en cada request.
- Error 401 si falta el token, la firma no valida, o expiró.

## 4. Aislamiento por organización (scoping)

| Ruta | Comportamiento con sesión |
|---|---|
| `POST /assessments` | Fuerza la organización del usuario; ignora cualquier `org_name` del cliente. |
| `GET /assessments` | Devuelve solo las evaluaciones de la organización del usuario. |
| `GET /assessments/{id}` y sub-recursos | 404 si el assessment no es de su organización. |
| `POST /assessments/{id}/reevaluate`, `/plans`, `/compare` | Igual: 404 si no es suyo. |
| `POST /orgs/{org_id}/events`, `GET /orgs/{org_id}/incidents` | 404 si `org_id` ≠ la del usuario. |
| `GET /incidents/{id}`, `/incidents/{id}/plans` | 404 si el incidente no es de su organización. |
| `GET /jobs/{id}` | 404 si el job no pertenece a su organización. |
| `GET/POST /orgs` | Se restringe: `GET /orgs` devuelve solo su organización. `POST /orgs` deja de estar disponible para el cliente (la creación la hace el seed/CLI). |
| `GET /methodology`, `GET /health` | Públicos (catálogo y salud, sin datos de cliente). |

Se responde **404, no 403**, para no revelar la existencia de recursos de otras organizaciones.

## 5. Cuentas precreadas (seed)

Al arrancar la API, si no existen, se crean:

| Usuario | Contraseña | Organización |
|---|---|---|
| `demo` | `demo123` | Organización Demo |
| `smoke` | `smoke123` | Smoke E2E |

- Idempotente: si el `username` ya existe, no se toca.
- Desactivable con `SEED_DEMO_USERS=0` (los tests lo desactivan).
- La administración real (crear organización + primer usuario) queda para una CLI/seed futuro; el
  cliente nunca crea organizaciones.

## 6. Frontend

- Pantalla de **login** (usuario/contraseña). Sin registro.
- El token se guarda en `localStorage`; todas las llamadas lo envían en `Authorization`.
- `GET /auth/me` al montar restaura la sesión; un 401 en cualquier llamada limpia el token y vuelve
  al login.
- Se **elimina el campo libre de "organización"** al crear una evaluación: la organización sale de
  la sesión y se muestra como contexto fijo.
- El historial y los datos ya vienen filtrados por el backend, así que no hay mezcla entre
  organizaciones.

## 7. Configuración

- `SECRET_KEY`: obligatoria en despliegues reales (firma de tokens). En el prototipo hay un default
  inseguro documentado; se agrega al `.env.example` del backend y de `deploy/`.
- `AUTH_TOKEN_TTL_HOURS`: opcional, default 72.
- `SEED_DEMO_USERS`: default `1`; los tests lo ponen en `0`.

## 8. Riesgos y notas

- **Token en `localStorage`** es vulnerable a XSS; aceptable para el prototipo, no para producción.
  Evolución: cookie `HttpOnly` + `SameSite`.
- **`SECRET_KEY` por defecto** solo sirve para demo; hay que fijarla por entorno.
- **Sin rate limiting ni bloqueo por intentos** en login: fuera de alcance.
- Las contraseñas de seed son de demo y deben rotarse/eliminarse antes de cualquier uso real.
