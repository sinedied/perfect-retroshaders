#!/usr/bin/env python3
"""Measure moire - the low-frequency beat a shader paints onto flat content.

A shader that modulates the image with a pattern locked to the source grid has a
problem the source itself does not: at a non-integer scale a source pixel covers
three or four output pixels, so the count of partial-coverage pixels varies from
block to block. Any non-linearity applied across the scaler's blend gives those
pixels a coverage-dependent shift, and that shift beats against the pixel grid at
a frequency far below the pattern's own. That beat is what the eye sees as moire.

METHOD

Render a 1px checkerboard - the worst case, maximum energy at the pixel grid -
and look at its spectrum. Two frequencies in that image are legitimate and must
not be counted:

  - the content. A 1px checkerboard is a single pair of impulses at half a cycle
    per source pixel on each axis, and nothing below.
  - the pattern. Anything locked to the source grid has its fundamental at one
    cycle per source pixel, with harmonics above.

So everything strictly slower than half a cycle per source pixel is neither, and
whatever is found there was manufactured by the shader. That is the beat. The
figure reported is its RMS, in 8-bit levels, with DC excluded.

Getting this band wrong is the documented way to produce confident nonsense: a
fixed "periods 6-64px are moire" window counts the pattern itself the moment its
pitch enters the window, and a low-pass at the pattern's repeat length removes
the beat along with it, because at a rational scale factor the whole image is
periodic at that length and nothing survives. Both were tried here. The band is
derived from the source and output sizes, never assumed.

Anything above about 0.4 is visible. That threshold is the ~0.2 recorded in
AGENTS.md carried across the scale factor between the two definitions, which the
self-test below measures rather than assumes.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python beat.py
"""

import math
import sys

import numpy as np

from crt_preview import render_crt, render_crt_v5
from lcd_preview import DEFAULTS_LCD, render_lcd

VISIBLE = 0.4

# Largest max/min of pattern strength across a frame before the pattern is
# judged to be collapsing somewhere. A flat render is 1.00 by construction; the
# curved shader measures 1.15 at its strongest setting, and a warped pattern
# with no local band-limiting runs away well past 2.
UNIFORM = 1.5

# The smallest pitch any shader here puts a pattern at, in output pixels. Both
# crt-perfect and lcd-perfect v3 lock to this when the source cells get too
# small to carry the pattern, so it is the floor of what counts as signal.
MIN_PITCH = 3.0


def checkerboard(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    return (((yy + xx) % 2) * 255).astype(np.uint8)[..., None].repeat(3, axis=2)


def _band(out_w, out_h, src_w, src_h, pattern, fx, fy):
    """The cutoff mask, shared by the flat and the curved metric."""
    px_f, py_f = pattern if pattern else (src_w / out_w, src_h / out_h)
    cx = min(0.5 * src_w / out_w, 0.85 * px_f) * 0.999
    cy = min(0.5 * src_h / out_h, 0.85 * py_f) * 0.999
    band = (fy[:, None] < cy) & (fx[None, :] < cx)
    band[0, 0] = False  # DC is the image's mean level, not a beat
    return band


def _supersampled(src_u8, out_w, out_h, curvature, ss=4):
    """Ground truth for the warped scale: ss x ss rays per output pixel through
    the warp, nearest source texel each, averaged. No footprint model is used -
    the mean of point samples over the pixel is the answer a footprint model is
    trying to approximate."""
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]
    off = (np.arange(ss) + 0.5) / ss
    acc = np.zeros((out_h, out_w, 3))
    ys, xs = np.mgrid[0:out_h, 0:out_w]
    for dy in off:
        for dx in off:
            u = (xs + dx) / out_w * 2.0 - 1.0
            v = (ys + dy) / out_h * 2.0 - 1.0
            s = 1.0 + curvature * (u * u + v * v)
            su, sv = u * s * 0.5 + 0.5, v * s * 0.5 + 0.5
            ix = np.clip((su * in_w).astype(int), 0, in_w - 1)
            iy = np.clip((sv * in_h).astype(int), 0, in_h - 1)
            inside = (su >= 0) & (su <= 1) & (sv >= 0) & (sv <= 1)
            acc += src[iy, ix] * inside[..., None]
    return acc / (ss * ss)


