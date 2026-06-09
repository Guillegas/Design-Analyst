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
