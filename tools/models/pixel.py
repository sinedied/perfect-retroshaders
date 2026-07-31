#!/usr/bin/env python3
"""Reference models for the pixel-perfect family.

These lived in the LCD module, which is drift: pixel-perfect shares the scaler
with lcd-perfect but is a different shader with different parameters, and
keeping them together meant two copies of render_pixel_perfect existed at once,
in two modules, with nothing importing one of them.
"""

import numpy as np

from models.common import smoothstep
from models.lcd import area_average

LUMA_709 = np.array([0.2126, 0.7152, 0.0722])
TINT_AXIS = np.array([-0.5, 1.0, -0.5])
WARM_AXIS = np.array([1.0, 0.0, -1.0])

DEFAULTS_PP = dict(
    pp_sharpness=1.00,
)

DEFAULTS_PP_V2 = dict(
    pp_sharpness=1.00,
    pp_gamma=1.00,
)

DEFAULTS_PP_V3 = dict(
    pp_saturation=1.00,
    pp_contrast=1.00,
    pp_brightness=1.00,
    pp_gamma=1.00,
)

DEFAULTS_PP_V4 = dict(DEFAULTS_PP_V3)

DEFAULTS_PP_V5 = dict(DEFAULTS_PP_V4, pp_red=1.00, pp_green=1.00, pp_blue=1.00)

DEFAULTS_PP_V6 = dict(
    pp_brightness=1.00,
    pp_contrast=1.00,
    pp_saturation=1.00,
    pp_gamma=1.00,
    pp_temperature=0.00,
    pp_tint=0.00,
)


