# Integración del worker en la app (Tattoo Inkprep)

> Documento de handoff para la sesión de Claude en el **repo de la app Flutter**.
> Describe el contrato completo con el worker `Design Analyst` (ya desplegado y
> funcionando). La app y el worker se comunican **solo a través de Supabase**;
> el worker nunca recibe la imagen de mano, la descarga él de Storage.

## 0. Datos de conexión

- **Supabase:** proyecto ref `uhffedvrxsdwizycmgsf` → `https://uhffedvrxsdwizycmgsf.supabase.co`
  - La app usa la **anon key** + Auth de usuario (RLS). NO la service_role.
  - Bucket de Storage: `designs`.
- **Worker (API):** `https://design-analyst-production.up.railway.app`
  - `GET /health` → `{"status":"ok"}`
  - `POST /analyze` → body `{"job_id":"<uuid>"}`, header `X-Worker-Secret: <secreto>` → responde **202** y procesa en background.
- **Secreto compartido `WORKER_SECRET`:** lo tiene Guillermo (está en las env vars
  de Railway y en el `.env` del worker). **NO se hardcodea en la app móvil** (ver §2).

## 1. Flujo de extremo a extremo

```
1. Usuario elige un diseño en la app.
2. App SUBE la imagen al bucket `designs` (Storage).
3. App INSERTA una fila en `design_uploads` (storage_path, formato, dims).
4. App INSERTA una fila en `analysis_jobs` (status='pending', project_id,
   design_upload_id, analysis_source='brands'|'my_inks', y las marcas/tintas elegidas).
5. Se DISPARA el worker: POST /analyze {job_id} con X-Worker-Secret  (ver §2 quién lo hace).
6. App ESPERA a que analysis_jobs.status pase a 'completed' (Realtime o polling).
7. App LEE extracted_colors + match_results (join inks) y los PINTA.
```

## 2. Quién llama al worker (seguridad — IMPORTANTE)

El `POST /analyze` necesita el `WORKER_SECRET`. **No lo metas en el cliente Flutter.**
Dos opciones (recomendada primero):

### Opción A (recomendada, producción): Supabase Edge Function como broker
1. La app, tras crear el job, invoca una **Edge Function** `trigger-analysis`
   (autenticada con el JWT del usuario de Supabase).
2. La Edge Function (servidor de confianza) hace el `POST /analyze` al worker con
   el `WORKER_SECRET` guardado como **secret de la Edge Function** (`supabase secrets set`).
3. Así el secreto vive solo en el servidor; el cliente nunca lo ve.

Esqueleto de la Edge Function (`supabase/functions/trigger-analysis/index.ts`):
```ts
Deno.serve(async (req) => {
  const { job_id } = await req.json();
  const r = await fetch(`${Deno.env.get("ANALYSIS_API_URL")}/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Worker-Secret": Deno.env.get("WORKER_SECRET")!,
    },
    body: JSON.stringify({ job_id }),
  });
  return new Response(await r.text(), { status: r.status });
});
```
Secrets: `supabase secrets set WORKER_SECRET=... ANALYSIS_API_URL=https://design-analyst-production.up.railway.app`.

### Opción A' (aún más desacoplada): Database Webhook → Edge Function
Configura un **Database Webhook** en Supabase sobre `INSERT` en `analysis_jobs`
que llame a la Edge Function. La app entonces SOLO inserta el job (paso 4) y ni
siquiera invoca nada: el webhook dispara el análisis. (La Edge Function recibe el
`record` del webhook y extrae `record.id` como `job_id`.)

### Opción B (solo para pruebas rápidas en local/dev, NO producción)
La app llama directamente a `POST /analyze` con el secreto en una variable de
entorno de build (`--dart-define=WORKER_SECRET=...`). Sirve para iterar rápido,
pero **no publiques la app así**: el secreto sería extraíble del binario.

## 3. Las tablas (contrato exacto, columnas reales verificadas)

### `design_uploads` (la app INSERTA)
| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid | autogenerado |
| `project_id` | uuid | del proyecto del usuario |
| `storage_path` | text | ruta dentro del bucket `designs` |
| `format` | text | `png`/`jpg`/`webp` |
| `width_px`,`height_px`,`size_bytes` | int | opcionales |
| `thumbnail_path` | text | opcional |

### `analysis_jobs` (la app INSERTA con status='pending')
| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid | este es el `job_id` |
| `project_id` | uuid | |
| `design_upload_id` | uuid | = `design_uploads.id` |
| `status` | text | empieza `pending`; el worker lo lleva a `processing`→`completed`/`failed` |
| `analysis_source` | text | `brands` o `my_inks` |
| `selected_brand_ids` | uuid[] | si `brands` |
| `selected_ink_ids` | uuid[] | si `my_inks` |
| `selected_mix_ids` | uuid[] | si `my_inks`: mezclas propias del Lab; puede ser `null` |
| `error_message` | text | lo rellena el worker si falla |
| `completed_at` | timestamptz | lo pone el worker |

> El tono de piel se resuelve por `projects.skin_tone_profile_id`; la app debe
> tenerlo seteado en el proyecto. El worker hace el join solo.