def curvature_residual(shaded, src_u8, curvature, src_w, src_h, pattern,
                       tile=128, ss=(8, 16)):
    """Worst tile-local low-frequency energy in the *residual* against truth.

    Measuring the curved render directly does not work, and the reason is worth
    keeping: barrel distortion varies the local magnification on purpose, so
    block sizes genuinely change across the frame. A band-limited FFT scores
    that intended variation as beat - it reads 4 to 20 where the flat metric
    reads 0.26, and none of it is an artifact. That is the trap the flat metric
    documents wearing a different hat: a band that does not exclude the effect
    under test measures the effect.

    Differencing against a supersampled reference of the same warp cancels the
    intended geometry and the black surround, leaving only what the shader got
    wrong.

    THE REFERENCE IS NOISY AND THE NOISE LOOKS EXACTLY LIKE THE ANSWER. Each ray
    takes one nearest texel, so a reference built from n samples per pixel
    quantises to 1/n and on a 1px checkerboard - maximum contrast between
    neighbours - that quantisation is enormous: 16.2 at 2x2, 8.0 at 4x4, 3.8 at
    8x8, 1.9 at 16x16, 0.9 at 32x32. Halving on every doubling is the signature
    of a 1/ss error and nothing to do with the shader, but any single one of
    those numbers reads as a confident, damning measurement.

    So the error is extrapolated away rather than sampled away: with e = C/ss,
    two references at ss and 2*ss give 2*r(2ss) - r(ss) with the C term removed.
    That reads -0.06 where ss=8 alone reads 3.8, and it is stable across which
    pair is used, which is the check that the model of the error is right.
    """
    lo, hi = ss
    r = []
    for n in (lo, hi):
        truth = _supersampled(src_u8, shaded.shape[1], shaded.shape[0],
                              curvature, n)
        resid = (shaded.astype(np.float64) / 255.0 - truth).mean(axis=2) * 255.0
        r.append(_worst_tile(resid, curvature, src_w, src_h, pattern, tile))
    return max(2.0 * r[1][0] - r[0][0], 0.0), r[1][1]


def _worst_tile(resid, curvature, src_w, src_h, pattern, tile):
    out_h, out_w = resid.shape
    fx = np.abs(np.fft.fftfreq(tile))
    band = _band(out_w, out_h, src_w, src_h, pattern, fx, fx)

    ys, xs = np.mgrid[0:out_h, 0:out_w]
    u = (xs + 0.5) / out_w * 2.0 - 1.0
    v = (ys + 0.5) / out_h * 2.0 - 1.0
    s = 1.0 + curvature * (u * u + v * v)
    su, sv = u * s * 0.5 + 0.5, v * s * 0.5 + 0.5
    lit = (su >= 0.005) & (su <= 0.995) & (sv >= 0.005) & (sv <= 0.995)

    worst, n = 0.0, 0
    for y in range(0, out_h - tile + 1, tile):
        for x in range(0, out_w - tile + 1, tile):
            if not lit[y:y + tile, x:x + tile].all():
                continue
            n += 1
            F = np.fft.fft2(resid[y:y + tile, x:x + tile]) / (tile * tile)
            worst = max(worst, float(np.sqrt((np.abs(F[band]) ** 2).sum())))
    if n == 0:
        raise ValueError(f"no {tile}x{tile} tile fits inside the tube at "
                         f"curvature {curvature}")
    return worst, n


