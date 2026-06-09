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