def render_pixel_perfect(src_u8, out_w, out_h, p=None):
    """Mirrors pixel-perfect.glsl: the scaler on its own."""
    p = dict(DEFAULTS_PP, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    color = area_average(src, out_w, out_h, p["pp_sharpness"])[0]
    return (np.clip(color, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def render_pixel_perfect_v2(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors pixel-perfect-v2.glsl: the scaler plus a post-blend gamma.

    The gamma goes on the blended colour, not on the taps, so this is NOT
    area_average's gamma argument - that one applies it before the blend.
    """
    p = dict(DEFAULTS_PP_V2, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    col = area_average(src, out_w, out_h, p["pp_sharpness"])[0]
    if abs(p["pp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["pp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


def render_pixel_perfect_v3(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors pixel-perfect-v3.glsl: the scaler plus a four-control grade.

    There is no sharpness parameter, so the footprint is always the full output
    pixel.     Brightness, contrast and saturation fold into a single affine map rather
    than three steps, for the same reason the shader folds them: at the defaults
    it is col*1 + 0 exactly, where the literal chain would round.

    Being affine is also why the grade may sit after the blend at all. The
    scaler's weights sum to 1, so A*sum(w_i * x_i) + B == sum(w_i * (A*x_i + B))
    - post-blend and per-tap are the same result. Only the clamp and the gamma
    are non-linear, and only they can manufacture a pattern.
    """
    p = dict(DEFAULTS_PP_V3, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    col = area_average(src, out_w, out_h)[0]

    A = p["pp_brightness"] * p["pp_contrast"]
    B = 0.5 - 0.5 * p["pp_contrast"]
    s = p["pp_saturation"]
    luma = (col * LUMA_709).sum(axis=-1, keepdims=True)
    col = col * (A * s) + (luma * (A * (1.0 - s)) + B)

    col = np.clip(col, 0.0, 1.0)
    if abs(p["pp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["pp_gamma"])
    return (col * 255.0 + 0.5).astype(np.uint8) if quantise else col


def render_pixel_perfect_v4(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors pixel-perfect-v4.glsl: v3 with the affine block behind a guard.

    Same output as v3 everywhere - the guard is an exact comparison with no dead
    band, and at 1.00 the block it skips is col*1.0 + 0.0, which is exact, so
    the two agree at every parameter value rather than merely outside a
    tolerance. That is why this is a guard and not a behaviour change.

    Tested separately per control, never as a sum: brightness 1.1 with contrast
    0.9 sums to exactly 3.0 and would be read as neutral.

    The clamp is inside the guard because only a grade can push a value out of
    0 to 1: the scaler's output is a convex blend of taps already in range.
    """
    p = dict(DEFAULTS_PP_V4, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    col = area_average(src, out_w, out_h)[0]

    if (p["pp_brightness"] != 1.0 or p["pp_contrast"] != 1.0
            or p["pp_saturation"] != 1.0):
        ga = p["pp_brightness"] * p["pp_contrast"]
        gb = 0.5 - 0.5 * p["pp_contrast"]
        s = p["pp_saturation"]
        luma = (col * LUMA_709).sum(axis=-1, keepdims=True)
        col = col * (ga * s) + (luma * (ga * (1.0 - s)) + gb)
        col = np.clip(col, 0.0, 1.0)

    if abs(p["pp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["pp_gamma"])
    return (col * 255.0 + 0.5).astype(np.uint8) if quantise else col


def render_pixel_perfect_v5(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors pixel-perfect-v5.glsl: v4 plus a per-channel trim.

    The trim is a separate multiply after the affine map, not folded into its
    coefficients. Folding is possible - a diagonal gain composes with an affine
    map - but it makes the coefficients vec3, which widens the luma term from
    scalar to vec3 and costs more than the multiply it saves. Measured 4
    instructions worse both ways round.

    It also has to come after the saturation mix rather than before, since
    dot(col*t, LUMA) is not t*dot(col, LUMA).

    Neutral at t = 1 by construction, and the guard is exact, so with the trim
    left alone this is v4 to the bit at every other setting.
    """
    p = dict(DEFAULTS_PP_V5, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    col = area_average(src, out_w, out_h)[0]

    if (p["pp_brightness"] != 1.0 or p["pp_contrast"] != 1.0
            or p["pp_saturation"] != 1.0 or p["pp_red"] != 1.0
            or p["pp_green"] != 1.0 or p["pp_blue"] != 1.0):
        ga = p["pp_brightness"] * p["pp_contrast"]
        gb = 0.5 - 0.5 * p["pp_contrast"]
        s = p["pp_saturation"]
        luma = (col * LUMA_709).sum(axis=-1, keepdims=True)
        col = col * (ga * s) + (luma * (ga * (1.0 - s)) + gb)
        col = col * np.array([p["pp_red"], p["pp_green"], p["pp_blue"]])
        col = np.clip(col, 0.0, 1.0)

    if abs(p["pp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["pp_gamma"])
    return (col * 255.0 + 0.5).astype(np.uint8) if quantise else col


def render_pixel_perfect_v6(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors pixel-perfect-v6.glsl: v5 with the trim as temperature + tint.

    Not normalised on luma, by decision: the axes shift the overall level a
    little as well as the colour, and pp_brightness takes that back out.
    """
    p = dict(DEFAULTS_PP_V6, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    col = area_average(src, out_w, out_h)[0]

    if (p["pp_brightness"] != 1.0 or p["pp_contrast"] != 1.0
            or p["pp_saturation"] != 1.0 or p["pp_temperature"] != 0.0
            or p["pp_tint"] != 0.0):
        ga = p["pp_brightness"] * p["pp_contrast"]
        gb = 0.5 - 0.5 * p["pp_contrast"]
        s = p["pp_saturation"]
        luma = (col * LUMA_709).sum(axis=-1, keepdims=True)
        col = col * (ga * s) + (luma * (ga * (1.0 - s)) + gb)
        col = col * (1.0 + p["pp_temperature"] * WARM_AXIS
                         + p["pp_tint"] * TINT_AXIS)
        col = np.clip(col, 0.0, 1.0)

    if abs(p["pp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["pp_gamma"])
    return (col * 255.0 + 0.5).astype(np.uint8) if quantise else col