def beat(img, src_w, src_h, pattern=None):
    """RMS of everything slower than the content and the pattern, in 8-bit levels."""
    lum = img.astype(np.float64)
    if lum.ndim == 3:
        lum = lum.mean(axis=2)
    if lum.max() <= 1.0001:
        lum = lum * 255.0
    out_h, out_w = lum.shape

    # forward normalisation, so sum |F|^2 over a band is that band's variance
    F = np.fft.fft2(lum) / lum.size
    fx = np.abs(np.fft.fftfreq(out_w))
    fy = np.abs(np.fft.fftfreq(out_h))

    # The band has to sit below BOTH legitimate patterns in the image.
    #
    #   content   a 1px checkerboard is impulses at half a cycle per source
    #             pixel, and nothing below
    #   shader    wherever the caller says its pattern is, defaulting to one
    #             cycle per source cell
    #
    # The second is the one that bites, and it is why the caller has to say.
    # A pattern that grows its period to keep clear of the pixel grid ends up
    # *below* the content on a dense source - at 480x272 into 640x480 the mesh
    # sits at 0.28 and the content at 0.375 - and a band that only ducks under
    # the content then scores the shader's own grid as moire. Measured that way
    # a correct mesh read 15.4, with every dominant component sitting at exactly
    # its own pitch and no structure in the other axis at all.
    #
    # The 0.85 is a guard, not a fudge. The pattern is not commensurate with the
    # frame, so a rectangular window smears it into neighbouring bins with only
    # 1/offset decay, and an edge sitting on the pattern swallows half its
    # skirt. Windowing the frame was tried and wrecked the self-test; cropping
    # to a whole number of periods just moves the leakage onto the content.
    band = _band(out_w, out_h, src_w, src_h, pattern, fx, fy)
    return float(np.sqrt((np.abs(F[band]) ** 2).sum()))


def measure(render, src_w=320, src_h=240, out_w=1024, out_h=768, pattern=None):
    src = checkerboard(src_w, src_h)
    return beat(render(src, out_w, out_h), src_w, src_h, pattern)


# Which pitch rule each shader follows. Exact filenames, not prefixes: after v3
# was promoted, the canonical shader is "lcd-perfect.glsl" and the superseded
# ones are "lcd-perfect-v1/v2a/v2b.glsl", so any prefix test on "lcd-perfect"
# matches all four and hands the archive a rule it does not use. Nothing fails
# when that happens - the numbers just quietly become wrong. The same fault was
# already here for "crt-perfect", which matched v1 to v3; those predate the
# minimum-pitch regime and track the source like everything else.
WHOLE_CELL_PERIOD = {"lcd-perfect.glsl"}
OUTPUT_LOCKED = {"crt-perfect.glsl", "crt-perfect-v4.glsl", "crt-perfect-v5.glsl"}


def pattern_freq(name, src_w, src_h, out_w, out_h, min_pitch=MIN_PITCH):
    """Where a shader puts its pattern, in cycles per output pixel.

    The band has to duck under this, so it has to be stated per shader rather
    than assumed. Three rules are in play across the family and they do not
    agree, which is exactly why guessing one does not work.
    """
    d = (src_w / out_w, src_h / out_h)
    if name in WHOLE_CELL_PERIOD:
        # the period grows to a whole number of cells, never finer than min_pitch
        n = [max(math.ceil(min_pitch * x - 1e-4), 1) for x in d]
        return (d[0] / n[0], d[1] / n[1])
    if name in OUTPUT_LOCKED:
        # locks to a fixed output-space pitch instead of growing the period
        return (min(d[0], 1.0 / min_pitch), min(d[1], 1.0 / min_pitch))
    # everything else tracks the source at one cycle per cell, always
    return d


# ---------------------------------------------------------------- self-test
#
# Constructions whose beat AGENTS.md already records. They are reproduced here
# from the descriptions in the design-rule table, and the tool is only
# trustworthy if it returns those numbers - a metric that has not been checked
# against a known-good and a known-bad case is how the last three tooling bugs
# produced confident, wrong figures.

def _v5(p=None, **kw):
    return lambda s, w, h: render_crt_v5(s, w, h, p, quantise=False, **kw)


def _post_gamma(g):
    """Output gamma applied after the blend, the way dmg_dot_matrix does it."""
    def r(s, w, h):
        return np.power(np.clip(render_crt_v5(s, w, h, quantise=False), 0.0, 1.0), g)
    return r


def _reinhard(k):
    """A soft shoulder instead of a hard clamp, also after the blend."""
    def r(s, w, h):
        c = render_crt_v5(s, w, h, dict(cp_brightness=k), quantise=False) * k
        return c / (1.0 + c)
    return r


