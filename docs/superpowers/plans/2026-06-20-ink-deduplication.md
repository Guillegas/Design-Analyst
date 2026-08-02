# De-duplicación de tintas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el resultado de un análisis nunca repita tinta: cuando dos colores del diseño resuelven a la misma tinta (o a tintas perceptualmente equivalentes de marcas distintas) se fusionan en una sola, conservando la del color más fuerte.

**Architecture:** Nuevo paso puro de consolidación post-matching en `app/pipeline/matching.py` (`consolidate_by_ink`), invocado por `runner.py` tras matchear todos los colores y antes de insertar resultados. Agrupa por equivalencia perceptual de la tinta rank-1 (ΔE CIEDE2000 < umbral; ΔE=0 cubre el mismo `ink_id`). Sin cambios de esquema.

**Tech Stack:** Python 3.12, numpy, scikit-image (`deltaE_ciede2000`), pydantic-settings, pytest.

## Global Constraints

- Spec de referencia: `docs/superpowers/specs/2026-06-20-ink-deduplication-design.md`.
- El parámetro nuevo es afinable sin tocar lógica: `ink_merge_delta_e: float = 2.0`.
- Estructura del dict `color` (producido por `extract_palette`): `{"rgb": {"r","g","b"}, "hex": str, "lab": {"l","a","b"}, "weight": float, "role": "dominant"|"secondary"}`.
- El dominante de cada grupo es el de **mayor peso** (orden estable descendente); aporta el color mostrado y su `ColorMatch`.
- Reutilizar el helper existente `_delta_e(lab1, lab2)` de `matching.py` para la distancia tinta-a-tinta.

---

### Task 1: `consolidate_by_ink` + config (TDD)

**Files:**
- Modify: `app/config.py` (añadir `ink_merge_delta_e` en la sección Matching, junto a `candidates_n`)
- Modify: `app/pipeline/matching.py` (añadir función `consolidate_by_ink` al final)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `Ink`, `Candidate`, `ColorMatch`, `_delta_e` (ya existen en `app/pipeline/matching.py`); `Settings.ink_merge_delta_e`, `Settings.dominant_weight`.
- Produces:
  ```python
  def consolidate_by_ink(
      pairs: list[tuple[dict, ColorMatch]],
      inks: list[Ink],
      s: Settings,
  ) -> list[tuple[dict, ColorMatch]]
  ```
  Devuelve la lista consolidada (≤ entradas de entrada), sin tintas rank-1 repetidas ni equivalentes. Cada `color` de salida lleva `weight` sumado (redondeado a 4) y `role` recalculado.

- [ ] **Step 1: Añadir el parámetro de config**

En `app/config.py`, dentro de la clase `Settings`, sección `# Matching`, añadir tras la línea de `candidates_n`:

```python
    ink_merge_delta_e: float = 2.0    # ΔE bajo el que dos tintas se consideran la misma
```

- [ ] **Step 2: Escribir los tests que fallan**

Añadir al final de `tests/test_matching.py`. Primero importar `consolidate_by_ink` ampliando el import existente:

```python
from app.pipeline.matching import (
    Ink, Candidate, ColorMatch, match_color, classify_quality, _delta_e_to_refs,
    consolidate_by_ink,
)
```

Y añadir el helper y los tests:

```python
def _color(weight, role, lab=(50.0, 0.0, 0.0)):
    l, a, b = lab
    return {
        "rgb": {"r": 0, "g": 0, "b": 0},
        "hex": "#000000",
        "lab": {"l": l, "a": a, "b": b},
        "weight": weight,
        "role": role,
    }


def _match(ink_id, delta_e=0.5):
    return ColorMatch(
        candidates=[Candidate(ink_id=ink_id, delta_e=delta_e, rank=1)],
        best_delta_e=delta_e,
        match_quality="excellent",
        needs_mix=False,
    )


def test_consolidate_merges_same_ink(monkeypatch):
    s = _settings(monkeypatch)
    inks = [Ink(id="black", lab=(0.0, 0.0, 0.0)), Ink(id="white", lab=(100.0, 0.0, 0.0))]
    c1, c2 = _color(0.6, "dominant"), _color(0.2, "secondary")
    m = _match("black")
    out = consolidate_by_ink([(c1, m), (c2, m)], inks, s)
    assert len(out) == 1
    assert out[0][1].candidates[0].ink_id == "black"
    assert out[0][0]["weight"] == pytest.approx(0.8)


def test_consolidate_merges_perceptually_equal_inks(monkeypatch):
    s = _settings(monkeypatch)
    # dos negros casi idénticos de dos marcas (ΔE < 2.0)
    inks = [
        Ink(id="A_black", lab=(1.0, 0.0, 0.0)),
        Ink(id="B_black", lab=(1.5, 0.0, 0.0)),
        Ink(id="white", lab=(100.0, 0.0, 0.0)),
    ]
    c1, c2 = _color(0.5, "dominant"), _color(0.3, "secondary")
    out = consolidate_by_ink([(c1, _match("A_black")), (c2, _match("B_black"))], inks, s)
    assert len(out) == 1
    # gana el dominante (mayor peso) -> su tinta A_black
    assert out[0][1].candidates[0].ink_id == "A_black"
    assert out[0][0]["weight"] == pytest.approx(0.8)


def test_consolidate_keeps_distinct_inks(monkeypatch):
    s = _settings(monkeypatch)
    inks = [Ink(id="black", lab=(0.0, 0.0, 0.0)), Ink(id="white", lab=(100.0, 0.0, 0.0))]
    c1, c2 = _color(0.5, "dominant"), _color(0.4, "secondary")
    out = consolidate_by_ink([(c1, _match("black")), (c2, _match("white"))], inks, s)
    assert len(out) == 2


def test_consolidate_recomputes_role_to_dominant(monkeypatch):
    s = _settings(monkeypatch)  # dominant_weight = 0.15
    inks = [Ink(id="black", lab=(0.0, 0.0, 0.0))]
    c1, c2 = _color(0.08, "secondary"), _color(0.09, "secondary")
    m = _match("black")
    out = consolidate_by_ink([(c1, m), (c2, m)], inks, s)
    assert len(out) == 1
    assert out[0][0]["weight"] == pytest.approx(0.17)
    assert out[0][0]["role"] == "dominant"  # 0.17 >= 0.15
```

