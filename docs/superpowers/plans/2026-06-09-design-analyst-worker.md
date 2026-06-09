# Worker de Análisis de Color (Tattoo Inkprep) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un worker Python (FastAPI) que, dado un `job_id`, descarga un diseño de Supabase Storage, extrae su paleta de color, la ajusta por tono de piel, hace matching perceptual (ΔE CIEDE2000) contra un catálogo de tintas y escribe los resultados en Supabase — todo determinista y trazable.

**Architecture:** Pipeline determinista en módulos puros (`color`, `skin`, `palette`, `matching`) sin dependencia de red, orquestados por un `runner` con manejo de estados/idempotencia/errores. La capa de I/O (Supabase: leer job, descargar imagen, escribir resultados) está aislada en `supabase_client`. Una API FastAPI fina expone `/health` y `/analyze` (auth por secreto compartido + `BackgroundTasks`). El núcleo de color se construye con TDD contra valores conocidos del catálogo.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, Pillow, numpy, scikit-learn (KMeans), scikit-image (ΔE CIEDE2000), supabase-py, pydantic, python-dotenv, pytest. Deploy: Docker en Railway.

---

## Pre-requisitos (lo que necesito del usuario / setup manual)

Estos pasos NO son código; son la conexión. Confírmalos/provéelos antes o durante el scaffold:

1. **Repo Git limpio.** Esta carpeta `design_analyst/` está hoy dentro del repo de `/Users/guillegas` (remote `Udia-Scuffers`). Hay que inicializar un repo propio aquí y conectarlo a `https://github.com/Guillegas/Design-Analyst.git`. (Ver Task 0.)
2. **Supabase service_role key.** Del dashboard → Settings → API → `service_role` (secret). El proyecto es `uhffedvrxsdwizycmgsf`, así que `SUPABASE_URL=https://uhffedvrxsdwizycmgsf.supabase.co`.
3. **`WORKER_SECRET`.** Lo generamos nosotros (p.ej. `openssl rand -hex 32`); la app deberá usar el mismo valor en su header `X-Worker-Secret`.
4. **Python 3.12 local.** Hoy solo hay 3.14, que puede no tener wheels de scikit-* estables. Instalar 3.12 (p.ej. `brew install python@3.12`) y crear el venv con él, para que coincida con `python:3.12-slim` del Docker.
5. **Un `job_id` real `pending`** (creado por la app al subir un diseño) para la prueba end-to-end de Task 11. No bloquea el desarrollo del núcleo.

---

## File Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI: /health, /analyze (auth + BackgroundTasks)
│   ├── config.py           # carga env + params del pipeline (Settings pydantic)
│   ├── supabase_client.py  # I/O: leer job+joins, descargar imagen, escribir resultados
│   └── pipeline/
│       ├── __init__.py
│       ├── color.py        # rgb_to_lab canónica + helpers hex/rgb
│       ├── skin.py         # pre-compensación por tono de piel
│       ├── palette.py      # extracción de paleta (KMeans + post-proceso)
│       ├── matching.py     # ΔE CIEDE2000 contra tintas elegibles
│       └── runner.py       # orquesta: estados, idempotencia, errores
├── tests/
│   ├── __init__.py
│   ├── test_color.py
│   ├── test_skin.py
│   ├── test_palette.py
│   └── test_matching.py
├── scripts/
│   └── run_job.py          # CLI: procesar un job_id real contra Supabase
├── Dockerfile
├── pyproject.toml
├── .env.example
├── .gitignore
├── .dockerignore
└── README.md
```

Cada módulo del pipeline es **puro** (sin red, entrada→salida determinista) y por eso testeable con `pytest` sin mocks de Supabase. `supabase_client.py` y `runner.py` concentran el I/O y la orquestación.

---

## Task 0: Repo limpio conectado a GitHub

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Inicializar repo propio en esta carpeta**

> Esta carpeta está dentro del repo de `/Users/guillegas`. Inicializamos uno propio aquí; el repo padre simplemente verá `design_analyst/` como subdirectorio (no lo añadimos a él).

Run:
```bash
cd /Users/guillegas/Developer/design_analyst
git init -b main
```
Expected: `Initialized empty Git repository`

- [ ] **Step 2: Crear `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/
.pytest_cache/
.mypy_cache/

# Env / secretos
.env
.env.*
!.env.example

