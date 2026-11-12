# PF-NIST-PLATFORM: instrucciones para agentes

Evaluador de madurez NIST CSF 2.0 / PF 1.0: backend FastAPI (`backend/`), frontend React + Vite
(`frontend/`), despliegue con Docker Compose (`deploy/`). Código, docs y commits en español.
`frontend/AGENTS.md` aplica solo al trabajo de diseño en Penpot.

## Verificar

Desde la raíz del repo:

- Tests backend: `nix develop -c bash -c 'cd backend && DATABASE_URL=sqlite:////tmp/pf-test.db uv run pytest -q'`
  (~2 min, unos 1000 tests). En NixOS `uv run` fuera de `nix develop` falla. Para iterar, pasa
  archivos concretos; la suite completa, una vez al final.
- Lint backend: `nix develop -c bash -c 'cd backend && ruff check . && ruff format --check .'`.
  Usa el `ruff` del devshell: el binario de la venv no arranca en NixOS.
- Frontend: `cd frontend && npm ci && npm run typecheck && npm run lint && npm run build`.
- Varios agentes en paralelo: cada uno en su worktree, y solo uno corre la suite completa.

## Convenciones que los tests o la trazabilidad exigen

- `docs/09-registro-de-implementacion.md` es un registro que solo crece: cada cambio relevante
  añade una entrada `## N. …` al final. No se reescriben entradas viejas.
- `backend/methodology/criteria.yml`: cambiar un criterio sube `version:`. `docs/03` debe coincidir
  (`tests/test_criteria_matrix_doc.py`), y las 25 subcategorías no cubiertas deben seguir
  justificadas en `docs/12` (`tests/test_csf_scope_documented.py`).
- Si cambia lo que emite un adaptador, se sube su `ADAPTER_VERSION`. Si cambia un prompt de IA, se
  crea un archivo nuevo (`prompts/extract_vN.txt`) y se sube `PROMPT_VERSION`; los viejos no se
  editan.
- Goldens (`backend/tests/golden`): regenerar con `UPDATE_GOLDEN=1` solo si el cambio es
  intencional, y revisar el diff.
- Esquema de BD: migración Alembic en `backend/alembic/versions/`. En SQLite (dev y tests),
  `app/core/db.py` añade tablas y columnas que falten.
- El contrato de evidencia está en `evidence_types.yml`; un campo nuevo en `doc.claim` sube su
  `type_version`.

## IA

- DeepSeek (`DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL=deepseek-flash`, modelo con razonamiento). Las
  llamadas reales cuestan: en tests se usan clientes falsos. No llames a la API sin necesidad y
  nunca imprimas la key.
- Los resultados se guardan en la tabla `ai_results`, por organización y por contenido. U1 vota
  entre `U1_VOTES` extracciones. Ver docs/05.

## Stack local

- `cd deploy && docker compose up -d --build`; el código va dentro de la imagen, así que hay que
  reconstruir para ver cambios. `deploy/.env` (no versionado) manda sobre las variables del shell.
- UI en `http://localhost:5173`, API en `http://localhost:8000`, usuario demo `demo` / `demo123`.
- Paquetes demo en `frontend/public/demo/{gaps,mid,good}` y logs en `frontend/public/demo/events/`.
  Cada escenario se evalúa con su propio log, elegido por ingesta.
