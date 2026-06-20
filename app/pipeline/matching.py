"""Matching perceptual v2: para un LAB extraído (ya ajustado por piel), devuelve
las N tintas elegibles más cercanas (ΔE CIEDE2000) rankeadas, más la calidad del
mejor match y un flag needs_mix."""
from dataclasses import dataclass

import numpy as np
from skimage.color import deltaE_ciede2000

from app.config import Settings


@dataclass(frozen=True)
class Ink:
    id: str
    lab: tuple[float, float, float]


@dataclass(frozen=True)
class Candidate:
    ink_id: str
    delta_e: float
    rank: int


@dataclass(frozen=True)
class ColorMatch:
    candidates: list[Candidate]
    best_delta_e: float
    match_quality: str
    needs_mix: bool


def _delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    a = np.array(lab1, dtype=float).reshape(1, 1, 3)
    b = np.array(lab2, dtype=float).reshape(1, 1, 3)
    return float(deltaE_ciede2000(a, b)[0, 0])


def _delta_e_to_refs(lab: tuple[float, float, float], refs: np.ndarray) -> np.ndarray:
    """ΔE CIEDE2000 de un color (lab) contra N referencias (refs: (N,3)) -> (N,)."""
    color = np.asarray(lab, dtype=float).reshape(1, 1, 3)
    ref = np.asarray(refs, dtype=float).reshape(1, -1, 3)
    color = np.broadcast_to(color, ref.shape)
    return deltaE_ciede2000(color, ref)[0]


def classify_quality(delta_e: float, s: Settings) -> str:
    if delta_e <= s.quality_excellent:
        return "excellent"
    if delta_e <= s.quality_good:
        return "good"
    if delta_e <= s.quality_fair:
        return "fair"
    return "poor"


def match_color(lab: tuple[float, float, float], inks: list[Ink], s: Settings) -> ColorMatch:
    if not inks:
        raise ValueError("No hay tintas elegibles para el matching")
    ref_labs = np.array([ink.lab for ink in inks], dtype=float)
    des = _delta_e_to_refs(lab, ref_labs)
    order = np.argsort(des)[: s.candidates_n]
    candidates = [
        Candidate(ink_id=inks[int(i)].id, delta_e=round(float(des[int(i)]), 4), rank=r + 1)
        for r, i in enumerate(order)
    ]
    best = candidates[0].delta_e
    quality = classify_quality(best, s)
    return ColorMatch(
        candidates=candidates,
        best_delta_e=best,
        match_quality=quality,
        needs_mix=best > s.quality_fair,
    )


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

    # agrupación anclada al representante (no transitiva): cada color se compara
    # solo con la tinta rank-1 del grupo, no con todos sus miembros.
    groups: list[dict] = []
    for color, match in ordered:
        ink_id = match.candidates[0].ink_id
        if ink_id not in ink_lab:
            raise ValueError(f"consolidate_by_ink: tinta '{ink_id}' no está en la lista de inks")
        rank1_lab = ink_lab[ink_id]
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
