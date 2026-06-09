# Design Analyst Worker — Tattoo Inkprep

Worker en Python (FastAPI) que analiza diseños de tatuaje y recomienda qué **bote
de tinta** del catálogo reproduce cada color, mediante matching perceptual
(ΔE CIEDE2000). El pipeline es **determinista y trazable**, no IA generativa.
La especificación completa está en [`design_analyst.md`](design_analyst.md).

## Cómo funciona

La app Flutter sube un diseño a Supabase Storage y crea una fila en
`analysis_jobs`. Este worker recibe el `job_id`, descarga la imagen, extrae la
paleta, la ajusta por tono de piel, hace el matching contra las tintas elegibles
y escribe `extracted_colors` + `match_results` en Supabase. La app lee los
resultados de la BD.

```
extracción de paleta (KMeans) → RGB→LAB (canónica) → ajuste por piel → ΔE CIEDE2000 → bote más cercano
```

## Desarrollo local

Requiere **Python 3.12** (coincide con la imagen Docker; scikit-* puede no tener
wheels estables en versiones más nuevas).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # rellena SUPABASE_SERVICE_ROLE_KEY y WORKER_SECRET
pytest                 # tests del pipeline (12 tests)
uvicorn app.main:app --reload
```

## Probar un job real

Con un `job_id` en estado `pending` (creado por la app al subir un diseño):

```bash
python scripts/run_job.py <job_id>
```

El script corre el runner contra el Supabase real; al terminar, `analysis_jobs`
queda `completed` y aparecen filas en `extracted_colors` y `match_results`.

## API

- `GET /health` → `{"status": "ok"}` (healthcheck de Railway).
- `POST /analyze` → body `{"job_id": "<uuid>"}`, header `X-Worker-Secret: <secreto>`.
  Responde **202** y procesa en segundo plano (FastAPI `BackgroundTasks`).

## Variables de entorno

Ver [`.env.example`](.env.example). La `service_role` key de Supabase y el
`WORKER_SECRET` son secretos: solo en variables de entorno, **nunca** en git.

> Nota de setup en Supabase: la `service_role` necesita privilegios sobre las
> tablas del contrato. Si ves `permission denied`, ejecuta en el SQL Editor:
> ```sql
> grant select, update on public.analysis_jobs to service_role;
> grant select on public.inks to service_role;
> grant select on public.skin_tone_profiles to service_role;
> grant select, insert, delete on public.extracted_colors to service_role;
> grant select, insert, delete on public.match_results to service_role;
> ```

## Deploy (Railway)

1. Conecta este repo de GitHub a Railway (deploy al hacer push).
2. Configura las variables de entorno en el panel de Railway.
3. Railway inyecta `$PORT`; el `Dockerfile` arranca uvicorn en ese puerto.
4. Healthcheck: `GET /health`.
5. La URL pública resultante es la que la app usará como `ANALYSIS_API_URL`.

## Alcance V1

Solo **bote directo** (sin mezclas de tinta), con ajuste por tono de piel
(heurístico, pendiente de validación por un tatuador experto). Sin colas ni
webhooks. Ver §13 del brief para lo que queda explícitamente fuera.
