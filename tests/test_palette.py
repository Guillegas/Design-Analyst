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
    assert abs(sum(c["weight"] for c in colors) - 1.0) < 0.05
    assert any(c["role"] == "dominant" for c in colors)
    hexes = {c["hex"] for c in colors}
    assert len(hexes) == 2


def test_near_white_background_is_discarded(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("WORKER_SECRET", "x")
    get_settings.cache_clear()

    img = Image.new("RGB", (100, 100), (255, 255, 255))
    for x in range(0, 20):
        for y in range(0, 20):
            img.putpixel((x, y), (10, 120, 200))
    colors = extract_palette(img, get_settings())

    assert len(colors) == 1
    r = colors[0]["rgb"]
    assert not (r["r"] > 240 and r["g"] > 240 and r["b"] > 240)