# OS
.DS_Store
```

- [ ] **Step 3: Conectar el remoto**

Run:
```bash
git remote add origin https://github.com/Guillegas/Design-Analyst.git
git remote -v
```
Expected: `origin  https://github.com/Guillegas/Design-Analyst.git (fetch/push)`

- [ ] **Step 4: Primer commit (brief + plan)**

```bash
git add design_analyst.md docs/ .gitignore
git commit -m "chore: project brief + implementation plan"
```

---

## Task 1: Scaffold de dependencias y config

**Files:**
- Create: `pyproject.toml`, `.env.example`, `.dockerignore`
- Create: `app/__init__.py`, `app/pipeline/__init__.py`, `tests/__init__.py`
- Create: `app/config.py`

- [ ] **Step 1: Crear `pyproject.toml`**

```toml
[project]
name = "design-analyst"
version = "0.1.0"
description = "Worker de análisis de color para Tattoo Inkprep"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "pillow>=10.3",
    "numpy>=1.26",
    "scikit-learn>=1.5",
    "scikit-image>=0.24",
    "supabase>=2.5",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.2"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Crear venv 3.12 e instalar**

Run:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
Expected: instala sin errores; `python -c "import sklearn, skimage, fastapi"` no falla.

- [ ] **Step 3: Crear `.env.example`**

```
SUPABASE_URL=https://uhffedvrxsdwizycmgsf.supabase.co
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=designs
WORKER_SECRET=
```

- [ ] **Step 4: Crear `.dockerignore`**

```
.venv/
__pycache__/
.pytest_cache/
.git/
.env
tests/
docs/
*.md
```

- [ ] **Step 5: Crear los `__init__.py` (vacíos)**

`app/__init__.py`, `app/pipeline/__init__.py`, `tests/__init__.py` — ficheros vacíos.

- [ ] **Step 6: Crear `app/config.py`**

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


# Perfiles de piel: heurísticos, NO validados por profesional (ver brief §6).
# hex representativo + s (cuánto influye la piel, 0..1).
SKIN_PROFILES: dict[str, dict] = {
    "very_light": {"hex": "#F5D9C4", "s": 0.05},
    "light":      {"hex": "#E8B89B", "s": 0.10},
    "medium":     {"hex": "#C68642", "s": 0.18},
    "tan":        {"hex": "#8D5524", "s": 0.26},
    "dark":       {"hex": "#5A3825", "s": 0.35},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "designs"
    worker_secret: str

    # Parámetros del pipeline de paleta (afinables sin tocar lógica).
    kmeans_k: int = 6
    near_white_threshold: int = 240   # R,G,B todos > esto => fondo, descartar
    alpha_threshold: int = 16         # alpha < esto => transparente, descartar
    min_cluster_weight: float = 0.03  # descarta clusters con menos peso
    merge_delta_e: float = 5.0        # fusiona clusters con ΔE entre sí < esto
    dominant_weight: float = 0.20     # weight >= esto => role 'dominant'
    resize_max_side: int = 200        # lado largo máx para acelerar KMeans


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example .dockerignore app/ tests/__init__.py
git commit -m "chore: scaffold deps, config y estructura de paquetes"
```

---

## Task 2: `color.py` — conversión RGB↔LAB canónica (TDD)

**Files:**
- Create: `app/pipeline/color.py`
- Test: `tests/test_color.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_color.py
from app.pipeline.color import rgb_to_lab, hex_to_rgb, rgb_to_hex


def test_white_maps_to_lab_100():
    L, a, b = rgb_to_lab(255, 255, 255)
    assert L == 100.0
    assert abs(a) < 0.01 and abs(b) < 0.01


def test_black_maps_to_lab_0():
    L, a, b = rgb_to_lab(0, 0, 0)
    assert L == 0.0 and a == 0.0 and b == 0.0


def test_known_red_value():
    # sRGB rojo puro -> CIELAB D65 conocido
    L, a, b = rgb_to_lab(255, 0, 0)
    assert abs(L - 53.24) < 0.1
    assert abs(a - 80.09) < 0.1
    assert abs(b - 67.20) < 0.1


def test_hex_roundtrip():
    assert hex_to_rgb("#FF8000") == (255, 128, 0)
    assert rgb_to_hex(255, 128, 0) == "#FF8000"
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `pytest tests/test_color.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.pipeline.color'`

