"""Extracción de paleta v2 (spec pipeline-v2): detección de fondo por bordes,
clustering en LAB con K alto, fusión perceptual por ΔE (nº de colores dinámico),
ruido + tope, color representativo con LAB canónico."""
import numpy as np
from PIL import Image
from sklearn.cluster import MiniBatchKMeans

from app.config import Settings
from app.pipeline.color import rgb_to_lab, rgb_to_lab_array, rgb_to_hex
from app.pipeline.matching import _delta_e, _delta_e_to_refs


def _foreground_pixels(img: Image.Image, s: Settings) -> np.ndarray:
    """Devuelve (M,3) píxeles del primer plano: descarta transparentes y el
    fondo (color uniforme detectado en los bordes; si no, fallback blanco)."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = np.asarray(img.convert("RGBA"))
        rgb2d = rgba[..., :3]
        alpha = rgba[..., 3]
    else:
        rgb2d = np.asarray(img.convert("RGB"))
        alpha = np.full(rgb2d.shape[:2], 255, dtype=np.uint8)

    h, w = rgb2d.shape[:2]
    flat = rgb2d.reshape(-1, 3)
    keep = alpha.reshape(-1) >= s.alpha_threshold
    fg = flat[keep]
    if len(fg) == 0:
        return fg

    # color de fondo candidato = mediana de los píxeles del borde
    border = np.concatenate([
        rgb2d[0, :, :], rgb2d[h - 1, :, :], rgb2d[:, 0, :], rgb2d[:, w - 1, :],
    ], axis=0).reshape(-1, 3)
    med = np.median(border, axis=0)
    med_lab = rgb_to_lab(*(int(round(v)) for v in med))
    border_lab = rgb_to_lab_array(border)
    border_d = _delta_e_to_refs(med_lab, border_lab)
    uniform_frac = float(np.mean(border_d < s.bg_merge_delta_e))

    fg_lab = rgb_to_lab_array(fg)
    if uniform_frac >= s.bg_border_fraction:
        # fondo uniforme detectado -> borrar píxeles cercanos a su color
        d = _delta_e_to_refs(med_lab, fg_lab)
        fg = fg[d >= s.bg_merge_delta_e]
    else:
        # fallback: quitar blanco casi puro
        fg = fg[~np.all(fg > s.near_white_threshold, axis=1)]
    return fg


def _merge_perceptual(clusters: list[dict], threshold: float) -> list[dict]:
    """Fusiona aglomerativamente el par de clusters más cercano por debajo de
    threshold (ΔE de su color representativo), recalculando color/peso, hasta que
    no quede ningún par bajo el umbral."""
    clusters = [dict(c) for c in clusters]
    while len(clusters) > 1:
        labs = [rgb_to_lab(*(int(round(v)) for v in c["rgb"])) for c in clusters]
        best_pair, best_de = None, threshold
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                de = _delta_e(labs[i], labs[j])
                if de < best_de:
                    best_de, best_pair = de, (i, j)
        if best_pair is None:
            break
        i, j = best_pair
        ci, cj = clusters[i], clusters[j]
        cnt = ci["count"] + cj["count"]
        rgb = (np.asarray(ci["rgb"]) * ci["count"] + np.asarray(cj["rgb"]) * cj["count"]) / cnt
        merged = {"rgb": rgb, "weight": ci["weight"] + cj["weight"], "count": cnt}
        clusters = [c for k, c in enumerate(clusters) if k not in (i, j)] + [merged]
    return clusters


def extract_palette(img: Image.Image, s: Settings) -> list[dict]:
    img = img.copy()
    img.thumbnail((s.resize_max_side, s.resize_max_side))
    pixels = _foreground_pixels(img, s)
    if len(pixels) == 0:
        return []

    lab_pixels = rgb_to_lab_array(pixels)
    k = min(s.kmeans_k_high, len(np.unique(pixels, axis=0)))
    km = MiniBatchKMeans(n_clusters=k, n_init=10, random_state=42).fit(lab_pixels)
    labels = km.labels_
    total = len(labels)

    clusters: list[dict] = []
    for i in range(k):
        sel = labels == i
        cnt = int(np.sum(sel))
        if cnt == 0:
            continue
        clusters.append({
            "rgb": pixels[sel].mean(axis=0),
            "weight": cnt / total,
            "count": cnt,
        })

    clusters = _merge_perceptual(clusters, s.merge_delta_e)

    # filtro por área, con rescate de acentos pequeños muy saturados: un cluster
    # bajo min_cluster_weight sobrevive si su croma >= chroma_keep y alcanza
    # min_chroma_weight (evita perder brillos amarillos/acentos vivos diminutos).
    def _chroma(rgb) -> float:
        _, a, b = rgb_to_lab(*(int(round(v)) for v in rgb))
        return (a * a + b * b) ** 0.5

    clusters = [
        c for c in clusters
        if c["weight"] >= s.min_cluster_weight
        or (_chroma(c["rgb"]) >= s.chroma_keep and c["weight"] >= s.min_chroma_weight)
    ]
    clusters.sort(key=lambda c: c["weight"], reverse=True)
    # el tope max_colors no debe expulsar a los acentos vivos rescatados (que por
    # definición son los de menor peso): reserva sitio para ellos.
    rescued = [c for c in clusters if c["weight"] < s.min_cluster_weight]
    main = [c for c in clusters if c["weight"] >= s.min_cluster_weight]
    keep_n = max(0, s.max_colors - len(rescued))
    clusters = main[:keep_n] + rescued

    wsum = sum(c["weight"] for c in clusters) or 1.0
    for c in clusters:
        c["weight"] /= wsum
    clusters.sort(key=lambda c: c["weight"], reverse=True)

    out = []
    for idx, c in enumerate(clusters):
        r, g, b = (int(round(v)) for v in c["rgb"])
        is_dominant = idx == 0 or c["weight"] >= s.dominant_weight
        out.append({
            "rgb": {"r": r, "g": g, "b": b},
            "hex": rgb_to_hex(r, g, b),
            "lab": dict(zip("lab", rgb_to_lab(r, g, b))),
            "weight": round(c["weight"], 4),
            "role": "dominant" if is_dominant else "secondary",
        })
    return out
