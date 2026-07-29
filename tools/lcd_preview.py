#!/usr/bin/env python3
"""Offline model of lcd-perfect.glsl.

Independent numpy reimplementation of the fragment shader, so gl_check.py can
diff the real shipped .glsl running on a GPU against it. An error has to be made
identically in both to slip through.

Mirrors the GLSL step for step; see render_lcd() for the correspondence.
"""

import numpy as np

DEFAULTS_PP = dict(
    pp_sharpness=1.00,
)

DEFAULTS_LCD = dict(
    lp_grid=0.30,
    lp_gap=0.16,
    lp_subpixels=0.20,
    lp_layout=0.0,
    lp_brightness=1.00,
    lp_gamma=1.00,
)

# Column matrix as a fraction of the row matrix, measured off a Game Boy Color
# panel. Must match GAP_ASPECT in the shader.
GAP_ASPECT = 0.4


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def aperture_integral(x, w, t, v, mode="edge"):
    """Antiderivative of the aperture profile, normalised so its mean over a cell
    is exactly 1 whatever the parameters are.

    The aperture is a trapezoid: lit across a width of w, dark across the rest,
    with a linear ramp of width t joining them. Differencing this over an output
    pixel's footprint gives the exact mean of the aperture over that pixel. At an
    integer x it equals x exactly, for every v, w and t, which is what makes the
    grid-weighted blend free.

    mode selects where the aperture sits in the cell. Only "edge" is shipped; the
    other exists so the contrast comparison that chose it stays reproducible.

      edge      aperture at the leading edge, matrix line wholly inside the cell
      centred   aperture centred, matrix line straddling the cell boundary
    """
    if mode == "centred":
        x = x - (1.0 - w) * 0.5
    elif mode != "edge":
        raise ValueError(f"unknown aperture mode {mode!r}")
    n = np.floor(x)
    f = x - n
    s0 = np.clip(f / t, 0.0, 1.0)
    s1 = np.clip((f - (w - t)) / t, 0.0, 1.0)
    phi = ((t * s0 * s0 - t * s1 * s1) * 0.5
           + np.maximum(f - t, 0.0) - np.maximum(f - w, 0.0))
    return (1.0 - v) * x + v * (n + phi / (w - t))


def area_average(src, out_w, out_h, sharpness=1.0, gamma=1.0,
                 aw=None, at=None, grid=0.0, mode="edge"):
    """The scaler pixel-perfect and lcd-perfect share, on encoded values.

    With aw given, the blend weights come from how much *aperture* falls on each
    side of the cell boundary rather than how much area, which makes the result
    the exact mean of source x grid instead of the product of their means.
    Returns (colour, px, py, dx, dy, gain).
    """
    in_h, in_w = src.shape[:2]
    tex_w, tex_h = in_w, in_h  # pass is srctype=source, so they coincide

    # texcoords at output pixel centres
    u = (np.arange(out_w) + 0.5) / out_w
    v = (np.arange(out_h) + 0.5) / out_h

    px = u * tex_w
    py = v * tex_h
    dx = max(in_w / out_w, 1e-6)
    dy = max(in_h / out_h, 1e-6)
    hx = max(0.4995 * sharpness * dx, 1e-6)
    hy = max(0.4995 * sharpness * dy, 1e-6)

    Bx = np.floor(px + 0.5)
    By = np.floor(py + 0.5)

    if aw is None:
        wx = np.clip((Bx - px + hx) / (2.0 * hx), 0.0, 1.0)
        wy = np.clip((By - py + hy) / (2.0 * hy), 0.0, 1.0)
        gain = np.ones((out_h, out_w))
    else:
        alo_x = aperture_integral(px - hx, aw[0], at[0], grid, mode)
        ahi_x = aperture_integral(px + hx, aw[0], at[0], grid, mode)
        alo_y = aperture_integral(py - hy, aw[1], at[1], grid, mode)
        ahi_y = aperture_integral(py + hy, aw[1], at[1], grid, mode)
        Ix = np.maximum(ahi_x - alo_x, 1e-6)
        Iy = np.maximum(ahi_y - alo_y, 1e-6)
        wx = np.clip((Bx - alo_x) / Ix, 0.0, 1.0)
        wy = np.clip((By - alo_y) / Iy, 0.0, 1.0)
        # peak of the profile, its flat top; scaling by it keeps the modulation
        # at or below 1 so nothing ever meets the clamp
        pkx = (1.0 - grid) + grid / (aw[0] - at[0])
        pky = (1.0 - grid) + grid / (aw[1] - at[1])
        gain = ((Iy / (2.0 * hy * pky))[:, None]
                * (Ix / (2.0 * hx * pkx))[None, :])

    # lo samples texel B-1, hi samples texel B; CLAMP_TO_EDGE at the borders
    ix_lo = np.clip(Bx.astype(int) - 1, 0, tex_w - 1)
    ix_hi = np.clip(Bx.astype(int), 0, tex_w - 1)
    iy_lo = np.clip(By.astype(int) - 1, 0, tex_h - 1)
    iy_hi = np.clip(By.astype(int), 0, tex_h - 1)

    a = src[np.ix_(iy_lo, ix_lo)]
    b = src[np.ix_(iy_lo, ix_hi)]
    c = src[np.ix_(iy_hi, ix_lo)]
    e = src[np.ix_(iy_hi, ix_hi)]

    # gamma on the taps, before the blend; base clamped because pow(0, g) is
    # undefined and returns NaN on real drivers
    if abs(gamma - 1.0) > 0.001:
        a, b, c, e = (np.power(np.maximum(t, 1e-8), gamma) for t in (a, b, c, e))

    WX = wx[None, :, None]
    WY = wy[:, None, None]
    inner_hi = e + (c - e) * WX
    inner_lo = b + (a - b) * WX
    color = inner_hi + (inner_lo - inner_hi) * WY
    return color, px, py, dx, dy, gain


