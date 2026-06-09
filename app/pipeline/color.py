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


import numpy as np


def rgb_to_lab_array(rgb: np.ndarray) -> np.ndarray:
    """Versión vectorizada de rgb_to_lab para (N,3) -> (N,3) sin redondear
    (precisión interna del clustering). Misma conversión canónica (D65)."""
    arr = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[:, 0], lin[:, 1], lin[:, 2]
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    delta = 6 / 29

    def f(t: np.ndarray) -> np.ndarray:
        return np.where(t > delta ** 3, np.cbrt(t), t / (3 * delta ** 2) + 4 / 29)

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    return np.stack([L, a, bb], axis=1)
