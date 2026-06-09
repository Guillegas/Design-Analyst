# Brief del Worker de Análisis de Color — Tattoo Inkprep

> **Para el Claude que abra este archivo en el repo vacío del worker:**
> Este documento es tu única fuente de verdad para arrancar. Describe el sistema
> completo, el contrato con la base de datos, el pipeline de análisis y la
> estructura de carpetas que debes crear. Léelo entero antes de escribir nada.
> No empieces a programar hasta hacer un plan de implementación (usa la skill
> `superpowers:writing-plans` si la tienes) y que el usuario lo apruebe.
>
> **Importante:** este worker es un proyecto Python **independiente**. NO es la
> app Flutter. La app vive en otro repo. Tú y la app os comunicáis a través de
> la base de datos de Supabase (ver "El contrato"). El usuario es **primerizo
> con workers de Python**: explica tus decisiones, ve paso a paso y no asumas
> conocimientos de infraestructura.

---

## 1. Qué es este worker y por qué existe

**Tattoo Inkprep** es una app para tatuadores que trabajan a color. El tatuador
sube un diseño digital limpio, elige la marca de tintas (o usa su inventario
personal "Mis tintas") y el tono de piel del cliente, y la app le devuelve qué
**botes de tinta** necesita para reproducir los colores del diseño.

El **matching de color** (qué tinta del catálogo se parece más a cada color del
diseño) necesita procesamiento de imagen y de color que vive mejor en Python
(Pillow, scikit-image, scikit-learn). Por eso es un servicio aparte: este worker.

**La regla de oro del producto (no la rompas):** el pipeline es **determinista y
trazable**, no IA generativa. Extracción de paleta → conversión a LAB → distancia
perceptual (Delta E) → bote más cercano. Resultados auditables, no una caja negra.

### Alcance de esta V1 del worker
- **Solo bote directo.** Se recomienda la tinta más cercana por color. **NO** se
  generan mezclas de tintas (la tabla `ink_mixes` está vacía a propósito; las
  mezclas esperan validación de un tatuador experto que aún no está en el proyecto).
- **Con ajuste por tono de piel** (modelo simple, ver §6).
- 6 marcas ya sembradas en el catálogo (1105 tintas con hex + LAB precalculados).

---

## 2. Arquitectura del sistema (vista de pájaro)

```
┌─────────────┐     1. sube imagen a Storage          ┌──────────────────┐
│  App Flutter │ ───────────────────────────────────> │ Supabase Storage │
│             │     2. crea analysis_jobs (pending)    │  bucket `designs`│
│             │ ─────────────┐                         └──────────────────┘
└─────────────┘              │                          ┌──────────────────┐
       │                     └────────────────────────> │ Supabase Postgres│
       │ 3. POST /analyze {job_id}                       │  analysis_jobs   │
       v                                                 │  extracted_colors│
┌─────────────┐   4. lee job + descarga imagen          │  match_results   │
│ ESTE WORKER  │ <──────────────────────────────────────│  inks (catálogo) │
│  (FastAPI)  │   5. escribe extracted_colors +         └──────────────────┘
│             │      match_results, marca job completed        ^
└─────────────┘ ──────────────────────────────────────────────┘
       │
       │ 6. la app lee los resultados de la BD y los pinta
       v   (eso es la "integración de la app", otro repo, otra fase)
```

La app y el worker **nunca se pasan la imagen de mano en mano**. La app sube la
imagen a Storage y crea un "job" en la tabla `analysis_jobs`. El worker recibe
solo el `job_id`, descarga la imagen él mismo desde Storage, hace el trabajo y
**escribe los resultados en la base de datos**. La app luego los lee.

---

## 3. El contrato (las tablas de Supabase que tocas)

Estas tablas **ya existen** en Supabase (no las crees). Aquí están las columnas
relevantes. Todas las claves son `uuid`.

### `analysis_jobs` — el trabajo a procesar (TÚ LO LEES Y LO ACTUALIZAS)
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid | el `job_id` que recibes |
| `project_id` | uuid → projects | |
| `design_upload_id` | uuid → design_uploads | de dónde sacas el `storage_path` |
| `status` | text | `pending` → `processing` → `completed` / `failed` |
| `analysis_source` | text | `brands` o `my_inks` — decide qué tintas son elegibles |
| `selected_brand_ids` | uuid[] | marcas elegidas (cuando `analysis_source='brands'`); `null` si no |
| `selected_ink_ids` | uuid[] | botes propios elegidos (cuando `analysis_source='my_inks'`); `null` si no |
| `error_message` | text | rellénalo si `status='failed'` |
| `completed_at` | timestamptz | ponlo al terminar |

