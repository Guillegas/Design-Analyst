from app.pipeline.skin import precompensate


def test_s_zero_leaves_color_unchanged():
    assert precompensate((120, 80, 60), skin_rgb=(150, 100, 80), s=0.0) == (120, 80, 60)


def test_dark_skin_pushes_toward_lighter_or_clamped():
    assert precompensate((100, 100, 100), skin_rgb=(40, 40, 40), s=0.5) == (160, 160, 160)


def test_result_is_clamped_to_0_255():
    r, g, b = precompensate((250, 250, 250), skin_rgb=(0, 0, 0), s=0.5)
    assert (r, g, b) == (255, 255, 255)
    r2, g2, b2 = precompensate((10, 10, 10), skin_rgb=(255, 255, 255), s=0.5)
    assert (r2, g2, b2) == (0, 0, 0)