- [ ] **Step 3: Implementar `color.py`**

```python
# app/pipeline/color.py
"""Conversión de color canónica. Debe coincidir EXACTAMENTE con la usada para
generar inks.lab_reference (brief §5.2): sRGB -> linear -> XYZ D65 -> CIELAB."""


def _srgb_channel_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    delta = 6 / 29
    return t ** (1 / 3) if t > delta ** 3 else t / (3 * delta ** 2) + 4 / 29


def rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    rl, gl, bl = (_srgb_channel_to_linear(v) for v in (r, g, b))
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    fx, fy, fz = (_f(t) for t in (x / xn, y / yn, z / zn))
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    return round(L, 2), round(a, 2), round(bb, 2)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b))
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `pytest tests/test_color.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/color.py tests/test_color.py
git commit -m "feat: rgb_to_lab canónica + helpers hex (color.py)"
```

---

## Task 3: `skin.py` — pre-compensación por tono de piel (TDD)

**Files:**
- Create: `app/pipeline/skin.py`
- Test: `tests/test_skin.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_skin.py
from app.pipeline.skin import precompensate


def test_s_zero_leaves_color_unchanged():
    # s=0 => tinta_necesaria == objetivo
    assert precompensate((120, 80, 60), skin_rgb=(150, 100, 80), s=0.0) == (120, 80, 60)


def test_dark_skin_pushes_toward_lighter_or_clamped():
    # objetivo medio, piel oscura, s alto => tinta_necesaria = (obj - s*piel)/(1-s)
    # con obj=(100,100,100), piel=(40,40,40), s=0.5 => (160,160,160)
    assert precompensate((100, 100, 100), skin_rgb=(40, 40, 40), s=0.5) == (160, 160, 160)


def test_result_is_clamped_to_0_255():
    # caso que se saldría de rango por arriba => clamp a 255
    r, g, b = precompensate((250, 250, 250), skin_rgb=(0, 0, 0), s=0.5)
    assert (r, g, b) == (255, 255, 255)
    # y por abajo => clamp a 0
    r2, g2, b2 = precompensate((10, 10, 10), skin_rgb=(255, 255, 255), s=0.5)
    assert (r2, g2, b2) == (0, 0, 0)
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `pytest tests/test_skin.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementar `skin.py`**

```python
# app/pipeline/skin.py
"""Pre-compensación por tono de piel (brief §6).
percibido = (1-s)*tinta + s*piel  =>  tinta = (objetivo - s*piel) / (1-s)."""


def _clamp(v: float) -> int:
    return int(round(max(0.0, min(255.0, v))))


def precompensate(
    target_rgb: tuple[int, int, int],
    skin_rgb: tuple[int, int, int],
    s: float,
) -> tuple[int, int, int]:
    if s <= 0.0:
        return target_rgb
    out = tuple(
        _clamp((t - s * p) / (1.0 - s))
        for t, p in zip(target_rgb, skin_rgb)
    )
    return out  # type: ignore[return-value]
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `pytest tests/test_skin.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/skin.py tests/test_skin.py
git commit -m "feat: pre-compensación por tono de piel (skin.py)"
```

---

## Task 4: `matching.py` — ΔE CIEDE2000 contra tintas elegibles (TDD)

**Files:**
- Create: `app/pipeline/matching.py`
- Test: `tests/test_matching.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_matching.py
from app.pipeline.matching import best_match, Ink


def test_exact_color_matches_its_ink_with_delta_e_near_zero():
    inks = [
        Ink(id="ink-red", lab=(53.24, 80.09, 67.20)),
        Ink(id="ink-blue", lab=(32.30, 79.19, -107.86)),
    ]
    match = best_match((53.24, 80.09, 67.20), inks)
    assert match.ink_id == "ink-red"
    assert match.delta_e < 0.5


def test_picks_nearest_of_several():
    inks = [
        Ink(id="ink-dark-gray", lab=(20.0, 0.0, 0.0)),
        Ink(id="ink-light-gray", lab=(80.0, 0.0, 0.0)),
    ]
    match = best_match((75.0, 0.0, 0.0), inks)
    assert match.ink_id == "ink-light-gray"


def test_empty_inks_raises():
    import pytest
    with pytest.raises(ValueError):
        best_match((50.0, 0.0, 0.0), [])
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `pytest tests/test_matching.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementar `matching.py`**