> Para el tono de piel necesitas `projects.skin_tone_profile_id`: haz join
> `analysis_jobs.project_id → projects.skin_tone_profile_id → skin_tone_profiles.name`.

### `design_uploads` — metadatos del archivo (TÚ LO LEES)
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid | = `analysis_jobs.design_upload_id` |
| `storage_path` | text | ruta dentro del bucket `designs` (descarga esto) |
| `format` | text | `png` / `jpg` / `webp` |

### `inks` — el catálogo curado (TÚ LO LEES, solo lectura)
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid | |
| `brand_id` | uuid → brands | filtra por aquí en modo `brands` |
| `name` | text | nombre del bote |
| `hex_reference` | text | `#RRGGBB` |
| `rgb_reference` | jsonb | `{"r":.., "g":.., "b":..}` |
| `lab_reference` | jsonb | `{"l":.., "a":.., "b":..}` — **úsalo tal cual para el matching** |

> El catálogo **ya trae el LAB precalculado** con la conversión canónica (ver §5).
> NO recalcules el LAB de las tintas; lee `lab_reference` directamente.

### `skin_tone_profiles` — perfiles de tono de piel (TÚ LO LEES, solo lectura)
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid | |
| `name` | text | `very_light` / `light` / `medium` / `tan` / `dark` |
| `display_name` | text | |
| `matching_rules` | jsonb | hoy vacío; hogar futuro de los parámetros de piel (ver §6) |

### `extracted_colors` — la paleta detectada (TÚ LA ESCRIBES)
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid | autogenerado |
| `analysis_job_id` | uuid → analysis_jobs | el job que procesas |
| `hex` | text | `#RRGGBB` del color extraído (sin ajuste de piel) |
| `rgb` | jsonb | `{"r":..,"g":..,"b":..}` |
| `lab` | jsonb | `{"l":..,"a":..,"b":..}` |
| `weight` | numeric | fracción [0..1] de cuánto pesa el color en el diseño |
| `role` | text | `dominant` / `secondary` |

### `match_results` — la tinta recomendada por color (TÚ LO ESCRIBES)
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid | autogenerado |
| `analysis_job_id` | uuid → analysis_jobs | |
| `extracted_color_id` | uuid → extracted_colors | a qué color responde |
| `match_type` | text | **siempre `direct_ink`** en V1 |
| `ink_id` | uuid → inks | la tinta recomendada |
| `ink_mix_id` | uuid | **siempre `null`** en V1 |
| `delta_e` | numeric | la distancia perceptual del match (CIEDE2000) |

> **Verifica los nombres/tipos exactos contra la BD real** antes de insertar
> (puede haber columnas `NOT NULL` o defaults que aquí no se listan). Usa la
> service_role key para inspeccionar el esquema si hace falta.

---

## 4. El ciclo de vida del job (qué hace el worker, paso a paso)

```
POST /analyze { "job_id": "<uuid>" }   (header X-Worker-Secret: <secreto>)
  │
  ├─ valida el secreto → 401 si no cuadra
  ├─ responde 202 Accepted enseguida y procesa en segundo plano
  │   (FastAPI BackgroundTasks; el análisis no debe bloquear la respuesta HTTP)
  │
  └─ en segundo plano (runner):
       1. lee el job. Si status != 'pending' (ya 'processing'/'completed'),
          no lo reproceses salvo reintento explícito → evita doble ejecución.
       2. status = 'processing'
       3. join para obtener: design_uploads.storage_path,
          projects.skin_tone_profile_id → skin_tone_profiles.name
       4. descarga la imagen del bucket `designs`
       5. PIPELINE (ver §5 y §6):
            a. extrae paleta  → lista de colores RGB con peso y rol
            b. rgb → lab (conversión canónica)
            c. ajuste por tono de piel (pre-compensación)
            d. matching ΔE contra tintas elegibles
       6. IDEMPOTENCIA: borra extracted_colors + match_results previos de este job
       7. inserta extracted_colors; por cada uno inserta su match_results
       8. status = 'completed', completed_at = now()
       │
       └─ en cualquier error: status = 'failed', error_message = str(e)
          (loguea el traceback; nunca dejes el job colgado en 'processing')
```