- [ ] **Step 3: Ejecutar los tests para verificar que fallan**

Run: `.venv/bin/pytest tests/test_matching.py -k consolidate -v`
Expected: FAIL con `ImportError: cannot import name 'consolidate_by_ink'`.

- [ ] **Step 4: Implementar `consolidate_by_ink`**

Añadir al final de `app/pipeline/matching.py`:

```python
def consolidate_by_ink(
    pairs: list[tuple[dict, ColorMatch]],
    inks: list[Ink],
    s: Settings,
) -> list[tuple[dict, ColorMatch]]:
    """Fusiona colores cuya tinta rank-1 es la misma o perceptualmente equivalente
    (ΔE < ink_merge_delta_e). Gana el color de mayor peso; los pesos se suman y el
    role se recalcula."""
    ink_lab = {ink.id: ink.lab for ink in inks}
    ordered = sorted(pairs, key=lambda p: p[0]["weight"], reverse=True)

    groups: list[dict] = []
    for color, match in ordered:
        rank1_lab = ink_lab[match.candidates[0].ink_id]
        placed = False
        for g in groups:
            if _delta_e(g["rep_ink_lab"], rank1_lab) < s.ink_merge_delta_e:
                g["weight"] += color["weight"]
                placed = True
                break
        if not placed:
            groups.append({
                "rep_ink_lab": rank1_lab,
                "color": color,
                "match": match,
                "weight": color["weight"],
            })

    out: list[tuple[dict, ColorMatch]] = []
    for g in groups:
        color = dict(g["color"])
        color["weight"] = round(g["weight"], 4)
        is_dominant = color["role"] == "dominant" or g["weight"] >= s.dominant_weight
        color["role"] = "dominant" if is_dominant else "secondary"
        out.append((color, g["match"]))
    return out
```

- [ ] **Step 5: Ejecutar los tests para verificar que pasan**

Run: `.venv/bin/pytest tests/test_matching.py -v`
Expected: PASS (los 4 nuevos `consolidate_*` y los existentes).

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/pipeline/matching.py tests/test_matching.py
git commit -m "feat(matching): consolidate_by_ink — fusiona tintas duplicadas/equivalentes"
```

---

### Task 2: Cablear consolidación en el runner

**Files:**
- Modify: `app/pipeline/runner.py` (import + bucle de matching → acumular, consolidar, insertar)

**Interfaces:**
- Consumes: `consolidate_by_ink(pairs, inks, settings)` de Task 1.
- Produces: nada nuevo (cambio de orquestación interno).

- [ ] **Step 1: Ampliar el import de matching**

En `app/pipeline/runner.py`, cambiar:

```python
from app.pipeline.matching import match_color
```

por:

```python
from app.pipeline.matching import match_color, consolidate_by_ink
```

- [ ] **Step 2: Sustituir el bucle de matching+insert por acumular → consolidar → insertar**

Reemplazar el bloque actual:

```python
        for color in colors:
            target_rgb = (color["rgb"]["r"], color["rgb"]["g"], color["rgb"]["b"])
            comp_rgb = precompensate(target_rgb, skin_rgb, s)
            comp_lab = rgb_to_lab(*comp_rgb)
            match = match_color(comp_lab, inks, settings)
            ec_id = sb.insert_extracted_color(client, job_id, color, match)
            sb.insert_match_candidates(client, job_id, ec_id, match.candidates)
```

por:

```python
        pairs = []
        for color in colors:
            target_rgb = (color["rgb"]["r"], color["rgb"]["g"], color["rgb"]["b"])
            comp_rgb = precompensate(target_rgb, skin_rgb, s)
            comp_lab = rgb_to_lab(*comp_rgb)
            match = match_color(comp_lab, inks, settings)
            pairs.append((color, match))

        pairs = consolidate_by_ink(pairs, inks, settings)

        for color, match in pairs:
            ec_id = sb.insert_extracted_color(client, job_id, color, match)
            sb.insert_match_candidates(client, job_id, ec_id, match.candidates)
```

- [ ] **Step 3: Actualizar el log de recuento de colores**

Cambiar:

```python
        log.info("job %s completado (%d colores)", job_id, len(colors))
```

por:

```python
        log.info("job %s completado (%d colores)", job_id, len(pairs))
```

- [ ] **Step 4: Verificar que toda la suite sigue verde**

Run: `.venv/bin/pytest -q`
Expected: PASS (sin regresiones).

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/runner.py
git commit -m "feat(runner): consolidar tintas duplicadas antes de insertar resultados"
```