```python
# app/pipeline/matching.py
"""Matching perceptual: para un LAB extraído (ya ajustado por piel), encuentra
la tinta elegible con menor ΔE CIEDE2000 (brief §5.3)."""
from dataclasses import dataclass

import numpy as np
from skimage.color import deltaE_ciede2000


@dataclass(frozen=True)
class Ink:
    id: str
    lab: tuple[float, float, float]


@dataclass(frozen=True)
class Match:
    ink_id: str
    delta_e: float


def _delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    a = np.array(lab1, dtype=float).reshape(1, 1, 3)
    b = np.array(lab2, dtype=float).reshape(1, 1, 3)
    return float(deltaE_ciede2000(a, b)[0, 0])


def best_match(lab: tuple[float, float, float], inks: list[Ink]) -> Match:
    if not inks:
        raise ValueError("No hay tintas elegibles para el matching")
    best: Match | None = None
    for ink in inks:
        de = _delta_e(lab, ink.lab)
        if best is None or de < best.delta_e:
            best = Match(ink_id=ink.id, delta_e=round(de, 4))
    assert best is not None
    return best
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `pytest tests/test_matching.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/matching.py tests/test_matching.py
git commit -m "feat: matching ΔE CIEDE2000 contra tintas elegibles (matching.py)"
```

---

## Task 5: `palette.py` — extracción de paleta con KMeans (TDD)

**Files:**
- Create: `app/pipeline/palette.py`
- Test: `tests/test_palette.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_palette.py
from PIL import Image

from app.pipeline.palette import extract_palette
from app.config import get_settings


def _two_color_image(c1, c2):
    img = Image.new("RGB", (100, 50), c1)
    for x in range(50, 100):
        for y in range(50):
            img.putpixel((x, y), c2)
    return img