### Qué tintas son "elegibles" para el matching
- `analysis_source == 'brands'` → tintas con `brand_id IN selected_brand_ids`.
- `analysis_source == 'my_inks'` → tintas con `id IN selected_ink_ids`.
- Si el conjunto elegible sale vacío → `failed` con mensaje claro.

---

## 5. Pipeline de color — extracción y conversión

### 5.1 Extracción de paleta (`pipeline/palette.py`)
1. Abre la imagen con Pillow. Si tiene alpha, **descarta píxeles transparentes**
   (alpha < 16). Convierte a RGB.
2. **Descarta el fondo casi-blanco** (R,G,B todos > 240): los diseños limpios
   suelen venir sobre blanco/transparente y no queremos recomendar "blanco".
3. Reescala a máx. ~200 px en el lado largo (velocidad; la paleta no cambia).
4. **KMeans** (scikit-learn) con `k = 6` sobre los píxeles restantes
   (si quedan menos de k píxeles únicos, baja k).
5. Post-proceso:
   - calcula el `weight` de cada cluster = fracción de píxeles que le tocaron.
   - **descarta** clusters con `weight < 0.03` (ruido).
   - **fusiona** clusters cuyo ΔE entre sí sea < 5 (colores casi idénticos):
     quédate con uno y suma sus pesos.
6. Ordena por peso descendente. El de mayor peso (y los que superen, p.ej., 0.20)
   → `role = 'dominant'`; el resto → `role = 'secondary'`. (Al menos 1 dominante.)
7. Devuelve la lista de colores `{rgb, weight, role}`.

> Parámetros (`k`, umbrales 240/16/0.03/ΔE<5) van en `config.py` para afinarlos
> sin tocar la lógica. Empieza con estos valores.

### 5.2 Conversión RGB → LAB (`pipeline/color.py`) — CRÍTICO
El catálogo (`inks.lab_reference`) se generó con esta conversión exacta
(sRGB → linear → XYZ D65 → CIELAB). **El worker DEBE usar la misma** o el Delta E
contra las tintas será incorrecto. Copia esta función literal:

```python
def _srgb_channel_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def _f(t: float) -> float:
    delta = 6 / 29
    return t ** (1 / 3) if t > delta ** 3 else t / (3 * delta ** 2) + 4 / 29

def rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    # sRGB -> XYZ (D65)
    rl, gl, bl = (_srgb_channel_to_linear(v) for v in (r, g, b))
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    # Normaliza por el blanco D65
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    fx, fy, fz = (_f(t) for t in (x / xn, y / yn, z / zn))
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    return round(L, 2), round(a, 2), round(bb, 2)
```

> `skimage.color.rgb2lab` usa la misma convención (D65, 2°) y daría valores casi
> idénticos, pero para evitar cualquier desviación de redondeo, **usa la función
> de arriba** para los colores extraídos. Para el ΔE sí puedes usar
> `skimage.color.deltaE_ciede2000`.

### 5.3 Distancia perceptual (matching, `pipeline/matching.py`)
- Métrica: **CIEDE2000** (`skimage.color.deltaE_ciede2000`), no euclídea simple.
- Para cada color extraído (ya ajustado por piel, §6), calcula ΔE contra el
  `lab_reference` de cada tinta elegible. Elige el de **menor ΔE**.
- Escribe `match_results` con `match_type='direct_ink'`, `ink_id`, `delta_e`,
  `ink_mix_id=null`.

---

## 6. Ajuste por tono de piel (`pipeline/skin.py`)

**Idea:** una tinta no se ve igual sobre piel clara que sobre piel oscura, porque
la piel transparenta por debajo y arrastra el color final. Para conseguir el color
del diseño sobre la piel del cliente, hay que **pre-compensar** el color objetivo
antes de buscar la tinta.

**Modelo (compositing inverso, en sRGB 0–255):** asumimos que lo que se percibe
es una mezcla de la tinta con el color de la piel:

```
percibido = (1 − s) · tinta + s · piel
```

Como queremos que `percibido == objetivo` (el color del diseño), despejamos la
tinta que hay que recomendar:

```
tinta_necesaria = (objetivo − s · piel) / (1 − s)      # por canal R,G,B
                  → clamp a [0, 255]
```

