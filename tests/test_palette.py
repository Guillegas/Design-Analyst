import numpy as np
from PIL import Image

from app.config import get_settings
from app.pipeline.palette import extract_palette


def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("WORKER_SECRET", "x")
    get_settings.cache_clear()
    return get_settings()


def _blocks(colors, block=40):
    """Imagen con bloques verticales de colores dados (sin fondo blanco)."""
    w = block * len(colors)
    img = Image.new("RGB", (w, block), colors[0])
    arr = np.array(img)
    for i, c in enumerate(colors):
        arr[:, i * block:(i + 1) * block] = c
    return Image.fromarray(arr)


def test_distinct_colors_give_that_many(monkeypatch):
    s = _settings(monkeypatch)
    colors = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (220, 200, 40)]
    palette = extract_palette(_blocks(colors), s)
    assert len(palette) == 4
    assert abs(sum(c["weight"] for c in palette) - 1.0) < 0.02
    assert any(c["role"] == "dominant" for c in palette)
    # cada salida tiene el formato del contrato
    c0 = palette[0]
    assert set(c0["rgb"]) == {"r", "g", "b"}
    assert set(c0["lab"]) == {"l", "a", "b"}
    assert c0["hex"].startswith("#")


def test_lower_merge_threshold_keeps_more_colors(monkeypatch):
    s = _settings(monkeypatch)
    # dos colores cercanos entre sí (ΔE ~4) + uno lejano
    colors = [(120, 120, 120), (132, 132, 132), (200, 40, 40)]
    img = _blocks(colors)

    s.merge_delta_e = 10.0   # fusiona los dos grises -> 2 colores
    coarse = extract_palette(img, s)
    s.merge_delta_e = 1.0    # no fusiona -> 3 colores
    fine = extract_palette(img, s)
    assert len(fine) >= len(coarse)
    assert len(coarse) <= 2
    assert len(fine) >= 3


def test_white_background_removed(monkeypatch):
    s = _settings(monkeypatch)
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    arr = np.array(img)
    arr[10:40, 10:40] = (10, 120, 200)   # mancha de color
    palette = extract_palette(Image.fromarray(arr), s)
    assert len(palette) == 1
    r = palette[0]["rgb"]
    assert not (r["r"] > 240 and r["g"] > 240 and r["b"] > 240)


def test_colored_uniform_background_removed(monkeypatch):
    s = _settings(monkeypatch)
    img = Image.new("RGB", (100, 100), (20, 60, 30))   # fondo verde oscuro uniforme
    arr = np.array(img)
    arr[10:40, 10:40] = (230, 80, 80)   # sujeto rojo
    palette = extract_palette(Image.fromarray(arr), s)
    # el fondo verde se elimina; queda el rojo dominante
    assert any(c["rgb"]["r"] > 150 for c in palette)
    assert all(not (c["rgb"]["r"] < 60 and c["rgb"]["g"] < 90 and c["rgb"]["b"] < 60)
               for c in palette)