def test_two_flat_colors_give_two_clusters(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("WORKER_SECRET", "x")
    get_settings.cache_clear()

    img = _two_color_image((200, 30, 30), (30, 30, 200))
    colors = extract_palette(img, get_settings())

    assert len(colors) == 2
    # pesos suman ~1 y hay al menos un dominante
    assert abs(sum(c["weight"] for c in colors) - 1.0) < 0.05
    assert any(c["role"] == "dominant" for c in colors)
    # cada color extraído está cerca de uno de los dos de entrada
    hexes = {c["rgb"] for c in colors}
    assert len(hexes) == 2


def test_near_white_background_is_discarded(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("WORKER_SECRET", "x")
    get_settings.cache_clear()

    # mayoría blanco con una mancha de color
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    for x in range(0, 20):
        for y in range(0, 20):
            img.putpixel((x, y), (10, 120, 200))
    colors = extract_palette(img, get_settings())

    assert len(colors) == 1
    r = colors[0]["rgb"]
    assert not (r["r"] > 240 and r["g"] > 240 and r["b"] > 240)
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `pytest tests/test_palette.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementar `palette.py`**

```python
# app/pipeline/palette.py
"""Extracción de paleta (brief §5.1): descarta transparente/blanco, reescala,
KMeans, post-proceso (pesos, descarte de ruido, fusión por ΔE), roles."""
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

from app.config import Settings
from app.pipeline.color import rgb_to_lab, rgb_to_hex
from app.pipeline.matching import _delta_e


def _relevant_pixels(img: Image.Image, s: Settings) -> np.ndarray:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = np.asarray(img.convert("RGBA"))
        rgb = rgba[..., :3].reshape(-1, 3)
        alpha = rgba[..., 3].reshape(-1)
        rgb = rgb[alpha >= s.alpha_threshold]
    else:
        rgb = np.asarray(img.convert("RGB")).reshape(-1, 3)
    # descarta fondo casi-blanco (todos los canales > umbral)
    not_white = ~np.all(rgb > s.near_white_threshold, axis=1)
    return rgb[not_white]


def extract_palette(img: Image.Image, s: Settings) -> list[dict]:
    # reescala por velocidad
    img = img.copy()
    img.thumbnail((s.resize_max_side, s.resize_max_side))
    pixels = _relevant_pixels(img, s)
    if len(pixels) == 0:
        return []

    k = min(s.kmeans_k, len(np.unique(pixels, axis=0)))
    km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(pixels)
    centers = km.cluster_centers_
    labels = km.labels_

    clusters = []
    total = len(labels)
    for i in range(k):
        weight = float(np.sum(labels == i)) / total
        r, g, b = (int(round(v)) for v in centers[i])
        clusters.append({"rgb": (r, g, b), "weight": weight})

    # descarta ruido
    clusters = [c for c in clusters if c["weight"] >= s.min_cluster_weight]

    # fusiona clusters con ΔE < umbral (quédate con el de mayor peso, suma pesos)
    clusters.sort(key=lambda c: c["weight"], reverse=True)
    merged: list[dict] = []
    for c in clusters:
        lab_c = rgb_to_lab(*c["rgb"])
        hit = None
        for m in merged:
            if _delta_e(lab_c, rgb_to_lab(*m["rgb"])) < s.merge_delta_e:
                hit = m
                break
        if hit:
            hit["weight"] += c["weight"]
        else:
            merged.append(dict(c))

    # renormaliza pesos a suma 1 tras descartes/fusiones
    wsum = sum(c["weight"] for c in merged) or 1.0
    for c in merged:
        c["weight"] = c["weight"] / wsum

    merged.sort(key=lambda c: c["weight"], reverse=True)

    out = []
    for idx, c in enumerate(merged):
        r, g, b = c["rgb"]
        is_dominant = idx == 0 or c["weight"] >= s.dominant_weight
        out.append({
            "rgb": {"r": r, "g": g, "b": b},
            "hex": rgb_to_hex(r, g, b),
            "lab": dict(zip("lab", rgb_to_lab(r, g, b))),
            "weight": round(c["weight"], 4),
            "role": "dominant" if is_dominant else "secondary",
        })
    return out
```

> Nota sobre el formato `lab`: `dict(zip("lab", (...)))` produce `{"l":..,"a":..,"b":..}`, que es el formato del contrato. Verifícalo en el test si lo amplías.

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `pytest tests/test_palette.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/palette.py tests/test_palette.py
git commit -m "feat: extracción de paleta KMeans + post-proceso (palette.py)"
```

---

## Task 6: Verificar el esquema real de Supabase

> El brief (§3) avisa: verifica nombres/tipos exactos y columnas `NOT NULL`/defaults
> contra la BD real antes de insertar. Este task es de **inspección**, no de código de app.

**Files:** ninguno (script ad-hoc / consola).

- [ ] **Step 1: Confirmar credenciales en `.env`**

Rellena `.env` con `SUPABASE_SERVICE_ROLE_KEY` y `WORKER_SECRET` reales (no commitear).
`WORKER_SECRET`: `openssl rand -hex 32`.

- [ ] **Step 2: Inspeccionar columnas de las tablas que escribimos**

Run (con el venv activo):
```bash
python -c "
from supabase import create_client
from app.config import get_settings
s = get_settings()
c = create_client(s.supabase_url, s.supabase_service_role_key)
for t in ['analysis_jobs','design_uploads','inks','skin_tone_profiles','extracted_colors','match_results']:
    rows = c.table(t).select('*').limit(1).execute().data
    print(t, '->', list(rows[0].keys()) if rows else '(vacía)')
"
```
Expected: imprime las columnas reales. **Anota cualquier columna `NOT NULL` no listada en el brief** (p.ej. `created_at`, índices) para no romper los inserts en Task 7/8.

- [ ] **Step 3: Confirmar que hay tintas con `lab_reference`**

```bash
python -c "
from supabase import create_client
from app.config import get_settings
s = get_settings()
c = create_client(s.supabase_url, s.supabase_service_role_key)
r = c.table('inks').select('id,name,hex_reference,lab_reference').limit(3).execute().data
print(r)
"
```
Expected: filas con `lab_reference = {'l':..,'a':..,'b':..}`. Si la clave fuese `L`/`A`/`B` u otro formato, ajusta el parseo en Task 7.

---

## Task 7: `supabase_client.py` — capa de I/O

**Files:**
- Create: `app/supabase_client.py`

> Sin test unitario automático (requiere red/credenciales); se valida en la prueba
> end-to-end (Task 11). Mantén las funciones finas y sin lógica de pipeline.

- [ ] **Step 1: Implementar `supabase_client.py`**

```python
# app/supabase_client.py
"""Capa de I/O contra Supabase: leer job + joins, descargar imagen, escribir
resultados. Usa la service_role key (salta RLS). Sin lógica de pipeline."""
from __future__ import annotations

from supabase import Client, create_client

from app.config import Settings
from app.pipeline.matching import Ink


def make_client(s: Settings) -> Client:
    return create_client(s.supabase_url, s.supabase_service_role_key)


def fetch_job(client: Client, job_id: str) -> dict:
    rows = client.table("analysis_jobs").select("*").eq("id", job_id).execute().data
    if not rows:
        raise ValueError(f"job {job_id} no existe")
    return rows[0]


def fetch_storage_path(client: Client, design_upload_id: str) -> str:
    rows = (
        client.table("design_uploads")
        .select("storage_path,format")
        .eq("id", design_upload_id)
        .execute()
        .data
    )
    if not rows:
        raise ValueError(f"design_upload {design_upload_id} no existe")
    return rows[0]["storage_path"]


def fetch_skin_profile_name(client: Client, project_id: str) -> str | None:
    proj = (
        client.table("projects")
        .select("skin_tone_profile_id")
        .eq("id", project_id)
        .execute()
        .data
    )
    if not proj or not proj[0].get("skin_tone_profile_id"):
        return None
    stp_id = proj[0]["skin_tone_profile_id"]
    stp = (
        client.table("skin_tone_profiles")
        .select("name")
        .eq("id", stp_id)
        .execute()
        .data
    )
    return stp[0]["name"] if stp else None


def fetch_eligible_inks(client: Client, job: dict) -> list[Ink]:
    source = job["analysis_source"]
    q = client.table("inks").select("id,lab_reference")
    if source == "brands":
        ids = job.get("selected_brand_ids") or []
        if not ids:
            return []
        q = q.in_("brand_id", ids)
    elif source == "my_inks":
        ids = job.get("selected_ink_ids") or []
        if not ids:
            return []
        q = q.in_("id", ids)
    else:
        raise ValueError(f"analysis_source desconocido: {source}")
    rows = q.execute().data
    inks = []
    for r in rows:
        lab = r["lab_reference"]
        inks.append(Ink(id=r["id"], lab=(lab["l"], lab["a"], lab["b"])))
    return inks


def download_image_bytes(client: Client, bucket: str, storage_path: str) -> bytes:
    return client.storage.from_(bucket).download(storage_path)


def set_status(client: Client, job_id: str, status: str, **extra) -> None:
    client.table("analysis_jobs").update({"status": status, **extra}).eq(
        "id", job_id
    ).execute()


def clear_previous_results(client: Client, job_id: str) -> None:
    # match_results primero (FK -> extracted_colors), luego extracted_colors
    client.table("match_results").delete().eq("analysis_job_id", job_id).execute()
    client.table("extracted_colors").delete().eq("analysis_job_id", job_id).execute()


def insert_extracted_color(client: Client, job_id: str, color: dict) -> str:
    row = {
        "analysis_job_id": job_id,
        "hex": color["hex"],
        "rgb": color["rgb"],
        "lab": color["lab"],
        "weight": color["weight"],
        "role": color["role"],
    }
    res = client.table("extracted_colors").insert(row).execute().data
    return res[0]["id"]


def insert_match_result(
    client: Client, job_id: str, extracted_color_id: str, ink_id: str, delta_e: float
) -> None:
    client.table("match_results").insert({
        "analysis_job_id": job_id,
        "extracted_color_id": extracted_color_id,
        "match_type": "direct_ink",
        "ink_id": ink_id,
        "ink_mix_id": None,
        "delta_e": delta_e,
    }).execute()
```

> Si Task 6 reveló columnas `NOT NULL` extra (o que `lab_reference` use otras claves),
> ajusta aquí los dicts de insert / el parseo de `lab` antes de continuar.

- [ ] **Step 2: Commit**

```bash
git add app/supabase_client.py
git commit -m "feat: capa de I/O contra Supabase (supabase_client.py)"
```

---

## Task 8: `runner.py` — orquestación, estados, idempotencia

**Files:**
- Create: `app/pipeline/runner.py`

- [ ] **Step 1: Implementar `runner.py`**

```python
# app/pipeline/runner.py
"""Orquesta un job (brief §4): estados pending->processing->completed/failed,
idempotencia (borra resultados previos), manejo de errores."""
import io
import logging
import traceback
from datetime import datetime, timezone

from PIL import Image

from app.config import SKIN_PROFILES, Settings
from app.pipeline.color import hex_to_rgb, rgb_to_lab
from app.pipeline.matching import best_match
from app.pipeline.palette import extract_palette
from app.pipeline.skin import precompensate
from app import supabase_client as sb

log = logging.getLogger("runner")


def process_job(job_id: str, settings: Settings) -> None:
    client = sb.make_client(settings)
    try:
        job = sb.fetch_job(client, job_id)

        # evita doble ejecución (brief §4.1)
        if job["status"] != "pending":
            log.info("job %s ya está en estado %s; no se reprocesa", job_id, job["status"])
            return

        sb.set_status(client, job_id, "processing")

        storage_path = sb.fetch_storage_path(client, job["design_upload_id"])
        skin_name = sb.fetch_skin_profile_name(client, job["project_id"])
        inks = sb.fetch_eligible_inks(client, job)
        if not inks:
            raise ValueError("conjunto de tintas elegibles vacío")

        img_bytes = sb.download_image_bytes(client, settings.supabase_storage_bucket, storage_path)
        img = Image.open(io.BytesIO(img_bytes))

        colors = extract_palette(img, settings)
        if not colors:
            raise ValueError("no se extrajo ningún color del diseño")

        # parámetros de piel
        if skin_name and skin_name in SKIN_PROFILES:
            prof = SKIN_PROFILES[skin_name]
            skin_rgb = hex_to_rgb(prof["hex"])
            s = float(prof["s"])
        else:
            skin_rgb, s = (0, 0, 0), 0.0

        # idempotencia
        sb.clear_previous_results(client, job_id)

        for color in colors:
            ec_id = sb.insert_extracted_color(client, job_id, color)
            target_rgb = (color["rgb"]["r"], color["rgb"]["g"], color["rgb"]["b"])
            comp_rgb = precompensate(target_rgb, skin_rgb, s)
            comp_lab = rgb_to_lab(*comp_rgb)
            match = best_match(comp_lab, inks)
            sb.insert_match_result(client, job_id, ec_id, match.ink_id, match.delta_e)

        sb.set_status(
            client, job_id, "completed",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        log.info("job %s completado (%d colores)", job_id, len(colors))

    except Exception as e:  # noqa: BLE001
        log.error("job %s falló: %s\n%s", job_id, e, traceback.format_exc())
        try:
            sb.set_status(client, job_id, "failed", error_message=str(e))
        except Exception:  # noqa: BLE001
            log.error("no se pudo marcar el job %s como failed", job_id)
```

- [ ] **Step 2: Verificar que importa sin errores**

Run: `python -c "from app.pipeline.runner import process_job; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/pipeline/runner.py
git commit -m "feat: orquestación de job con estados/idempotencia/errores (runner.py)"
```

---

## Task 9: `scripts/run_job.py` — CLI end-to-end

**Files:**
- Create: `scripts/run_job.py`

- [ ] **Step 1: Implementar el script**

```python
# scripts/run_job.py
"""CLI: procesa un job_id real contra el Supabase configurado en .env.
Uso: python scripts/run_job.py <job_id>"""
import logging
import sys

from app.config import get_settings
from app.pipeline.runner import process_job


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2:
        print("uso: python scripts/run_job.py <job_id>")
        raise SystemExit(2)
    job_id = sys.argv[1]
    process_job(job_id, get_settings())
    print(f"hecho. revisa analysis_jobs.status del job {job_id}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/run_job.py
git commit -m "feat: CLI run_job para prueba end-to-end (scripts/run_job.py)"
```

---

## Task 10: `app/main.py` — API FastAPI

**Files:**
- Create: `app/main.py`

- [ ] **Step 1: Implementar la API**

```python
# app/main.py
"""API HTTP del worker (brief §7): /health y /analyze (auth + BackgroundTasks)."""
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.pipeline.runner import process_job

app = FastAPI(title="Design Analyst Worker")


class AnalyzeRequest(BaseModel):
    job_id: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", status_code=202)
def analyze(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    x_worker_secret: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    if x_worker_secret != settings.worker_secret:
        raise HTTPException(status_code=401, detail="secreto inválido")
    background_tasks.add_task(process_job, req.job_id, settings)
    return {"accepted": True, "job_id": req.job_id}
```

- [ ] **Step 2: Verificar arranque y /health**

Run:
```bash
uvicorn app.main:app --port 8000 &
sleep 2 && curl -s localhost:8000/health && kill %1
```
Expected: `{"status":"ok"}`

- [ ] **Step 3: Verificar 401 sin secreto**

Run (con uvicorn corriendo):
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8000/analyze \
  -H "Content-Type: application/json" -d '{"job_id":"x"}'
```
Expected: `401`

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: API FastAPI /health y /analyze (main.py)"
```

---

## Task 11: Prueba end-to-end contra Supabase real

**Files:** ninguno (validación).

- [ ] **Step 1: Correr un job real**

Con un `job_id` `pending` real y `.env` configurado:
```bash
python scripts/run_job.py <job_id>
```
Expected: termina sin excepción.

- [ ] **Step 2: Verificar resultados en la BD**

```bash
python -c "
from supabase import create_client
from app.config import get_settings
s = get_settings(); c = create_client(s.supabase_url, s.supabase_service_role_key)
jid = '<job_id>'
print('job:', c.table('analysis_jobs').select('status,error_message,completed_at').eq('id',jid).execute().data)
print('colors:', len(c.table('extracted_colors').select('id').eq('analysis_job_id',jid).execute().data))
print('matches:', len(c.table('match_results').select('id').eq('analysis_job_id',jid).execute().data))
"
```
Expected: `status='completed'`, `error_message=None`, y nº de colors == nº de matches (> 0).

- [ ] **Step 3: Verificar idempotencia**

Vuelve a poner el job en `pending` manualmente y re-ejecuta el script; confirma que no se duplican filas (mismo conteo).

---

## Task 12: Dockerfile + README + deploy en Railway

**Files:**
- Create: `Dockerfile`, `README.md`

- [ ] **Step 1: Crear `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# deps de sistema mínimas para Pillow/scikit
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app ./app

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

- [ ] **Step 2: Build local del Docker**

Run:
```bash
docker build -t design-analyst .
```
Expected: build termina OK.

- [ ] **Step 3: Crear `README.md`**

````markdown
# Design Analyst Worker — Tattoo Inkprep

Worker Python (FastAPI) que analiza diseños y recomienda botes de tinta por
matching perceptual (ΔE CIEDE2000). Determinista y trazable. Ver `design_analyst.md`.

## Local
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # rellena las claves
pytest                 # tests del pipeline
uvicorn app.main:app --reload
```

## Probar un job real
```bash
python scripts/run_job.py <job_id>
```

## Variables de entorno
Ver `.env.example`. La `service_role` key y `WORKER_SECRET` NUNCA van a git.

## Deploy (Railway)
Repo conectado a Railway; deploy al hacer push. Variables de §9 del brief en el
panel de Railway. Healthcheck: `GET /health`.
````

- [ ] **Step 4: Commit y push**

```bash
git add Dockerfile README.md
git commit -m "chore: Dockerfile, README y prep de deploy"
git push -u origin main
```

- [ ] **Step 5: Deploy en Railway (guiado, manual)**

Cuando el usuario lo pida, guiarlo clic a clic: New Project → Deploy from GitHub →
seleccionar `Design-Analyst` → añadir variables de entorno (§9) → confirmar
healthcheck `/health` → copiar la URL pública (será `ANALYSIS_API_URL` para la app).

---

## Self-Review (cobertura del spec)

- §3 contrato → Tasks 6, 7 (verificación + I/O por tabla). ✅
- §4 ciclo de vida (estados, idempotencia, doble ejecución, errores) → Task 8. ✅
- §5.1 paleta → Task 5. ✅
- §5.2 rgb_to_lab canónica → Task 2. ✅
- §5.3 matching CIEDE2000 → Task 4. ✅
- §6 piel (compositing inverso, s=0, perfiles) → Tasks 3 y 8 (perfiles aplicados en runner). ✅
- §7 API (/health, /analyze, 401, 202, BackgroundTasks) → Task 10. ✅
- §8 estructura → Tasks 1–12. ✅
- §9 env → Task 1. ✅
- §10 deploy Railway → Task 12. ✅
- §11 pruebas (unit + e2e) → Tasks 2–5 (unit), 11 (e2e). ✅
- §13 NO-hacer (sin mezclas, sin IA, sin tocar esquema, secretos fuera de git, sin colas) → respetado en todo el plan. ✅
```