- `s` ∈ [0,1] = cuánto influye la piel (crece con lo oscura que es).
- `piel` = color RGB representativo del perfil.
- En piel oscura, esto empuja la tinta recomendada a ser **más clara/saturada**
  (coherente con la práctica real de "punch through").
- Se **desactiva** poniendo `s = 0` (la tinta necesaria = objetivo).

El flujo es: color extraído RGB → `tinta_necesaria` RGB (pre-compensada) →
`rgb_to_lab` → matching. (El `extracted_colors.lab/hex/rgb` que guardas es el
color **original** del diseño, sin compensar; la compensación solo afecta a qué
tinta se elige.)

### Parámetros provisionales por perfil (en `config.py`)
> **Estos valores son heurísticos, NO validados por un profesional.** Son un punto
> de partida razonable y monótono. Cuando entre el tatuador experto, se reemplazan
> (su hogar definitivo es `skin_tone_profiles.matching_rules` en la BD; por ahora
> viven en el worker para que sea autocontenido y testeable).

| `name`       | piel representativa (hex) | `s`   |
|--------------|---------------------------|-------|
| `very_light` | `#F5D9C4`                 | 0.05  |
| `light`      | `#E8B89B`                 | 0.10  |
| `medium`     | `#C68642`                 | 0.18  |
| `tan`        | `#8D5524`                 | 0.26  |
| `dark`       | `#5A3825`                 | 0.35  |

Si el job no tiene perfil de piel (`skin_tone_profile_id` nulo) → trata como
`s = 0` (sin ajuste).

---

## 7. La API HTTP (`app/main.py`)

FastAPI con dos endpoints:

- `GET /health` → `{"status": "ok"}`. Para que Railway compruebe que está vivo.
- `POST /analyze`
  - Body: `{ "job_id": "<uuid>" }`
  - Header obligatorio: `X-Worker-Secret: <WORKER_SECRET>`. Si no cuadra → 401.
  - Lanza el procesado con `BackgroundTasks` y responde **202 Accepted**
    inmediatamente (`{"accepted": true, "job_id": ...}`). El análisis corre
    detrás; la app sigue el progreso leyendo `analysis_jobs.status`.

> Sin webhooks ni colas en V1. Si el procesado tarda y Railway corta peticiones
> largas, el `BackgroundTasks` ya desacopla la respuesta del trabajo. Si más
> adelante hiciera falta, se migra a una cola (RQ/Celery), pero **no ahora**
> (YAGNI).

### Auth y secretos
- **App → worker:** secreto compartido `WORKER_SECRET` en el header. Simple y
  suficiente para V1.
- **Worker → Supabase:** usa la **service_role key** (NO la anon key) para
  descargar de Storage y escribir en las tablas (salta RLS, es backend de
  confianza). Trátala como secreto: solo en variables de entorno, nunca en git.

---

## 8. Estructura del repo a crear

```
.
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI: /health, /analyze
│   ├── config.py           # carga env + params (k, umbrales, piel)
│   ├── supabase_client.py  # descargar imagen, leer job, escribir resultados
│   └── pipeline/
│       ├── __init__.py
│       ├── palette.py      # extracción de paleta (KMeans + post-proceso)
│       ├── color.py        # rgb_to_lab (función canónica) + helpers
│       ├── skin.py         # pre-compensación por tono de piel
│       ├── matching.py     # ΔE CIEDE2000 contra tintas elegibles
│       └── runner.py       # orquesta el job: estados, idempotencia, errores
├── tests/
│   ├── test_color.py       # rgb_to_lab contra valores conocidos del catálogo
│   ├── test_skin.py        # s=0 no cambia nada; piel oscura aclara
│   ├── test_matching.py    # un color exacto de una tinta → ΔE≈0 a esa tinta
│   └── test_palette.py     # imagen sintética de 2 colores → 2 clusters
├── scripts/
│   └── run_job.py          # CLI: procesar un job_id real contra Supabase
├── Dockerfile
├── pyproject.toml          # o requirements.txt
├── .env.example
├── .gitignore              # incluye .env
└── README.md
```

### Dependencias
`fastapi`, `uvicorn[standard]`, `pillow`, `numpy`, `scikit-learn`,
`scikit-image`, `supabase` (cliente Python oficial) o `httpx` contra la REST API
de Supabase, `python-dotenv`, `pydantic`. Para tests: `pytest`.

