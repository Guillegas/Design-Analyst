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
