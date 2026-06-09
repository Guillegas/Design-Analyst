# Pipeline v2 — Diseño (Design Analyst, Tattoo Inkprep)

**Fecha:** 2026-06-09
**Estado:** aprobado para escribir plan de implementación
**Autor:** Guillermo + Claude

## Objetivo

Hacer el worker **mucho más exacto y profesional**, para que sea la herramienta
definitiva de un tatuador a color. Hoy resume cada diseño a 6 colores y da 1 tinta
por color. Un tatuaje a color real usa de media ~20 tintas y varía según el diseño.

v2 debe: (1) **captar todos los colores reales** de cada diseño, en número
**variable** auto-detectado; (2) dar **varias tintas candidatas** por color con su
ΔE; (3) **avisar** cuando ninguna tinta sola sirve (haría falta mezcla);
(4) ser **más preciso** trabajando en espacio perceptual de punta a punta.

## Principio rector (no se rompe)

Determinista, trazable, auditable. **Sin IA generativa** en el núcleo: la ciencia
de color (LAB + ΔE CIEDE2000) es exacta y reproducible; una red/LLM sería menos
precisa y no reproducible. Mismo diseño → mismo resultado, con un ΔE que justifica
cada match.

## Alcance

**Dentro de v2:**
- Extracción de paleta v2 (clustering en LAB + fusión perceptual, nº dinámico).
- Detección de fondo por bordes (geométrica + ΔE; no es IA).
- Matching v2: top-N candidatas por color, ranking, ΔE.
- Clasificación de calidad del match + flag `needs_mix`.
- Migraciones de esquema en Supabase.
- Mantener el ajuste por tono de piel actual.

**Fuera de v2 (fases futuras, solo si los diseños reales lo piden):**
- **Mezclas de tinta** (recetas): subsistema propio, su propio spec, validado por
  el experto (padre de Guillermo, tatuador profesional).
- **Balance de blancos** anclado al fondo (clásico/numpy, no IA): para fotos con
  luz no neutra. Decidido: probar primero el sistema determinista al máximo y
  añadirlo solo si hace falta.
- **Segmentación sujeto/fondo con modelo** (rembg/U²-Net): dependencia pesada,
  más RAM/coste; la detección por bordes cubre el caso limpio. Futuro.

## Arquitectura (módulos)

Se mantiene la estructura actual; cambian internos de `palette.py`, `matching.py`,
`runner.py`, `supabase_client.py`, `config.py`. `color.py` y `skin.py` casi intactos.

### `color.py` — conversión de color (CRÍTICO, casi intacto)
- Se conserva `rgb_to_lab` canónica (cuadra exacto con `inks.lab_reference`).
- Se añade una versión **vectorizada** `rgb_to_lab_array(arr)` para convertir
  millones de píxeles a LAB de golpe (numpy), con un test que garantiza que da
  **idénticos** valores que la escalar para los mismos RGB.
- `hex_to_rgb`, `rgb_to_hex` se mantienen.

### `palette.py` — extracción v2
Flujo:
1. Abrir imagen (Pillow); descartar píxeles transparentes (alpha < `alpha_threshold`).
2. **Detección de fondo por bordes:** muestrear los píxeles del borde de la imagen;
   si una fracción ≥ `bg_border_fraction` son un color casi uniforme, ese es el
   fondo → eliminar todos los píxeles a ΔE < `bg_merge_delta_e` de él. Si no hay
   fondo uniforme claro, fallback: eliminar blanco (todos los canales >
   `near_white_threshold`). Configurable/desactivable.
3. Reescalar a `resize_max_side` (512) de lado largo.
4. Convertir píxeles RGB→LAB (`rgb_to_lab_array`). **Clusterizar en LAB** con
   MiniBatchKMeans, `n_clusters = min(kmeans_k_high, nº colores únicos)`.
5. **Fusión perceptual:** fusionar iterativamente los clústeres cuyo ΔE CIEDE2000
   entre centroides sea < `merge_delta_e` (3.5). Al fusionar: sumar pesos y
   recalcular el color representativo como **media RGB ponderada** de los píxeles
   de los clústeres unidos. Repetir hasta que no queden pares por debajo del umbral.
   → el nº de colores **emerge** del diseño.
6. **Ruido y tope:** descartar clústeres con peso < `min_cluster_weight` (0.5%);
   si quedan más de `max_colors` (40), conservar los de mayor peso.
7. **Color representativo y LAB almacenado:** color = media RGB de los píxeles del
   clúster; su LAB se calcula con `rgb_to_lab` **canónica** (consistencia total con
   el catálogo). El clustering/fusión usan LAB perceptual; el LAB guardado y el
   matching usan la canónica.
8. **Pesos y roles:** peso = fracción de píxeles; `dominant` si peso ≥
   `dominant_weight` (0.15) o es el de mayor peso; resto `secondary`.
9. Devolver lista ordenada por peso desc.: `{rgb, hex, lab, weight, role}`.

Resultado: paleta perceptualmente fiel, tamaño variable (típico 8-35), sin ruido.

