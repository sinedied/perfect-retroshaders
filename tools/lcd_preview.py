#!/usr/bin/env python3
"""Offline model of the lcd-perfect family and pixel-perfect.

Independent numpy reimplementation of the fragment shader, so gl_check.py can
diff the real shipped .glsl running on a GPU against it. An error has to be made
identically in both to slip through.

Mirrors the GLSL step for step. render_lcd_v3() is the shipped
lcd-perfect.glsl; the rest are the superseded versions kept in
tools/iterations/ and still verified.
"""

import numpy as np

DEFAULTS_PP = dict(
    pp_sharpness=1.00,
)

DEFAULTS_PP_V2 = dict(
    pp_sharpness=1.00,
    pp_gamma=1.00,
)

# v3 drops pp_sharpness - below 1.00 it narrows the footprint past the output
# pixel, which turns the area average back into nearest-neighbour and restores
# the crawling, uneven blocks the shader exists to remove - and spends the space
# on a grade instead.
DEFAULTS_PP_V3 = dict(
    pp_saturation=1.00,
    pp_contrast=1.00,
    pp_brightness=1.00,
    pp_gamma=1.00,
)

# Rec.709, matching LUMA in pixel-perfect-v3.glsl.
LUMA_709 = np.array([0.2126, 0.7152, 0.0722])

DEFAULTS_LCD = dict(
    lp_grid=0.30,
    lp_gap=0.16,
    lp_subpixels=0.20,
    lp_layout=0.0,
    lp_brightness=1.00,
    lp_gamma=1.00,
)

DEFAULTS_V2B = dict(
    lp_grid=0.35,
    lp_balance=0.84,
    lp_gap=0.12,
    lp_subpixels=0.20,
    lp_layout=0.0,
    lp_brightness=1.00,
    lp_gamma=1.00,
)

DEFAULTS_V2A = dict(
    lp_grid=0.37,
    lp_balance=0.79,
    lp_subpixels=0.20,
    lp_layout=0.0,
    lp_brightness=1.00,
    lp_gamma=1.00,
)

# Column matrix as a fraction of the row matrix, measured off a Game Boy Color
# panel. Must match GAP_ASPECT in lcd-perfect-v1.glsl. v2 replaces it with the
# lp_balance parameter, because it caps the column gap at 40% of the row gap and
# so cannot reach lcd1x's 4:1 the other way round.
GAP_ASPECT = 0.4

TAU = 2.0 * np.pi