### `extracted_colors` (la app LEE — escrito por el worker) **[v2]**
| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid | |
| `analysis_job_id` | uuid | |
| `hex` | text | `#RRGGBB` color original del diseño |
| `rgb` | jsonb | `{"r":..,"g":..,"b":..}` |
| `lab` | jsonb | `{"l":..,"a":..,"b":..}` |
| `weight` | numeric | fracción [0..1] del diseño |
| `role` | text | `dominant`/`secondary` |
| `best_delta_e` | numeric | **[v2]** ΔE del mejor match |
| `match_quality` | text | **[v2]** `excellent`/`good`/`fair`/`poor` |
| `needs_mix` | bool | **[v2]** true = ninguna tinta sola sirve (futuro: mezcla) |

### `match_results` (la app LEE — escrito por el worker) **[v2]**
Ahora hay **N filas por color** (una por candidata).
| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid | |
| `analysis_job_id` | uuid | |
| `extracted_color_id` | uuid | a qué color responde |
| `match_type` | text | `direct_ink` (bote) o `user_mix` (mezcla propia del Lab) |
| `ink_id` | uuid | → `inks.id`; `null` cuando `match_type='user_mix'` |
| `ink_mix_id` | uuid | siempre `null` (mezclas curadas de catálogo = fase futura) |
| `user_ink_mix_id` | uuid | → `user_ink_mixes.id`; `null` cuando `match_type='direct_ink'` |
| `delta_e` | numeric | distancia de esta candidata |
| `rank` | int | **[v2]** 1 = mejor, 2..N siguientes |

### `inks` (la app LEE para nombre/hex de cada tinta)
Campos útiles: `id`, `brand_id`, `name`, `hex_reference`, `rgb_reference`,
`family`, `official_image_url`, `discontinued`.

## 4. Cómo leer y pintar los resultados (v2)

Por cada `extracted_color` (ordénalos por `weight` desc):
- Pinta el swatch del color (`hex`), su peso y rol.
- Badge de calidad según `match_quality` (excellent/good/fair/poor).
- Si `needs_mix == true`: muestra aviso "requiere mezcla" (de momento sin receta).
- Lista sus `match_results` ordenados por `rank` (1..N) → para cada candidata,
  join a `inks` por `ink_id` para nombre + `hex_reference`, y muestra el `delta_e`
  (cuanto menor, más fiel). Si `match_type='user_mix'`, el nombre y el color
  salen de `user_ink_mixes` (`name`, `result_hex`) en vez de `inks`.

Query de lectura (PostgREST / supabase-dart) — un solo embed anidado:
```sql
-- extracted_colors con sus candidatas (match_results) y la tinta de cada una
select
  ec.*,
  mr:match_results (
    rank, delta_e, ink_id,
    ink:inks ( name, hex_reference, brand_id )
  )
from extracted_colors ec
where ec.analysis_job_id = :job_id
order by ec.weight desc;
```
En supabase-dart:
```dart
final data = await supabase
  .from('extracted_colors')
  .select('*, match_results(rank, delta_e, ink_id, inks(name, hex_reference))')
  .eq('analysis_job_id', jobId)
  .order('weight', ascending: false);
// dentro de cada color, ordena match_results por rank
```

## 5. Esperar a que termine (paso 6)

Dos formas:
- **Realtime (recomendado):** suscríbete a cambios de `analysis_jobs` filtrando por
  `id=job_id`; cuando `status` sea `completed`, lee los resultados.
- **Polling:** consulta `analysis_jobs.status` cada ~2-3s hasta `completed`/`failed`.

El análisis tarda típicamente entre 5 y 20s (diseños ricos, instancia pequeña).
Si `status='failed'`, muestra `error_message`.

## 6. RLS (permisos del lado app)

La app usa la anon key + Auth. Asegúrate de que las **policies RLS** permiten al
usuario dueño del proyecto:
- INSERT/SELECT en `design_uploads`, `analysis_jobs` (de sus proyectos).
- SELECT en `extracted_colors`, `match_results` (de sus jobs), e `inks` (catálogo, lectura pública).
(El worker usa service_role y salta RLS; esto es solo para el cliente.)

## 7. Checklist de prueba real

1. Subir un diseño → ver fila en `design_uploads` y en Storage.
2. Crear el job → fila `analysis_jobs` en `pending`.
3. Disparar análisis (Edge Function/webhook/directo) → `processing` → `completed`.
4. Ver `extracted_colors` (nº variable de colores) con `match_quality`/`needs_mix`.
5. Ver `match_results` con `rank` 1..5 por color.
6. La UI pinta swatches + candidatas + avisos.
7. Probar un `my_inks` con inventario pequeño → verás muchos `needs_mix` (correcto).

## 8. Notas

- El worker es determinista: mismo diseño + mismas tintas elegibles → mismo resultado.
- El nº de colores lo decide el diseño (mando `merge_delta_e` en el worker, hoy 3.0).
- Mezclas (`ink_mix_id`, recetas) = fase futura; hoy `needs_mix` solo avisa.
- Para depurar el worker: `analysis_jobs.error_message` recoge cualquier fallo.