> Las libs de imagen (scikit-image/scikit-learn/scipy) hacen la imagen Docker
> grande. Es aceptable; el análisis corre en segundo plano y no es latencia
> crítica. Usa una base `python:3.12-slim` y instala solo lo necesario.

---

## 9. Variables de entorno (`.env.example`)

```
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role key — secreto>
SUPABASE_STORAGE_BUCKET=designs
WORKER_SECRET=<secreto compartido con la app>
```

El usuario tiene el proyecto Supabase `uhffedvrxsdwizycmgsf`. La service_role key
se saca del dashboard de Supabase (Settings → API). **Nunca** la subas a git.

---

## 10. Deploy en Railway

1. `Dockerfile` que arranca `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   (Railway inyecta `$PORT`).
2. Conectar el repo de GitHub a Railway → despliega solo al hacer push.
3. Configurar las variables de entorno (§9) en Railway (no en git).
4. Railway da una URL pública → esa es la que la app pondrá en `ANALYSIS_API_URL`
   (eso lo hará la integración de la app, otra fase).
5. `GET /health` como healthcheck.

> El usuario es primerizo: cuando llegue el momento del deploy, guíalo clic a
> clic por Railway. No hace falta resolver el deploy para empezar a construir y
> probar el worker en local.

---

## 11. Pruebas

- **Unitarias** (pytest, sin red): color, skin, matching, palette con entradas
  sintéticas y valores conocidos. Ej.: el RGB exacto de una tinta del catálogo
  debe dar ΔE ≈ 0 contra esa tinta; `s=0` deja el color intacto; una imagen de
  dos colores planos debe dar dos clusters.
- **End-to-end manual** (`scripts/run_job.py`): pasas un `job_id` real (creado
  por la app al subir un diseño), el script corre el runner contra el Supabase
  real y compruebas que `analysis_jobs` queda `completed` y que aparecen filas
  en `extracted_colors` y `match_results`. Esto reemplaza tener que llamar al
  endpoint HTTP mientras desarrollas.

---

## 12. Orden de implementación sugerido

1. **Scaffold**: estructura de carpetas, `pyproject.toml`/deps, `.env.example`,
   `.gitignore`, `config.py` cargando env.
2. **`pipeline/color.py`** + `test_color.py` (la base de todo; verifica contra
   un par de tintas del catálogo).
3. **`pipeline/skin.py`** + `test_skin.py`.
4. **`pipeline/palette.py`** + `test_palette.py`.
5. **`pipeline/matching.py`** + `test_matching.py` (lee tintas elegibles).
6. **`supabase_client.py`**: leer job, descargar imagen, escribir resultados.
7. **`pipeline/runner.py`**: orquesta todo con estados + idempotencia + errores.
8. **`scripts/run_job.py`**: prueba end-to-end contra Supabase real.
9. **`app/main.py`**: FastAPI con `/health` y `/analyze`.
10. **`Dockerfile`** + README + (cuando toque) deploy en Railway.

Construye y prueba cada pieza antes de la siguiente. Aplica TDD donde tenga
sentido (color/skin/matching son ideales: entrada conocida → salida conocida).

---

## 13. Cosas que NO debes hacer en esta V1

- **No** generes mezclas de tintas (`ink_mixes` se queda vacía; `match_type`
  siempre `direct_ink`).
- **No** uses IA generativa para el matching. Pipeline determinista.
- **No** crees ni modifiques tablas de Supabase (ya existen; solo lees/escribes).
- **No** metas la service_role key ni el WORKER_SECRET en git.
- **No** montes colas, reintentos automáticos ni webhooks todavía (YAGNI).
- **No** recalcules el LAB de las tintas: usa `inks.lab_reference`.

---

## 14. Glosario rápido

- **LAB / CIELAB:** espacio de color perceptual (L=luminosidad, a=verde↔rojo,
  b=azul↔amarillo). Comparar aquí se aproxima a cómo el ojo percibe diferencias.
- **Delta E (ΔE):** distancia entre dos colores en LAB. CIEDE2000 es la fórmula
  moderna y más fiel. ΔE≈0 = idénticos; ΔE>10 = claramente distintos.
- **service_role key:** clave de Supabase que salta las reglas de seguridad por
  fila (RLS). Solo para backend de confianza como este worker.
- **job:** una fila en `analysis_jobs` = una petición de análisis de un diseño.
```
