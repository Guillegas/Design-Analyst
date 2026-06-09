from app.pipeline.color import rgb_to_lab, hex_to_rgb, rgb_to_hex


def test_white_maps_to_lab_100():
    L, a, b = rgb_to_lab(255, 255, 255)
    assert L == 100.0
    assert abs(a) < 0.01 and abs(b) < 0.01


def test_black_maps_to_lab_0():
    L, a, b = rgb_to_lab(0, 0, 0)
    assert L == 0.0 and a == 0.0 and b == 0.0


def test_known_red_value():
    L, a, b = rgb_to_lab(255, 0, 0)
    assert abs(L - 53.24) < 0.1
    assert abs(a - 80.09) < 0.1
    assert abs(b - 67.20) < 0.1


def test_hex_roundtrip():
    assert hex_to_rgb("#FF8000") == (255, 128, 0)
    assert rgb_to_hex(255, 128, 0) == "#FF8000"


import numpy as np
from app.pipeline.color import rgb_to_lab_array


def test_array_matches_scalar():
    rgbs = [(255, 255, 255), (0, 0, 0), (255, 0, 0), (25, 100, 147), (128, 64, 200)]
    arr = rgb_to_lab_array(np.array(rgbs, dtype=np.float64))
    for i, rgb in enumerate(rgbs):
        L, a, b = rgb_to_lab(*rgb)
        assert abs(round(float(arr[i, 0]), 2) - L) < 0.01
        assert abs(round(float(arr[i, 1]), 2) - a) < 0.01
        assert abs(round(float(arr[i, 2]), 2) - b) < 0.01


def test_array_shape():
    arr = rgb_to_lab_array(np.zeros((10, 3)))
    assert arr.shape == (10, 3)