def render_pixel_perfect(src_u8, out_w, out_h, p=None):
    """Mirrors pixel-perfect.glsl: the scaler on its own."""
    p = dict(DEFAULTS_PP, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    color = area_average(src, out_w, out_h, p["pp_sharpness"])[0]
    return (np.clip(color, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def render_lcd(src_u8, out_w, out_h, p=None, mode="edge", quantise=True):
    """src_u8: (H,W,3) uint8 source frame -> (out_h,out_w,3) uint8 output."""
    p = dict(DEFAULTS_LCD, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0

    awx = max(1.0 - p["lp_gap"] * GAP_ASPECT, 1e-3)
    awy = max(1.0 - p["lp_gap"], 1e-3)
    atx = min(max(2.0 * (1.0 - awx), 1e-4), 0.45 * awx)
    aty = min(max(2.0 * (1.0 - awy), 1e-4), 0.45 * awy)
    color, px, py, dx, dy, gain = area_average(
        src, out_w, out_h, 1.0, p["lp_gamma"], (awx, awy), (atx, aty),
        p["lp_grid"], mode)

    # --- RGB stripes -----------------------------------------------------
    stripe = np.ones((out_h, out_w, 3))
    if p["lp_subpixels"] > 0.0:
        amount = p["lp_subpixels"] * smoothstep(3.0, 6.0, 1.0 / dx)
        if amount > 0.0:
            third = 1.0 / 3.0
            st = min(max(0.5 * p["lp_gap"], 1e-4), 0.15 / 3.0)
            hx = 0.4995 * dx
            sx = px[:, None] - np.array([0.0, third, 2.0 * third])[None, :]
            cov = (aperture_integral(sx + hx, third, st, 1.0, mode)
                   - aperture_integral(sx - hx, third, st, 1.0, mode)) / (2.0 * hx)
            if p["lp_layout"] >= 0.5:
                cov = cov[:, ::-1]
            stripe = np.repeat((1.0 + (cov - 1.0) * amount)[None, :, :],
                               out_h, axis=0)

    m = np.sqrt(np.maximum(stripe * (gain * p["lp_brightness"])[..., None], 0.0))
    out = np.clip(color * m, 0.0, 1.0)
    # quantise=False returns 0..1 floats, for beat.py; the maths is unchanged
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out
