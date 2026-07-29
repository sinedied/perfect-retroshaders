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
    lp_grid=0.80,
    lp_gap=0.12,
    lp_subpixels=0.35,
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


def aperture(x, d, w, mode="edge"):
    """Exact mean of a unit pulse train (period 1, lit width w) over a footprint
    of d centred on x.

    mode selects where the aperture sits in the cell. Only "edge" is shipped;
    the others exist so the contrast comparison that chose it stays reproducible.

      edge      aperture at the leading edge, matrix line wholly inside the cell
      centred   aperture centred, matrix line straddling the cell boundary
      shifted   centred, plus a half-output-pixel phase shift
    """
    if mode == "centred":
        x = x - (1.0 - w) * 0.5
    elif mode == "shifted":
        x = x - (1.0 - w) * 0.5 - 0.5 * d
    elif mode != "edge":
        raise ValueError(f"unknown aperture mode {mode!r}")

    lo, hi = x - 0.5 * d, x + 0.5 * d
    fl, fh = np.floor(lo), np.floor(hi)
    return ((fh - fl) * w
            + np.clip(hi - fh, 0.0, w)
            - np.clip(lo - fl, 0.0, w)) / d


def area_average(src, out_w, out_h, sharpness=1.0, gamma=1.0):
    """The scaler pixel-perfect and lcd-perfect share, on encoded values.

    Returns (colour, px, py, dx, dy): the blended image plus the source-pixel
    coordinates and footprint, which the caller needs for the grid.
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
    wx = np.clip((Bx - px + hx) / (2.0 * hx), 0.0, 1.0)
    wy = np.clip((By - py + hy) / (2.0 * hy), 0.0, 1.0)

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
    return inner_hi + (inner_lo - inner_hi) * WY, px, py, dx, dy


def render_pixel_perfect(src_u8, out_w, out_h, p=None):
    """Mirrors pixel-perfect.glsl: the scaler on its own."""
    p = dict(DEFAULTS_PP, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    color, _, _, _, _ = area_average(src, out_w, out_h, p["pp_sharpness"])
    return (np.clip(color, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def render_lcd(src_u8, out_w, out_h, p=None, mode="edge"):
    """src_u8: (H,W,3) uint8 source frame -> (out_h,out_w,3) uint8 output."""
    p = dict(DEFAULTS_LCD, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0

    color, px, py, dx, dy = area_average(src, out_w, out_h, 1.0, p["lp_gamma"])

    # --- the black matrix ------------------------------------------------
    gain = np.ones((out_h, out_w))
    if p["lp_grid"] > 0.0 and p["lp_gap"] > 0.0:
        awx = max(1.0 - p["lp_gap"] * GAP_ASPECT, 1e-3)
        awy = max(1.0 - p["lp_gap"], 1e-3)
        gx = 1.0 + p["lp_grid"] * (aperture(px, dx, awx, mode) / awx - 1.0)
        gy = 1.0 + p["lp_grid"] * (aperture(py, dy, awy, mode) / awy - 1.0)
        gain = gy[:, None] * gx[None, :]

    # --- RGB stripes -----------------------------------------------------
    stripe = np.ones((out_h, out_w, 3))
    if p["lp_subpixels"] > 0.0:
        amount = p["lp_subpixels"] * smoothstep(3.0, 6.0, 1.0 / dx)
        if amount > 0.0:
            third = 1.0 / 3.0
            phase = np.array([0.0, third, 2.0 * third])
            cov = aperture(px[:, None] - phase[None, :], dx, third, mode)
            if p["lp_layout"] >= 0.5:
                cov = cov[:, ::-1]
            stripe = np.repeat((1.0 + (cov * 3.0 - 1.0) * amount)[None, :, :],
                               out_h, axis=0)

    m = np.sqrt(np.maximum(stripe * (gain * p["lp_brightness"])[..., None], 0.0))
    return (np.clip(color * m, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
