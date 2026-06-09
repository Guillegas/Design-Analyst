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
    not_white = ~np.all(rgb > s.near_white_threshold, axis=1)
    return rgb[not_white]


def extract_palette(img: Image.Image, s: Settings) -> list[dict]:
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

    clusters = [c for c in clusters if c["weight"] >= s.min_cluster_weight]

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