# Stripe fade window, in output pixels per cell. Must match the shader it
# belongs to - v1 shipped with 3 to 6, which leaves the stripes at 1.3% strength
# at 3.2 px/cell and so inert at 320x240 into 1024x768; v2 widens it.
STRIPE_FADE = (3.0, 6.0)
STRIPE_FADE_V2 = (2.5, 5.0)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def aperture_trapezoid(x, w, t, v, mode="edge"):
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
                 aw=None, at=None, grid=0.0, mode="edge", aperture=None):
    """The scaler pixel-perfect and lcd-perfect share, on encoded values.

    With aw given, the blend weights come from how much *aperture* falls on each
    side of the cell boundary rather than how much area, which makes the result
    the exact mean of source x grid instead of the product of their means.

    aperture overrides that with a callable (coord, half_footprint, axis) ->
    (Alo, Ahi, AB_minus_B, peak), which is how the sinusoidal variant plugs its
    own profile in without duplicating the blend.

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

    if aperture is not None:
        alo_x, ahi_x, abx, pkx = aperture(px, hx, 0)
        alo_y, ahi_y, aby, pky = aperture(py, hy, 1)
        Ix = np.maximum(ahi_x - alo_x, 1e-6)
        Iy = np.maximum(ahi_y - alo_y, 1e-6)
        wx = np.clip((Bx + abx - alo_x) / Ix, 0.0, 1.0)
        wy = np.clip((By + aby - alo_y) / Iy, 0.0, 1.0)
        gain = ((Iy / (2.0 * hy * pky))[:, None]
                * (Ix / (2.0 * hx * pkx))[None, :])
    elif aw is None:
        wx = np.clip((Bx - px + hx) / (2.0 * hx), 0.0, 1.0)
        wy = np.clip((By - py + hy) / (2.0 * hy), 0.0, 1.0)
        gain = np.ones((out_h, out_w))
    else:
        alo_x = aperture_trapezoid(px - hx, aw[0], at[0], grid, mode)
        ahi_x = aperture_trapezoid(px + hx, aw[0], at[0], grid, mode)
        alo_y = aperture_trapezoid(py - hy, aw[1], at[1], grid, mode)
        ahi_y = aperture_trapezoid(py + hy, aw[1], at[1], grid, mode)
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


def stripe_factor(p, px, dx, out_w, out_h, st, mode="edge",
                  fade=STRIPE_FADE):
    """The RGB stripe modulation, shared by every lcd-perfect variant.

    Three trapezoid apertures of a third of a cell each, box filtered the same
    way as the grid. Their coverages sum to exactly one at every scale, so the
    stripe is exactly luminance neutral, and blending toward white keeps that
    true at any visibility.

    Mean-normalised, not peak-normalised like the grid: a stripe concentrates one
    channel's light into a third of a cell, so its mean is what must stay at 1
    for white to stay white, which puts its peak near 3.
    """
    stripe = np.ones((out_h, out_w, 3))
    if p["lp_subpixels"] <= 0.0:
        return stripe
    amount = p["lp_subpixels"] * smoothstep(*fade, 1.0 / dx)
    if amount <= 0.0:
        return stripe
    third = 1.0 / 3.0
    hx = 0.4995 * dx
    sx = px[:, None] - np.array([0.0, third, 2.0 * third])[None, :]
    cov = (aperture_trapezoid(sx + hx, third, st, 1.0, mode)
           - aperture_trapezoid(sx - hx, third, st, 1.0, mode)) / (2.0 * hx)
    if p["lp_layout"] >= 0.5:
        cov = cov[:, ::-1]
    return np.repeat((1.0 + (cov - 1.0) * amount)[None, :, :], out_h, axis=0)


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


def render_lcd(src_u8, out_w, out_h, p=None, mode="edge", quantise=True,
               balance=None):
    """Mirrors lcd-perfect-v1.glsl: the trapezoid aperture, GAP_ASPECT fixed.

    balance given mirrors lcd-perfect-v2b.glsl instead, which splits the matrix
    between the axes by lp_balance rather than by that constant.
    """
    p = dict(DEFAULTS_V2B if balance else DEFAULTS_LCD, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0

    if balance:
        b = p["lp_balance"]
        awx = max(1.0 - p["lp_gap"] * 2.0 * b, 1e-3)
        awy = max(1.0 - p["lp_gap"] * 2.0 * (1.0 - b), 1e-3)
    else:
        awx = max(1.0 - p["lp_gap"] * GAP_ASPECT, 1e-3)
        awy = max(1.0 - p["lp_gap"], 1e-3)
    atx = min(max(2.0 * (1.0 - awx), 1e-4), 0.45 * awx)
    aty = min(max(2.0 * (1.0 - awy), 1e-4), 0.45 * awy)
    color, px, py, dx, dy, gain = area_average(
        src, out_w, out_h, 1.0, p["lp_gamma"], (awx, awy), (atx, aty),
        p["lp_grid"], mode)

    stripe = stripe_factor(p, px, dx, out_w, out_h,
                           st=min(max(0.5 * p["lp_gap"], 1e-4), 0.15 / 3.0),
                           mode=mode,
                           fade=STRIPE_FADE_V2 if balance else STRIPE_FADE)

    m = np.sqrt(np.maximum(stripe * (gain * p["lp_brightness"])[..., None], 0.0))
    out = np.clip(color * m, 0.0, 1.0)
    # quantise=False returns 0..1 floats, for beat.py; the maths is unchanged
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


def aperture_sine(x, m, phase):
    """Antiderivative of a sinusoidal aperture of one cycle per cell:

        a(x) = 1 - m * cos(TAU * (x - phase))
        A(x) = x - m * sin(TAU * (x - phase)) / TAU

    A(n) == n at integers when phase is 0, and A(n) - n is a constant otherwise,
    which is what keeps the aperture-weighted blend free.
    """
    return x - m * np.sin(TAU * (x - phase)) / TAU


def render_lcd_v2a(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors lcd-perfect-v2a.glsl: sinusoidal aperture, lp_balance."""
    p = dict(DEFAULTS_V2A, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]

    amp = np.clip(p["lp_grid"] * 2.0
                  * np.array([p["lp_balance"], 1.0 - p["lp_balance"]]), 0.0, 1.0)
    d = (max(in_w / out_w, 1e-6), max(in_h / out_h, 1e-6))

    def aperture(coord, half, axis):
        m = amp[axis]
        # half an output pixel, unconditionally: without it every even-integer
        # scale reads the same value from both samples of a cell
        phase = 0.5 * d[axis]
        return (aperture_sine(coord - half, m, phase),
                aperture_sine(coord + half, m, phase),
                m * np.sin(TAU * phase) / TAU,
                1.0 + m)

    color, px, py, dx, dy, gain = area_average(
        src, out_w, out_h, 1.0, p["lp_gamma"], aperture=aperture)

    stripe = stripe_factor(p, px, dx, out_w, out_h, st=0.05,
                           fade=STRIPE_FADE_V2)

    m = np.sqrt(np.maximum(stripe * (gain * p["lp_brightness"])[..., None], 0.0))
    out = np.clip(color * m, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


DEFAULTS_V3 = dict(
    lp_grid=0.30,
    lp_balance=0.50,
    lp_min_pitch=3.00,
    lp_subpixels=0.20,
    lp_layout=0.0,
    lp_brightness=1.20,
    lp_gamma=1.00,
)


def box_sinc(f):
    """Mean of a unit sinusoid of f cycles per output pixel over one pixel."""
    x = np.pi * np.maximum(f, 1e-4)
    return np.sin(x) / x


def nyquist_fade(f):
    return 1.0 - smoothstep(0.34, 0.5, f)


def render_lcd_v3(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors lcd-perfect.glsl.

    Written out rather than routed through area_average(): v3 puts the mesh on a
    whole number of cells per period, which that helper has no place for, and a
    model meant to be read against the GLSL is worth more than a shared path.
    """
    p = dict(DEFAULTS_V3, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]
    tex_w, tex_h = in_w, in_h

    px = (np.arange(out_w) + 0.5) / out_w * tex_w
    py = (np.arange(out_h) + 0.5) / out_h * tex_h
    d = np.array([max(in_w / out_w, 1e-6), max(in_h / out_h, 1e-6)])
    h = 0.4995 * d
    Bx, By = np.floor(px + 0.5), np.floor(py + 0.5)

    # cells per pattern period: one while a cell can carry a line, otherwise a
    # whole number of them, so the pattern stays exactly periodic on the source
    # grid and cannot beat against it
    N = np.maximum(np.ceil(p["lp_min_pitch"] * d - 1e-4), 1.0)
    f = d / N

    amp = np.clip(p["lp_grid"] * 2.0
                  * np.array([p["lp_balance"], 1.0 - p["lp_balance"]]), 0.0, 1.0)
    # eased back as the period spans more cells; see the shader header
    amp = amp * nyquist_fade(f) * (2.0 / (N + 1.0))
    phase = 0.5 * f
    hh = 0.4995 * f

    def axis(t, B, i):
        alo = aperture_sine(t - hh[i], amp[i], phase[i])
        ahi = aperture_sine(t + hh[i], amp[i], phase[i])
        I = np.maximum(ahi - alo, 1e-6)
        g = I / (2.0 * hh[i] * (1.0 + amp[i]))
        Bt = B / N[i]
        AB = Bt - amp[i] * np.sin(TAU * (Bt - phase[i])) / TAU
        return g, np.clip((AB - alo) / I, 0.0, 1.0)

    gx, wx = axis(px / N[0], Bx, 0)
    gy, wy = axis(py / N[1], By, 1)
    gain = gy[:, None] * gx[None, :]

    ix_lo = np.clip(Bx.astype(int) - 1, 0, tex_w - 1)
    ix_hi = np.clip(Bx.astype(int), 0, tex_w - 1)
    iy_lo = np.clip(By.astype(int) - 1, 0, tex_h - 1)
    iy_hi = np.clip(By.astype(int), 0, tex_h - 1)

    a = src[np.ix_(iy_lo, ix_lo)]
    b = src[np.ix_(iy_lo, ix_hi)]
    c = src[np.ix_(iy_hi, ix_lo)]
    e = src[np.ix_(iy_hi, ix_hi)]
    if abs(p["lp_gamma"] - 1.0) > 0.001:
        g = p["lp_gamma"]
        a, b, c, e = (np.power(np.maximum(x, 1e-8), g) for x in (a, b, c, e))

    WX, WY = wx[None, :, None], wy[:, None, None]
    inner_hi = e + (c - e) * WX
    inner_lo = b + (a - b) * WX
    color = inner_hi + (inner_lo - inner_hi) * WY

    stripe = np.ones((out_h, out_w, 3))
    if p["lp_subpixels"] > 0.0:
        sinc = box_sinc(f[0])
        ac = p["lp_subpixels"] * sinc * nyquist_fade(f[0])
        tx = px / N[0]
        arg = TAU * (tx[:, None] - phase[0] - 1.0 / 6.0
                     - np.array([0.0, 1.0 / 3.0])[None, :])
        rg = 1.0 + ac * np.cos(arg)
        s = np.concatenate([rg, 3.0 - rg[:, :1] - rg[:, 1:2]], axis=1)

        M = amp[0] * sinc
        # phase cancels: the stripe argument already carries it and the mesh
        # trough sits at it
        corr = 1.0 - 0.5 * M * ac * np.cos(
            TAU * (np.array([0.0, 1.0 / 3.0, 2.0 / 3.0]) + 1.0 / 6.0))
        # square-rooted: sqrt() below halves the deviation, so the
        # correction has to be halved with it
        s = s / np.sqrt(np.maximum(corr, 1e-3))[None, :]

        if p["lp_layout"] >= 0.5:
            s = s[:, ::-1]
        stripe = np.repeat(s[None, :, :], out_h, axis=0)

    m = np.sqrt(np.maximum(stripe * (gain * p["lp_brightness"])[..., None], 0.0))
    out = np.clip(color * m, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out