EXPECTED = [
    ("nothing non-linear after the blend",
     _v5(dict(cp_brightness=1.0)), 0.02),
    ("linearise taps, blend, re-encode (v1)",
     lambda s, w, h: render_crt(s, w, h) / 255.0, 3.35),
    ("output gamma 1.4 after the blend", _post_gamma(1.4), 1.53),
    ("output gamma 2.0 after the blend", _post_gamma(2.0), 3.06),
    ("clamp from cp_brightness 1.25", _v5(dict(cp_brightness=1.25)), 0.13),
    ("clamp from cp_brightness 4.00", _v5(dict(cp_brightness=4.00)), 4.84),
]


def self_test():
    """Check this tool against the figures AGENTS.md already records.

    The original tool was not in the repo and had to be rebuilt from its
    description, so the absolute scale is this definition's, not the original's.
    What must hold is that the ordering is identical and that the ratio to the
    record is consistent - if every construction comes out the same multiple
    bigger, the two are measuring the same thing through a different
    normalisation. If one construction drifts, they are not.
    """
    print("self-test against the figures recorded in AGENTS.md\n")
    print(f"  {'construction':<44s} {'measured':>9s} {'recorded':>9s} {'ratio':>7s}")
    got, ratios = [], []
    for label, render, expected in EXPECTED:
        v = measure(render)
        got.append(v)
        ratios.append(v / expected)
        print(f"  {label:<44s} {v:9.2f} {expected:9.2f} {v / expected:7.2f}")

    recorded = [e for _, _, e in EXPECTED]
    order_ok = (np.argsort(got) == np.argsort(recorded)).all()
    spread = max(ratios) / min(ratios)
    print(f"\n  ordering matches the record: {'yes' if order_ok else 'NO'}")
    print(f"  ratio {min(ratios):.2f} to {max(ratios):.2f} "
          f"(spread {spread:.2f}x), mean {np.mean(ratios):.2f}")
    print(f"  -> this definition reads about {np.mean(ratios):.1f}x the recorded "
          f"figures, so the visible threshold is {VISIBLE}")
    return order_ok and spread < 1.5


def report():
    print(f"\nbeat on a 1px checkerboard (visible above ~{VISIBLE})\n")
    scales = [
        ((320, 240), (1024, 768)),
        ((256, 224), (1024, 768)),
        ((256, 192), (1024, 768)),
        ((240, 160), (1024, 768)),
        ((160, 144), (1024, 768)),
        # PSP is the hardest case in the set and was missing from it until a
        # pattern turned up on a device that no measurement here predicted: at
        # 640x480 it is 1.33 output pixels per cell, below the two per cycle
        # where a pattern folds to a wrong coarser pitch at near-full amplitude.
        ((480, 272), (1024, 768)),
        ((480, 272), (640, 480)),
        ((320, 240), (640, 480)),
        ((256, 192), (640, 480)),
        ((160, 144), (640, 480)),
    ]
    # Each shader at its own shipped defaults, which is the only configuration
    # that gets gated; a parameter pushed past its default is the user's choice
    # and the headers document what it costs.
    from shaders import REGISTRY
    cols = [(n.replace(".glsl", "").replace("lcd-perfect", "lcd")
              .replace("dmg-perfect", "dmg"), n)
            for n in REGISTRY if n.startswith(("lcd-", "dmg-"))]
    cols.append(("crt-perfect", "crt-perfect.glsl"))

    print("  " + " " * 22 + "".join(f"{n:>14s}" for n, _ in cols))
    worst, worst_at = 0.0, ""
    for (sw, sh), (ow, oh) in scales:
        row = []
        for _, name in cols:
            model = REGISTRY[name]
            r = measure(lambda s, w, h, m=model: m.render(
                s, w, h, dict(m.defaults)) / 255.0, sw, sh, ow, oh,
                pattern_freq(name, sw, sh, ow, oh))
            if r > worst:
                worst, worst_at = r, f"{name} at {sw}x{sh} -> {ow}x{oh}"
            row.append(f"{r:14.3f}")
        print(f"  {sw}x{sh} -> {ow}x{oh}".ljust(24) + "".join(row))
    print(f"\n  worst at defaults: {worst:.3f} ({worst_at})   "
          f"{'OK' if worst <= VISIBLE else 'VISIBLE MOIRE'}")
    return worst


