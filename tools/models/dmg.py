#!/usr/bin/env python3
"""Offline model of dmg-perfect.

Independent numpy reimplementation of the fragment shader, so gl_check.py can
diff the real shipped .glsl running on a GPU against it. An error has to be made
identically in both to slip through.

The four-tap scaler comes from models.lcd.area_average, which is already
cross-verified on the GPU against pixel-perfect.glsl and shared by every shader
here. Everything DMG-specific - the gap floor, the dot coverage, the grid mix -
is written fresh, because that is the part with no second implementation yet.
"""

import numpy as np

from models.common import smoothstep

from models.lcd import area_average

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


def dot_integral(x, w):
    """Antiderivative of the dot profile: 1 across w of each cell, 0 after it.

    Differencing it over an output pixel's footprint gives that pixel's exact dot
    coverage. Peak-normalised - it tops out at 1, unlike the LCD aperture,
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


# v3 fixes one term: what the shadow measures a dot's opacity against.
#
# v2 used clamp(1 - luma, 0, 1), which is the right formula with the paper level
# hardcoded to white. No Game Boy palette is anywhere near white, so every shade
# was judged most of the way opaque and the shadow became a flat dimming of the
# whole picture - the undriven shade, which is three quarters of a typical
# frame, cast 55% of a full shadow.
#
# Opacity is transmittance: a reflective panel shows paper * transmittance, so a
# dot blocks 1 - luma/paper. The divisor is the palette's lightest shade, which
# is not knowable in advance - Gambatte's DMG measures 0.401, mGBA's DMG green
# 0.560, a Pocket palette 0.664 to 0.767, greyscale 1.000 - so it is taken as
# the brightest of the four taps, floored. See PAPER_FLOOR.
DEFAULTS_DMG_V3 = dict(DEFAULTS_DMG_V2)

# Must match PAPER_FLOOR in dmg-perfect-v3.glsl. It has to sit below the darkest
# paper anyone ships, because a floor above it dims every undriven pixel, which
# is the fault being fixed: 0.45 costs Gambatte's default palette 10.8%.
PAPER_FLOOR = 0.35


def render_dmg_v3(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v3.glsl."""
    p = dict(DEFAULTS_DMG_V3, **(p or {}))
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
        offx = p["dp_shadow_offset"] / scx
        offy = p["dp_shadow_offset"] / scy
        Sx = np.maximum(dot_integral(px - offx + hx, lit)
                        - dot_integral(px - offx - hx, lit), 0.0) / (2 * hx)
        Sy = np.maximum(dot_integral(py - offy + hy, lit)
                        - dot_integral(py - offy - hy, lit), 0.0) / (2 * hy)
        Sx = 1.0 + (Sx - 1.0) * fx
        Sy = 1.0 + (Sy - 1.0) * fy
        lobe = np.maximum(Sy[:, None] * Sx[None, :] - dot2d, 0.0)
        L = np.array([0.299, 0.587, 0.114])
        # gated on the blend weight, so an exact-boundary flip of B cannot swap
        # which neighbour the maximum sees - see the shader for why
        WX = wxA[None, :]; WY = wyA[:, None]
        ks = [WX * WY, (1 - WX) * WY, WX * (1 - WY), (1 - WX) * (1 - WY)]
        paper = np.maximum.reduce(
            [(t @ L) * smoothstep(0.0, 0.02, k)
             for t, k in zip((t00, t10, t01, t11), ks)] + [np.full((out_h, out_w),
                                                                   PAPER_FLOOR)])
        caster = np.clip(1.0 - (area @ L) / paper, 0.0, 1.0)
        substrate = substrate - p["dp_shadow"] * lobe * caster

    D = dot2d[..., None]
    col = area + (substrate[..., None] + (dotm - substrate[..., None]) * D
                  - area) * p["dp_grid"]

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