### `matching.py` — matching v2
Por cada color extraído (ya pre-compensado por piel → LAB):
1. ΔE CIEDE2000 contra **todas** las tintas elegibles, **vectorizado** (numpy +
   skimage sobre arrays: 35 colores × 1105 tintas es instantáneo).
2. Ordenar ascendente; tomar las primeras `candidates_n` (5) → lista de candidatas
   con `rank` (1..N) y `delta_e`.
3. **Calidad** del mejor (rank 1), umbrales configurables:
   - `excellent` ΔE ≤ `quality_excellent` (2.0)
   - `good` ΔE ≤ `quality_good` (5.0)
   - `fair` ΔE ≤ `quality_fair` (10.0)
   - `poor` ΔE > `quality_fair` → `needs_mix = true`
4. Devolver, por color: `best_delta_e`, `match_quality`, `needs_mix`, y la lista
   de candidatas rankeadas.

Tipos (dataclasses): `Ink(id, lab)`, `Candidate(ink_id, delta_e, rank)`,
`ColorMatch(candidates: list[Candidate], best_delta_e, match_quality, needs_mix)`.

### `skin.py` — sin cambios
`precompensate((r,g,b), skin_rgb, s)` igual. Se aplica a cada color antes del
matching; el color guardado en `extracted_colors` es el original. `s=0` si no hay
perfil. Calibración fina de perfiles = futuro, con el experto.

### `runner.py` — orquestación
Igual en estados/idempotencia/errores. Cambios:
- Tras extraer la paleta v2 y, por color, precompensar + obtener `ColorMatch`:
  - Insertar `extracted_colors` con `best_delta_e`, `match_quality`, `needs_mix`.
  - Insertar **N filas** en `match_results` (una por candidata) con su `rank`.
- Idempotencia idéntica (borra match_results + extracted_colors del job y reinserta).

### `supabase_client.py`
- `insert_extracted_color` acepta y escribe los 3 campos nuevos.
- Nueva `insert_match_candidates(job_id, extracted_color_id, candidates)` que inserta
  las N filas con `rank`. (O un `insert_match_result` con `rank`.)

## Esquema de BD (migraciones)

Archivo `migrations/2026-06-09_pipeline_v2.sql`:
```sql
alter table public.extracted_colors
  add column if not exists best_delta_e numeric,
  add column if not exists match_quality text,
  add column if not exists needs_mix boolean default false;

alter table public.match_results
  add column if not exists rank integer;
```
- `extracted_colors`: resumen del match por color.
- `match_results`: N filas por color (candidatas), `rank` 1..N, `match_type` sigue
  `direct_ink`, `ink_mix_id` sigue `null`.
- Idempotencia del runner sin cambios.
- La app (otro repo) se adaptará a leer candidatas (orden por `rank`) + flags. Aún
  no consume estos datos, así que estamos a tiempo.

## Configuración (`config.py`)

| Parámetro | Default | Controla |
|---|---|---|
| `resize_max_side` | 512 | fidelidad vs velocidad |
| `kmeans_k_high` | 48 | grupos finos antes de fusionar |
| `merge_delta_e` | 3.5 | **resolución perceptual** (mando principal) |
| `min_cluster_weight` | 0.005 | descarte de ruido |
| `max_colors` | 40 | tope de seguridad |
| `dominant_weight` | 0.15 | umbral rol dominante |
| `candidates_n` | 5 | candidatas por color |
| `quality_excellent` | 2.0 | umbral ΔE excelente |
| `quality_good` | 5.0 | umbral ΔE bueno |
| `quality_fair` | 10.0 | umbral ΔE aceptable (mayor → needs_mix) |
| `bg_border_fraction` | 0.5 | % borde uniforme = fondo |
| `bg_merge_delta_e` | 4.0 | ΔE para borrar el fondo |
| `near_white_threshold` | 250 | fallback blanco |
| `alpha_threshold` | 16 | transparencia |

## Tests (TDD)

- `test_color.py`: `rgb_to_lab` canónica intacta; `rgb_to_lab_array` == escalar.
- `test_palette.py`: N colores planos → ~N; degradado → varios pasos; `merge_delta_e`
  más bajo → más colores (monótono); fondo blanco/negro/color uniforme eliminado;
  fondo no uniforme no se sobre-elimina; pesos suman ~1; al menos 1 dominante.
- `test_matching.py`: top-N ordenadas asc.; `rank` correcto; color exacto de una
  tinta → rank 1 ΔE≈0; clasificación de calidad (cercano→excellent, lejano→poor +
  needs_mix=true); conjunto de tintas vacío → error.
- `test_skin.py`: sin cambios, sigue verde.

## Rendimiento

MiniBatchKMeans + ΔE vectorizado. 512px, k=48, 1105 tintas → unos segundos en
background. Aceptable (no es latencia crítica; la app sondea el estado).

## Verificación end-to-end

Reproceso de un job real `pending` contra Supabase: comprobar paleta de tamaño
variable, N candidatas por color con `rank`, flags de calidad coherentes, e
idempotencia (reproceso no duplica). Deploy a Railway por push.