def report_curvature():
    """What barrel distortion costs crt-perfect-v6.

    The scaler only, with the patterns disabled: curvature acts on the sampling
    coordinate, and the patterns are deliberately left in unwarped screen space,
    so this is where any damage would land. Measured as the residual against a
    supersampled reference of the same warp, because the curved render cannot be
    measured directly - see curvature_residual().
    """
    from crt_preview import DEFAULTS_V6, render_crt_v6

    print("\ncurvature: worst 128x128 tile of the residual against supersampled")
    print(f"truth, scaler only (visible above ~{VISIBLE})\n")
    scales = [((320, 240), (1024, 768)), ((256, 224), (1024, 768)),
              ((320, 240), (640, 480))]
    ks = [0.0, 0.05, 0.10, 0.15]
    off = dict(DEFAULTS_V6, cp_scanlines=0.0, cp_rgb_mask=0.0,
               cp_mask_type=0.0, cp_brightness=1.0)

    print("  " + " " * 22 + "".join(f"{f'k={k:.2f}':>10s}" for k in ks) + "     tiles")
    worst, worst_at = 0.0, ""
    for (sw, sh), (ow, oh) in scales:
        src = checkerboard(sw, sh)
        pat = pattern_freq("crt-perfect.glsl", sw, sh, ow, oh)
        row, tiles = [], 0
        for k in ks:
            img = render_crt_v6(src, ow, oh, dict(off, cp_curvature=k))
            r, tiles = curvature_residual(img, src, k, sw, sh, pat)
            if r > worst:
                worst, worst_at = r, f"curvature {k:.2f} at {sw}x{sh} -> {ow}x{oh}"
            row.append(f"{r:10.3f}")
        print(f"  {sw}x{sh} -> {ow}x{oh}".ljust(24) + "".join(row) + f"    {tiles:4d}")

    print(f"\n  worst with curvature: {worst:.3f} ({worst_at})   "
          f"{'OK' if worst <= VISIBLE else 'VISIBLE MOIRE'}")
    return worst