# v4 changes only the shadow, in two ways the user asked for and one that
# follows from them.
#
#   - the offsets are in SOURCE pixels and separate per axis. A shadow is thrown
#     by a dot, so it belongs a fraction of a cell away and should look the same
#     at every scale; v3 measured it in output pixels, so at 5x a "1.5" was
#     three tenths of a cell and at 3x it was half of one.
#   - it goes UNDER everything, as one multiply on the finished colour. v3
#     subtracted it from the gap colour alone, and the gap is one output pixel
#     wide, so the shadow could only ever darken the grid lines - which reads as
#     a mesh drawn on top rather than as anything lying underneath. On a
#     reflective panel the light crosses the crystal, reflects off the substrate
#     and crosses back, so a neighbour shading the substrate scales whatever
#     that cell finally shows: an undriven cell is transparent and the shadow
#     reads through it, a driven one is already dark and hides it.
#   - at a cell or more away the casting dot is outside the four taps the
#     scaler holds, so it needs its own sample. One nearest tap at the cell
#     centre: opacity is a per-cell quantity, and the displaced aperture
#     supplies the edges.
DEFAULTS_DMG_V4 = dict(
    dp_grid=0.30,
    dp_gap=1.00,
    dp_shadow=0.00,
    dp_shadow_x=0.50,
    dp_shadow_y=1.50,
    dp_brightness=1.00,
    dp_gamma=1.00,
)


