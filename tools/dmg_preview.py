#!/usr/bin/env python3
"""Offline model of dmg-perfect.

Independent numpy reimplementation of the fragment shader, so gl_check.py can
diff the real shipped .glsl running on a GPU against it. An error has to be made
identically in both to slip through.

The four-tap scaler comes from lcd_preview.area_average, which is already
cross-verified on the GPU against pixel-perfect.glsl and shared by every shader
here. Everything DMG-specific - the gap floor, the dot coverage, the grid mix -
is written fresh, because that is the part with no second implementation yet.
"""

import numpy as np

from lcd_preview import area_average

# The reference's own settings for the geometry, and neutral for the tone.
# dmg_dot_matrix is already right at a whole scale factor, so matching it there
# is a constraint rather than a goal, and matching it exactly is only possible
# from the same starting point:
#
#   dp_grid 0.30 is dmg_edge_alpha, dp_level 1.00 is dmg_grid_lightness, and
#   dp_gap 0.20 is the 1px line the reference draws at 5x, expressed as the
#   share of a cell that it is.
#
# The two tone parameters depart, and they depart together. The reference pairs
# a 1.20 lift with a 1.40 gamma, which is one contrast curve in two halves, and
# both halves are non-linearities after the blend:
#
#   - gamma 1.40 measures 0.86 beat against 0.12 at 1.00, on a 1px checkerboard
#     at 160x144 -> 1024x768, which is the fault AGENTS.md records for a curve
#     applied after a blend.
#   - a 1.20 gain then clips, because unlike every other shader here this one
#     does not darken what it draws on. lcd-perfect and crt-perfect sit at 82%
#     and 83% of white *with* their lift, so theirs restores what their pattern
#     removed; a DMG grid is invisible on white and this sits at 100%, so a lift
#     has nothing to restore and only meets the clamp. Measured 2.06 beat, on a
#     source that reaches white; a Game Boy palette peaks well below it, so on
#     the content this shader is for a 1.20 lift costs nothing.
#
# So both default to neutral. The identity is unaffected: it holds wherever the
# two shaders are set the same, at any gamma or gain, and tools/grid.py gates it
# at 3x, 4x and 5x with the reference's own 1.20 and 1.40 on both sides.
DEFAULTS_DMG = dict(
    dp_grid=0.30,
    dp_gap=0.20,
    dp_level=1.00,
    dp_brightness=1.00,
    dp_gamma=1.00,
)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def dot_integral(x, w):
    """Antiderivative of the dot profile: 1 across w of each cell, 0 after it.

    Differencing it over an output pixel's footprint gives that pixel's exact dot
    coverage. Peak-normalised - it tops out at 1, unlike lcd_preview's aperture,
    which is normalised to a mean of 1 and peaks near 3.
    """
    n = np.floor(x)
    return n * w + np.clip(x - n, 0.0, w)


def gap_effective(gap, sc):
    """The gap actually drawn, as a share of a cell, for a scale of sc.

    Never thinner than one output pixel, and never thinner than two at a
    fractional scale - a line under two pixels has no guaranteed solid core, so
    how its ink spreads shifts cell to cell. The second pixel is only taken while
    the cell can afford it: it costs 1/sc of a cell, already 40% at five output
    pixels per cell.

    The whole-scale test is a distance to the nearest integer, never an equality.
    """
    if gap <= 0.0:
        return 0.0
    offs = abs(sc - np.floor(sc + 0.5))
    room = np.clip(sc - 4.0, 0.0, 1.0)
    minpx = 1.0 + np.clip(offs / 0.25, 0.0, 1.0) * room
    return max(gap, minpx / sc * smoothstep(0.0, 0.01, gap))