def pattern_strength(img, tile=16):
    """RMS about the local mean, in tile x tile windows.

    Orientation-independent on purpose. The obvious way to measure how strong a
    scanline pattern is - peak-to-peak of a tile's row-mean - is only valid while
    the scanlines are horizontal. On a curved image they are not, and averaging
    along tile rows smears them: measured that way, a perfectly healthy warped
    pattern read 34.7 at the centre and 3.2 at the corner, a 10x collapse that
    looks exactly like catastrophic corner aliasing and is entirely the metric.
    RMS about the local mean has no preferred direction and reports 12.4 against
    12.1 for the same image.

    Returns a (rows, cols) array, one figure per window.
    """
    a = img.astype(np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    if a.max() <= 1.0001:
        a = a * 255.0
    h, w = a.shape
    ny, nx = h // tile, w // tile
    b = a[:ny * tile, :nx * tile].reshape(ny, tile, nx, tile)
    return b.transpose(0, 2, 1, 3).reshape(ny, nx, -1).std(axis=2)


def min_local_pitch(src_h, out_h, curvature, min_pitch=MIN_PITCH, lift=True):
    """Smallest number of output pixels per pattern cycle anywhere in the frame.

    This is the invariant the whole warped-pattern design rests on, and it is
    geometry, not an image statistic - which makes it the decisive check. A
    pattern locked to the source cannot also be locked to the output grid, so
    under warp its screen pitch varies, and it is finest where the magnification
    is greatest, at the corners. Keeping that worst case at or above min_pitch is
    what stops it aliasing.

    lift=False models the obvious implementation, which sets the pitch floor from
    the source and band-limits on a frame-wide frequency. It is the control: the
    floor has to absorb the largest magnification in the frame, not just exist.

    Note this cannot be measured from the rendered image. Aliasing does not
    remove pattern energy, it relocates it, so a strength or uniformity metric
    reads an aliased pattern as perfectly healthy - the naive version measures
    *more* uniform than the correct one. Only the geometry tells you.
    """
    jmax = (1.0 + 4.0 * curvature) / (1.0 + 2.0 * curvature)
    src_pitch = out_h / max(src_h, 1)
    floor = min_pitch * jmax if lift else min_pitch
    return max(src_pitch, floor) / jmax


def report_curvature_uniformity():
    """Does the pattern survive being warped, everywhere in the frame?

    Two checks. The invariant - worst-case local pitch, which is what the design
    guarantees - with the obvious implementation alongside as a control. Then the
    rendered pattern strength, which confirms nothing has collapsed.
    """
    from crt_preview import DEFAULTS_V7, render_crt_v7

    print("\ncurvature: smallest output px per pattern cycle, anywhere in frame")
    print(f"(must stay >= cp_min_pitch = {MIN_PITCH:.2f}; 'naive' floors the pitch")
    print(" from the source only, without absorbing the magnification)\n")
    scales = [((320, 240), (1024, 768)), ((256, 224), (1024, 768)),
              ((480, 272), (1024, 768)), ((320, 240), (640, 480))]
    ks = [0.05, 0.10, 0.20]

    print("  " + " " * 22 + "".join(f"{f'k={k:.2f}':>16s}" for k in ks))
    print("  " + " " * 22 + "".join(f"{'v7':>8s}{'naive':>8s}" for _ in ks))
    worst_ok, worst_naive = 99.0, 99.0
    for (sw, sh), (ow, oh) in scales:
        row = []
        for k in ks:
            a = min_local_pitch(sh, oh, k, lift=True)
            b = min_local_pitch(sh, oh, k, lift=False)
            worst_ok, worst_naive = min(worst_ok, a), min(worst_naive, b)
            row.append(f"{a:8.2f}{b:8.2f}")
        print(f"  {sw}x{sh} -> {ow}x{oh}".ljust(24) + "".join(row))
    print(f"\n  worst: v7 {worst_ok:.2f}  naive {worst_naive:.2f}   "
          f"{'OK' if worst_ok >= MIN_PITCH - 1e-6 else 'PATTERN GOES BELOW THE FLOOR'}")

    print("\ncurvature: pattern strength across the frame, 16x16 windows\n")
    print("  " + " " * 22 + "".join(f"{f'k={k:.2f}':>12s}" for k in [0.0] + ks[:2]))
    worst = 1.0
    for (sw, sh), (ow, oh) in scales:
        src = np.full((sh, sw, 3), 128, np.uint8)
        row = []
        for k in [0.0] + ks[:2]:
            m = pattern_strength(render_crt_v7(src, ow, oh,
                                               dict(DEFAULTS_V7, cp_curvature=k)))
            ratio = float(m.max() / max(m.min(), 1e-6))
            worst = max(worst, ratio)
            row.append(f"{ratio:12.2f}")
        print(f"  {sw}x{sh} -> {ow}x{oh}".ljust(24) + "".join(row))
    print(f"\n  worst max/min across the frame: {worst:.2f}   "
          f"{'OK' if worst <= UNIFORM else 'PATTERN COLLAPSING'}")
    return worst if worst_ok >= MIN_PITCH - 1e-6 else 99.0


def report_grade():
    """What each of pixel-perfect-v3's grade controls costs in beat.

    The claim is that brightness, contrast and saturation are affine, so they
    commute with the scaler's blend - post-blend and per-tap are the same result
    - and therefore cannot give partial-coverage pixels a coverage-dependent
    shift. Only the clamp and the gamma are non-linear. That is an argument, and
    an argument gets measured here rather than asserted.

    The clip column is what makes it falsifiable: if the affine reasoning holds,
    beat should track how much of the frame meets the clamp and nothing else, so
    a control at 0% clip must read at the neutral floor no matter how far from 1
    it is set.

    Two sources, because a black-and-white checkerboard cannot exercise a
    saturation control at all - on grey, luma equals every channel and the mix is
    a no-op, so a broken saturation would measure perfect. The chroma case is a
    red/cyan 1px checker, the same worst case one axis over.
    """
    from lcd_preview import (DEFAULTS_PP_V3, LUMA_709, area_average,
                             render_pixel_perfect_v3)

    def chroma(w, h):
        yy, xx = np.mgrid[0:h, 0:w]
        odd = ((yy + xx) % 2).astype(np.uint8)
        return np.stack([odd * 255, (1 - odd) * 255, (1 - odd) * 255], axis=2)

    def clip_pct(src, ow, oh, p):
        """Share of the frame the grade pushes outside 0 to 1, before the clamp."""
        col = area_average(src.astype(np.float64) / 255.0, ow, oh)[0]
        ga = p["pp_brightness"] * p["pp_contrast"]
        gb = 0.5 - 0.5 * p["pp_contrast"]
        s = p["pp_saturation"]
        luma = (col * LUMA_709).sum(axis=-1, keepdims=True)
        g = col * (ga * s) + (luma * (ga * (1.0 - s)) + gb)
        return float(((g < 0.0) | (g > 1.0)).mean()) * 100.0

    configs = [
        ("neutral (the defaults)", {}),
        ("saturation 0.00", dict(pp_saturation=0.0)),
        ("saturation 1.80", dict(pp_saturation=1.8)),
        ("contrast 0.40", dict(pp_contrast=0.4)),
        ("contrast 1.60", dict(pp_contrast=1.6)),
        ("brightness 0.60", dict(pp_brightness=0.6)),
        ("brightness 2.00", dict(pp_brightness=2.0)),
        ("gamma 0.70", dict(pp_gamma=0.7)),
        ("gamma 1.40", dict(pp_gamma=1.4)),
        ("full grade", dict(pp_saturation=1.3, pp_contrast=1.2,
                            pp_brightness=1.1, pp_gamma=0.9)),
    ]
    scales = [((320, 240), (1024, 768)), ((480, 272), (1024, 768)),
              ((480, 272), (640, 480)), ((320, 240), (640, 480)),
              ((160, 144), (1024, 768))]

    print("\npixel-perfect-v3: what a post-blend grade costs, worst over "
          f"{len(scales)} scales")
    print(f"(1px checkerboards, visible above ~{VISIBLE}; clip is the share of "
          "the frame\n the grade pushes outside 0 to 1 before the clamp)\n")
    print(f"  {'configuration':<24s} {'mono':>8s} {'chroma':>8s} {'clip':>8s}")

    worst_clean, worst_at = 0.0, ""
    for label, over in configs:
        p = dict(DEFAULTS_PP_V3, **over)
        mono_b = chroma_b = clip = 0.0
        for (sw, sh), (ow, oh) in scales:
            for name, make in (("mono", checkerboard), ("chroma", chroma)):
                src = make(sw, sh)
                r = beat(render_pixel_perfect_v3(src, ow, oh, p), sw, sh)
                if name == "mono":
                    mono_b = max(mono_b, r)
                else:
                    chroma_b = max(chroma_b, r)
                clip = max(clip, clip_pct(src, ow, oh, p))
        # Only the rows that are meant to be clean are gated. A row that clips,
        # or that takes the gamma, is a documented cost the header states - the
        # same way crt-perfect's gamma 1.4 is not a failure.
        linear = clip < 1e-9 and abs(p["pp_gamma"] - 1.0) <= 0.001
        r = max(mono_b, chroma_b)
        if linear and r > worst_clean:
            worst_clean, worst_at = r, label
        print(f"  {label:<24s} {mono_b:8.3f} {chroma_b:8.3f} {clip:7.1f}%"
              f"{'' if linear else '   <- clamp/gamma, a documented cost'}")

    print(f"\n  worst where nothing clips and the gamma is off: {worst_clean:.3f}"
          f" ({worst_at})   {'OK' if worst_clean <= VISIBLE else 'VISIBLE MOIRE'}")
    print("  An affine grade commutes with the blend, so these must sit at the"
          "\n  scaler's own floor however far from 1 the control is pushed.")
    return worst_clean


if __name__ == "__main__":
    ok = self_test()
    w = report()
    wg = report_grade()
    wc = report_curvature()
    wu = report_curvature_uniformity()
    sys.exit(0 if ok and max(w, wg, wc) <= VISIBLE and wu <= UNIFORM else 1)