def render_dmg_v4(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v4.glsl."""
    p = dict(DEFAULTS_DMG_V4, **(p or {}))
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

    D = dot2d[..., None]
    col = area + (DMG_SUBSTRATE + (dotm - DMG_SUBSTRATE) * D - area) * p["dp_grid"]

    if p["dp_shadow"] > 0.0:
        qx = px - p["dp_shadow_x"]
        qy = py - p["dp_shadow_y"]
        Sx = np.maximum(dot_integral(qx + hx, lit)
                        - dot_integral(qx - hx, lit), 0.0) / (2 * hx)
        Sy = np.maximum(dot_integral(qy + hy, lit)
                        - dot_integral(qy - hy, lit), 0.0) / (2 * hy)
        Sx = 1.0 + (Sx - 1.0) * fx
        Sy = 1.0 + (Sy - 1.0) * fy

        # the casting cell, sampled nearest, with CLAMP_TO_EDGE. The epsilon is
        # the recorded floor() trap - q sits exactly on a cell boundary for many
        # pixels at once at a whole scale factor, and a few ULP pick a different
        # cell across what may be a hard edge in the content.
        cx = np.clip(np.floor(qx + 1e-3).astype(int), 0, in_w - 1)
        cy = np.clip(np.floor(qy + 1e-3).astype(int), 0, in_h - 1)
        caster = s[np.ix_(cy, cx)]

        L = np.array([0.299, 0.587, 0.114])
        WX = wxA[None, :]; WY = wyA[:, None]
        ks = [WX * WY, (1 - WX) * WY, WX * (1 - WY), (1 - WX) * (1 - WY)]
        paper = np.maximum.reduce(
            [(t @ L) * smoothstep(0.0, 0.02, k)
             for t, k in zip((t00, t10, t01, t11), ks)]
            + [np.full((out_h, out_w), PAPER_FLOOR)])
        opacity = np.clip(1.0 - (caster @ L) / paper, 0.0, 1.0)
        shade = p["dp_shadow"] * opacity * (Sy[:, None] * Sx[None, :])
        col = col * (1.0 - shade)[..., None]

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


# v5 fixes the shadow's placement and softens it, and adds a colour trim.
#
#   - the offset is no longer a control. 0.60 right and 0.85 down, in source
#     pixels, is the placement that reads as a panel lit from above.
#   - the shadow is box-blurred, for nothing. Its coverage is already the exact
#     mean of the aperture over the output pixel's footprint, so widening that
#     footprint convolves it with a wider box. Verified against an explicit
#     convolution of the hard pulse train, not assumed.
#   - dp_red / dp_green / dp_blue trim the balance. A gain is affine, so putting
#     it after the blend is identical to putting it on the taps and a quarter of
#     the cost; it goes on the finished colour so the substrate is tinted too.
#     Behind a uniform branch, so neutral is free - measured, the everything-off
#     path is 291 ops, the same as v4's.
SHADOW_OFFSET = (0.50, 0.85)
SHADOW_BLUR = 0.20

DEFAULTS_DMG_V5 = dict(
    dp_grid=0.30,
    dp_gap=1.00,
    dp_shadow=0.00,
    dp_red=1.00,
    dp_green=1.00,
    dp_blue=1.00,
    dp_brightness=1.00,
    dp_gamma=1.00,
)


def render_dmg_v5(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v5.glsl."""
    p = dict(DEFAULTS_DMG_V5, **(p or {}))
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

    D = dot2d[..., None]
    col = area + (DMG_SUBSTRATE + (dotm - DMG_SUBSTRATE) * D - area) * p["dp_grid"]

    if p["dp_shadow"] > 0.0:
        qx = px - SHADOW_OFFSET[0]
        qy = py - SHADOW_OFFSET[1]
        hsx, hsy = hx + SHADOW_BLUR, hy + SHADOW_BLUR
        Sx = np.maximum(dot_integral(qx + hsx, lit)
                        - dot_integral(qx - hsx, lit), 0.0) / (2 * hsx)
        Sy = np.maximum(dot_integral(qy + hsy, lit)
                        - dot_integral(qy - hsy, lit), 0.0) / (2 * hsy)
        Sx = 1.0 + (Sx - 1.0) * fx
        Sy = 1.0 + (Sy - 1.0) * fy

        cx = np.clip(np.floor(qx + 1e-3).astype(int), 0, in_w - 1)
        cy = np.clip(np.floor(qy + 1e-3).astype(int), 0, in_h - 1)
        caster = s[np.ix_(cy, cx)]

        L = np.array([0.299, 0.587, 0.114])
        WX = wxA[None, :]; WY = wyA[:, None]
        ks = [WX * WY, (1 - WX) * WY, WX * (1 - WY), (1 - WX) * (1 - WY)]
        paper = np.maximum.reduce(
            [(t @ L) * smoothstep(0.0, 0.02, k)
             for t, k in zip((t00, t10, t01, t11), ks)]
            + [np.full((out_h, out_w), PAPER_FLOOR)])
        opacity = np.clip(1.0 - (caster @ L) / paper, 0.0, 1.0)
        shade = p["dp_shadow"] * opacity * (Sy[:, None] * Sx[None, :])
        col = col * (1.0 - shade)[..., None]

    trim = (abs(p["dp_red"] - 1.0) + abs(p["dp_green"] - 1.0)
            + abs(p["dp_blue"] - 1.0))
    if trim > 0.001:
        col = col * np.array([p["dp_red"], p["dp_green"], p["dp_blue"]])

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


# v7 keeps v6's blur exactly and pays less for it.
#
# The blur itself is the point of both: the shadow's edge comes from a per-cell
# opacity, so sampling that nearest leaves a hard cell-sized step no matter what
# is done to the aperture - v5 widened the aperture's box filter alone and the
# outer edge stayed one output pixel wide, which is no blur at all. Reading the
# four surrounding cells and interpolating turns the step into a ramp across a
# whole cell: measured on a block of dark cells, 1 output pixel becomes 20 at
# 24x. v6 made the ramp width a parameter; full softness was the only setting
# worth having, so here it is a constant and the weights are the plain
# fractional position.
#
# The saving is in what that lets go of. paper now comes from the four cells
# just read, which deletes v6's gated maximum over the *scaler's* taps - that
# existed because the tap pair flips at an exact boundary and a bare max would
# swap in a different neighbour, and it cost four smoothsteps. Measured on this
# GPU: v6 142.6% of pixellate, v7 126.8%, and v5 - which had no real blur -
# 131.5%. Removing that block bought more than four extra texture fetches cost.
#
# A three-tap triangle filter was tried, since that is the true minimum for a
# continuous 2D interpolation. It measured 129.6%: the branchless corner
# selection costs back more than the fetch saves. Do not re-try it.
SHADOW_APERTURE_SOFT = 0.5

DEFAULTS_DMG_V7 = dict(DEFAULTS_DMG_V5)


def render_dmg_v7(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v7.glsl."""
    p = dict(DEFAULTS_DMG_V7, **(p or {}))
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

    D = dot2d[..., None]
    col = area + (DMG_SUBSTRATE + (dotm - DMG_SUBSTRATE) * D - area) * p["dp_grid"]

    if p["dp_shadow"] > 0.0:
        qx = px - SHADOW_OFFSET[0]
        qy = py - SHADOW_OFFSET[1]
        hsx = hx + SHADOW_APERTURE_SOFT
        hsy = hy + SHADOW_APERTURE_SOFT
        Sx = np.maximum(dot_integral(qx + hsx, lit)
                        - dot_integral(qx - hsx, lit), 0.0) / (2 * hsx)
        Sy = np.maximum(dot_integral(qy + hsy, lit)
                        - dot_integral(qy - hsy, lit), 0.0) / (2 * hsy)
        Sx = 1.0 + (Sx - 1.0) * fx
        Sy = 1.0 + (Sy - 1.0) * fy

        # the 2x2 of cells around the shifted point, and where in it we sit
        # No epsilon: the pair and the weight must come from the same value,
        # and the interpolated texcoord's float32 error is larger than any
        # epsilon worth adding anyway. Harmless, because the weight is zero
        # exactly where the pair changes - see the shader.
        gx, gy = qx - 0.5, qy - 0.5
        gix, giy = np.floor(gx), np.floor(gy)
        gfx, gfy = gx - gix, gy - giy
        ix0 = np.clip(gix.astype(int), 0, in_w - 1)
        ix1 = np.clip(gix.astype(int) + 1, 0, in_w - 1)
        iy0 = np.clip(giy.astype(int), 0, in_h - 1)
        iy1 = np.clip(giy.astype(int) + 1, 0, in_h - 1)

        L = np.array([0.299, 0.587, 0.114])
        c00 = s[np.ix_(iy0, ix0)] @ L
        c10 = s[np.ix_(iy0, ix1)] @ L
        c01 = s[np.ix_(iy1, ix0)] @ L
        c11 = s[np.ix_(iy1, ix1)] @ L

        WX = gfx[None, :]; WY = gfy[:, None]
        caster_lum = ((c00 + (c10 - c00) * WX)
                      + ((c01 + (c11 - c01) * WX)
                         - (c00 + (c10 - c00) * WX)) * WY)
        # weighted before reducing: a max over a *set* of cells is unstable
        # when floor() can pick a different set - see the shader
        kb = [(1 - WX) * (1 - WY), WX * (1 - WY), (1 - WX) * WY, WX * WY]
        paper = np.maximum.reduce(
            [c * smoothstep(0.0, 0.02, k)
             for c, k in zip((c00, c10, c01, c11), kb)]
            + [np.full((out_h, out_w), PAPER_FLOOR)])
        opacity = np.clip(1.0 - caster_lum / paper, 0.0, 1.0)
        shade = p["dp_shadow"] * opacity * (Sy[:, None] * Sx[None, :])
        col = col * (1.0 - shade)[..., None]

    trim = (abs(p["dp_red"] - 1.0) + abs(p["dp_green"] - 1.0)
            + abs(p["dp_blue"] - 1.0))
    if trim > 0.001:
        col = col * np.array([p["dp_red"], p["dp_green"], p["dp_blue"]])

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


# v6 is where the blur was found, and it keeps the softness as a parameter.
#
# v5 widened the box filter on the displaced aperture and called that a blur. It
# is not: that only softens the aperture's own gaps, while the edge of the
# shadow as a whole comes from the per-cell opacity, sampled nearest. Measured
# on a block of dark cells at 24x, v5's outer edge fell from full to nothing in
# one output pixel. Interpolating the opacity between the four surrounding cells
# is what actually softens it - 1 output pixel becomes 8, 14 and 20 at
# dp_shadow_blur 0.30, 0.60 and 1.00.
#
# At 0 the weights collapse to a nearest pick and this is exactly v5, so the
# parameter spans the old look through to fully soft. v7 fixes it at 1.00 and
# spends the saving elsewhere; this version is kept because the sweep is the
# evidence for that choice.
DEFAULTS_DMG_V6 = dict(DEFAULTS_DMG_V5, dp_shadow_blur=0.60)


def render_dmg_v6(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v6.glsl."""
    p = dict(DEFAULTS_DMG_V6, **(p or {}))
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

    D = dot2d[..., None]
    col = area + (DMG_SUBSTRATE + (dotm - DMG_SUBSTRATE) * D - area) * p["dp_grid"]

    if p["dp_shadow"] > 0.0:
        qx = px - SHADOW_OFFSET[0]
        qy = py - SHADOW_OFFSET[1]
        # only half the parameter goes into the aperture's box; the rest sets
        # the width of the opacity ramp below, which is the actual blur
        hsx = hx + p["dp_shadow_blur"] * SHADOW_APERTURE_SOFT
        hsy = hy + p["dp_shadow_blur"] * SHADOW_APERTURE_SOFT
        Sx = np.maximum(dot_integral(qx + hsx, lit)
                        - dot_integral(qx - hsx, lit), 0.0) / (2 * hsx)
        Sy = np.maximum(dot_integral(qy + hsy, lit)
                        - dot_integral(qy - hsy, lit), 0.0) / (2 * hsy)
        Sx = 1.0 + (Sx - 1.0) * fx
        Sy = 1.0 + (Sy - 1.0) * fy

        # No epsilon: the pair and the weight must come from the same value,
        # and the interpolated texcoord's float32 error is larger than any
        # epsilon worth adding anyway. Harmless, because the weight is zero
        # exactly where the pair changes - see the shader.
        gx, gy = qx - 0.5, qy - 0.5
        gix, giy = np.floor(gx), np.floor(gy)
        gfx, gfy = gx - gix, gy - giy
        blur = max(p["dp_shadow_blur"], 1e-4)
        wbx = np.clip((gfx - 0.5) / blur + 0.5, 0.0, 1.0)
        wby = np.clip((gfy - 0.5) / blur + 0.5, 0.0, 1.0)
        ix0 = np.clip(gix.astype(int), 0, in_w - 1)
        ix1 = np.clip(gix.astype(int) + 1, 0, in_w - 1)
        iy0 = np.clip(giy.astype(int), 0, in_h - 1)
        iy1 = np.clip(giy.astype(int) + 1, 0, in_h - 1)

        L = np.array([0.299, 0.587, 0.114])
        c00 = s[np.ix_(iy0, ix0)] @ L
        c10 = s[np.ix_(iy0, ix1)] @ L
        c01 = s[np.ix_(iy1, ix0)] @ L
        c11 = s[np.ix_(iy1, ix1)] @ L
        WX = wbx[None, :]; WY = wby[:, None]
        lo_ = c00 + (c10 - c00) * WX
        hi_ = c01 + (c11 - c01) * WX
        caster_lum = lo_ + (hi_ - lo_) * WY

        # v6 still takes paper from the scaler's own taps, gated by their blend
        # weights so an exact-boundary flip cannot swap in a different
        # neighbour. v7 drops all of that by reading it from the four cells the
        # shadow already has.
        WXa = wxA[None, :]; WYa = wyA[:, None]
        ks = [WXa * WYa, (1 - WXa) * WYa, WXa * (1 - WYa), (1 - WXa) * (1 - WYa)]
        paper = np.maximum.reduce(
            [(t @ L) * smoothstep(0.0, 0.02, k)
             for t, k in zip((t00, t10, t01, t11), ks)]
            + [np.full((out_h, out_w), PAPER_FLOOR)])
        opacity = np.clip(1.0 - caster_lum / paper, 0.0, 1.0)
        shade = p["dp_shadow"] * opacity * (Sy[:, None] * Sx[None, :])
        col = col * (1.0 - shade)[..., None]

    trim = (abs(p["dp_red"] - 1.0) + abs(p["dp_green"] - 1.0)
            + abs(p["dp_blue"] - 1.0))
    if trim > 0.001:
        col = col * np.array([p["dp_red"], p["dp_green"], p["dp_blue"]])

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


# v8 fixes v7's blur artifact and adds the contrast wheel.
#
# The blur itself was never the problem. At dp_shadow_blur = 1.0 v6's weights
# reduce to clamp(gf, 0, 1) == gf and its footprint to h + APERTURE_SOFT, which
# is exactly what v7 hardcodes - so the two are algebraically identical in both
# the aperture and the interpolation, and every difference between them is the
# `paper` divisor.
#
# v6 reduced over the scaler's four taps and v7 over the four shadow cells, and
# both had to gate each term by its blend weight first so that floor() picking a
# different *set* at a boundary could not swap in a different neighbour. v7's
# gate opens over a weight range of 0.02 while its bilinear weights sweep the
# full 0..1 once per cell, so paper stepped between the floor and the paper
# level along a contour inside every cell: 22/255 against v6, reading as a hard
# dark bar down the edge of every dark region with the gradient gone.
#
# v8 takes paper from the luma of the area blend instead. Continuous in position
# by construction, stable at the boundary for the same reason the scaler is,
# one dot product and one max, and bit-identical to v6 at a whole scale factor -
# where the blend returns the source texel exactly.
DEFAULTS_DMG_V8 = dict(DEFAULTS_DMG_V7, dp_contrast=1.0)


def render_dmg_v8(src_u8, out_w, out_h, p=None, quantise=True):
    """Mirrors dmg-perfect-v8.glsl."""
    p = dict(DEFAULTS_DMG_V8, **(p or {}))
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

    # area stays raw - the shadow's opacity is a ratio of two source levels, so
    # an output gain has to cancel out of it rather than change how much light a
    # dot appears to block.
    area = blend(wxA, wyA)
    dotm = blend(wxL, wyL)

    D = dot2d[..., None]
    ab = area * p["dp_brightness"]
    db = dotm * p["dp_brightness"]
    col = ab + (DMG_SUBSTRATE + (db - DMG_SUBSTRATE) * D - ab) * p["dp_grid"]

    # The contrast wheel: an affine map pivoting on the substrate, so the gaps
    # are its fixed point and stay exactly where they are. Folded to a gain and
    # an offset rather than written as a mix, so 1.00 is col*1.0 + 0.0 and is
    # bit-exact.
    # Unbranched, matching the shader: a uniform branch round it measured
    # 105.7% of the yardstick against 105.5% unbranched, so it bought nothing,
    # and the fold is what makes 1.00 exact rather than the branch.
    col = col * p["dp_contrast"] + (1.0 - p["dp_contrast"]) * DMG_SUBSTRATE

    if p["dp_shadow"] > 0.0:
        qx = px - SHADOW_OFFSET[0]
        qy = py - SHADOW_OFFSET[1]
        hsx, hsy = hx + SHADOW_APERTURE_SOFT, hy + SHADOW_APERTURE_SOFT
        Sx = np.maximum(dot_integral(qx + hsx, lit)
                        - dot_integral(qx - hsx, lit), 0.0) / (2 * hsx)
        Sy = np.maximum(dot_integral(qy + hsy, lit)
                        - dot_integral(qy - hsy, lit), 0.0) / (2 * hsy)
        Sx = 1.0 + (Sx - 1.0) * fx
        Sy = 1.0 + (Sy - 1.0) * fy

        # the 2x2 of cells around the shifted point, and where in it we sit.
        # No epsilon: the pair and the weight must come from the same value, and
        # the interpolated texcoord's float32 error is larger than any epsilon
        # worth adding anyway. Harmless, because the weight is zero exactly
        # where the pair changes - see the shader.
        gx, gy = qx - 0.5, qy - 0.5
        gix, giy = np.floor(gx), np.floor(gy)
        gfx, gfy = gx - gix, gy - giy
        ix0 = np.clip(gix.astype(int), 0, in_w - 1)
        ix1 = np.clip(gix.astype(int) + 1, 0, in_w - 1)
        iy0 = np.clip(giy.astype(int), 0, in_h - 1)
        iy1 = np.clip(giy.astype(int) + 1, 0, in_h - 1)

        L = np.array([0.299, 0.587, 0.114])
        c00 = s[np.ix_(iy0, ix0)] @ L
        c10 = s[np.ix_(iy0, ix1)] @ L
        c01 = s[np.ix_(iy1, ix0)] @ L
        c11 = s[np.ix_(iy1, ix1)] @ L

        WX = gfx[None, :]; WY = gfy[:, None]
        caster_lum = ((c00 + (c10 - c00) * WX)
                      + ((c01 + (c11 - c01) * WX)
                         - (c00 + (c10 - c00) * WX)) * WY)

        # No reduction over the taps at all - that is the whole of the fix.
        # The blend is continuous in position, which is what a divisor needs if
        # it is not to print its own structure into the shadow, and it is stable
        # at the floor() boundary for the same reason the scaler is.
        paper = np.maximum(area @ L, PAPER_FLOOR)
        opacity = np.clip(1.0 - caster_lum / paper, 0.0, 1.0)
        shade = p["dp_shadow"] * opacity * (Sy[:, None] * Sx[None, :])
        col = col * (1.0 - shade)[..., None]

    trim = (abs(p["dp_red"] - 1.0) + abs(p["dp_green"] - 1.0)
            + abs(p["dp_blue"] - 1.0))
    if trim > 0.001:
        col = col * np.array([p["dp_red"], p["dp_green"], p["dp_blue"]])

    if abs(p["dp_gamma"] - 1.0) > 0.001:
        col = np.power(np.maximum(col, 1e-8), p["dp_gamma"])
    out = np.clip(col, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out