def render_dmg(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v1.glsl."""
    p = dict(DEFAULTS_DMG, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]

    col, px, py, dx, dy, _ = area_average(src, out_w, out_h)
    col = col * p["dp_brightness"]

    hx = max(0.4995 * dx, 1e-6)
    hy = max(0.4995 * dy, 1e-6)
    litx = max(1.0 - gap_effective(p["dp_gap"], out_w / max(in_w, 1.0)), 1e-3)
    lity = max(1.0 - gap_effective(p["dp_gap"], out_h / max(in_h, 1.0)), 1e-3)

    covx = (dot_integral(px + hx, litx) - dot_integral(px - hx, litx)) / (2 * hx)
    covy = (dot_integral(py + hy, lity) - dot_integral(py - hy, lity)) / (2 * hy)
    # below two output pixels per cell the pattern folds, so it fades to zero at
    # two rather than at one; the window clears a whole 3x with room to spare
    covx = 1.0 + (covx - 1.0) * smoothstep(2.0, 2.9, out_w / max(in_w, 1.0))
    covy = 1.0 + (covy - 1.0) * smoothstep(2.0, 2.9, out_h / max(in_h, 1.0))
    dot2d = covy[:, None] * covx[None, :]

    m = (1.0 + (dot2d - 1.0) * p["dp_grid"])[..., None]
    col = p["dp_level"] + (col - p["dp_level"]) * m

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])

    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


# v2 departs from v1 in three ways, all of them consequences of one finding:
# drawing the matrix at a whole scale factor and then scaling that up is not
# the same thing as drawing it directly at a fractional scale, and the two-pass
# arrangement is the one that holds together. Both passes are linear, so the
# composite has a closed form and can be evaluated in one pass - see
# tools/twopass.py, which builds the pipeline literally and gates the match.
#
#   - the grid line is dp_gap pixels at the whole scale that FITS, not a fixed
#     share of a cell, so it stays about one output pixel wide everywhere
#   - the blend needs two sets of weights, area and aperture, because the grid
#     owes mean(source * dot) and the area mean alone does not supply it
#   - dp_level is gone: this is a DMG shader and a DMG's substrate is its
#     lightest state, so the gap colour is not a choice
DEFAULTS_DMG_V2 = dict(
    dp_grid=0.30,
    dp_gap=1.00,
    dp_shadow=0.00,
    dp_shadow_offset=1.50,
    dp_brightness=1.00,
    dp_gamma=1.00,
)

DMG_SUBSTRATE = 1.0


def fit_scale(in_w, in_h, out_w, out_h):
    """The largest whole scale that fits: 5 at 1024x768, 3 at 640x480.

    The nudge is the recorded trap - floor() on a division result can land a few
    ULP low, and reading 4 instead of 5 at exactly 5.0 changes the answer.
    """
    return max(np.floor(min(out_w / in_w, out_h / in_h) + 1e-3), 1.0)


def render_dmg_v2(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v2.glsl."""
    p = dict(DEFAULTS_DMG_V2, **(p or {}))
    s = src_u8.astype(np.float64) / 255.0
    in_h, in_w = s.shape[:2]

    px = ((np.arange(out_w) + 0.5) / out_w) * in_w
    py = ((np.arange(out_h) + 0.5) / out_h) * in_h
    hx = max(0.4995 * in_w / out_w, 1e-6)
    hy = max(0.4995 * in_h / out_h, 1e-6)
    Bx = np.floor(px + 0.5)
    By = np.floor(py + 0.5)

    scx, scy = out_w / max(in_w, 1.0), out_h / max(in_h, 1.0)
    N = fit_scale(in_w, in_h, out_w, out_h)
    lit = np.clip(1.0 - p["dp_gap"] / N, 1e-3, 1.0)

    Alox, Ahix = dot_integral(px - hx, lit), dot_integral(px + hx, lit)
    Aloy, Ahiy = dot_integral(py - hy, lit), dot_integral(py + hy, lit)
    Ix = np.maximum(Ahix - Alox, 1e-6)
    Iy = np.maximum(Ahiy - Aloy, 1e-6)

    covx_raw, covy_raw = Ix / (2 * hx), Iy / (2 * hy)

    wxA = np.clip((Bx - px + hx) / (2 * hx), 0.0, 1.0)
    wyA = np.clip((By - py + hy) / (2 * hy), 0.0, 1.0)
    # where an output pixel lands wholly in a gap there is no aperture to weight
    # by and this is 0/0, so it falls back to the area weights; the value is
    # otherwise arbitrary and float32 need not pick what float64 picks
    kx, ky = smoothstep(0.0, 0.01, covx_raw), smoothstep(0.0, 0.01, covy_raw)
    wxL = wxA + (np.clip((Bx * lit - Alox) / Ix, 0.0, 1.0) - wxA) * kx
    wyL = wyA + (np.clip((By * lit - Aloy) / Iy, 0.0, 1.0) - wyA) * ky

    fx, fy = smoothstep(2.0, 2.9, scx), smoothstep(2.0, 2.9, scy)
    covx = 1.0 + (covx_raw - 1.0) * fx
    covy = 1.0 + (covy_raw - 1.0) * fy
    dot2d = covy[:, None] * covx[None, :]

    ixl = np.clip(Bx.astype(int) - 1, 0, in_w - 1)
    ixh = np.clip(Bx.astype(int), 0, in_w - 1)
    iyl = np.clip(By.astype(int) - 1, 0, in_h - 1)
    iyh = np.clip(By.astype(int), 0, in_h - 1)
    t00 = s[np.ix_(iyl, ixl)]; t10 = s[np.ix_(iyl, ixh)]
    t01 = s[np.ix_(iyh, ixl)]; t11 = s[np.ix_(iyh, ixh)]

    def blend(wx, wy):
        WX = wx[None, :, None]; WY = wy[:, None, None]
        hi = t11 + (t01 - t11) * WX
        lo = t10 + (t00 - t10) * WX
        return hi + (lo - hi) * WY

    area = blend(wxA, wyA) * p["dp_brightness"]
    dotm = blend(wxL, wyL) * p["dp_brightness"]

    substrate = np.full((out_h, out_w), DMG_SUBSTRATE)
    if p["dp_shadow"] > 0.0:
        offx, offy = p["dp_shadow_offset"] / scx, p["dp_shadow_offset"] / scy
        Sx = np.maximum(dot_integral(px - offx + hx, lit)
                        - dot_integral(px - offx - hx, lit), 0.0) / (2 * hx)
        Sy = np.maximum(dot_integral(py - offy + hy, lit)
                        - dot_integral(py - offy - hy, lit), 0.0) / (2 * hy)
        Sx = 1.0 + (Sx - 1.0) * fx
        Sy = 1.0 + (Sy - 1.0) * fy
        lobe = np.maximum(Sy[:, None] * Sx[None, :] - dot2d, 0.0)
        # from the area mean, not the aperture mean: this term is not
        # multiplied by the coverage, so it cannot use a 0/0 value
        caster = np.clip(1.0 - area @ np.array([0.299, 0.587, 0.114]), 0.0, 1.0)
        substrate = substrate - p["dp_shadow"] * lobe * caster

    D = dot2d[..., None]
    col = area + (substrate[..., None] + (dotm - substrate[..., None]) * D
                  - area) * p["dp_grid"]

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out
