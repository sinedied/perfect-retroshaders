#!/usr/bin/env python3
"""The numbers that decide whether a shader looks right.

  moire      the low-frequency beat a shader paints onto flat content. Render a
             1px checkerboard - maximum energy at the pixel grid - and measure
             everything strictly slower than both the content and the shader's
             own pattern. Whatever is down there was manufactured.

  grid       are the cells even, and does a line hold its share of a cell across
             scales. Spacing CV catches two faults at once, on purpose, because
             a viewer cannot tell them apart; cv_lattice separates them for the
             author.

  lock       pattern cycles per source line. 1.000 means scanlines still land on
             source rows, which is what makes them read as scanlines.

  pitch      the finest the pattern gets anywhere in the frame, in output
             pixels. Geometry, not an image statistic - and it has to be,
             because aliasing relocates pattern energy rather than removing it,
             so an aliased pattern measures perfectly healthy.

    python tools/measure.py                  the working set
    python tools/measure.py crt-perfect      one family
    python tools/measure.py --self-test      check the metric, not the shaders
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

# The four shades a Game Boy core actually puts on screen, lightest first.
# Gambatte's GB-DMG: the darkest paper of any palette surveyed, at luma 0.401,
# so it is the strictest case for anything that must tell an undriven pixel from
# a driven one. A plain checkerboard's light square IS white, which hides every
# fault that depends on the difference between white and the panel's own paper.
DMG_PALETTE = [(87, 130, 0), (49, 116, 0), (0, 81, 33), (0, 66, 12)]

def dmg_checkerboard(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    a = np.empty((h, w, 3), np.uint8)
    a[...] = np.array(DMG_PALETTE[0], np.uint8)
    a[(yy + xx) % 2 == 0] = np.array(DMG_PALETTE[3], np.uint8)
    return a


# --------------------------------------------------------------------------
# moire

def pattern_freq(name, src_w, src_h, out_w, out_h, min_pitch=None):
    """Where a shader puts its pattern, in cycles per output pixel.

    The band has to duck under this, so it is declared per shader in
    baseline.toml rather than guessed. Three rules are in play across the family
    and they do not agree, which is exactly why guessing does not work - and why
    the previous version of this, which matched on filename prefixes, handed
    crt-perfect v6 through v10 the wrong rule and measured them against a band
    that cut through their own mesh.
    """
    min_pitch = c.MIN_PITCH if min_pitch is None else min_pitch
    d = (src_w / out_w, src_h / out_h)
    rule = c.SHADERS_DECLARED.get(name, {}).get("pattern", "source")
    if rule == "whole-cell":
        # the period grows to a whole number of cells, never finer than min_pitch
        n = [max(math.ceil(min_pitch * x - 1e-4), 1) for x in d]
        return (d[0] / n[0], d[1] / n[1])
    if rule == "output-locked":
        # locks to a fixed output-space pitch instead of growing the period
        return (min(d[0], 1.0 / min_pitch), min(d[1], 1.0 / min_pitch))
    return d  # tracks the source at one cycle per cell, always


def _band(out_w, out_h, src_w, src_h, pattern, fx, fy):
    """The cutoff mask. Derived from the sizes, never assumed.

    Getting this wrong is the documented way to produce confident nonsense: a
    fixed "periods 6-64px are moire" window counts the pattern itself the moment
    its pitch enters the window, and a low-pass at the pattern's repeat length
    removes the beat along with it, because at a rational scale the whole image
    is periodic at that length and nothing survives. Both were tried here.

    The 0.85 is a guard, not a fudge. The pattern is not commensurate with the
    frame, so a rectangular window smears it into neighbouring bins with only
    1/offset decay, and an edge sitting on the pattern swallows half its skirt.
    Windowing the frame wrecked the self-test; cropping to a whole number of
    periods just moves the leakage onto the content.
    """
    px_f, py_f = pattern if pattern else (src_w / out_w, src_h / out_h)
    cx = min(0.5 * src_w / out_w, 0.85 * px_f) * 0.999
    cy = min(0.5 * src_h / out_h, 0.85 * py_f) * 0.999
    band = (fy[:, None] < cy) & (fx[None, :] < cx)
    band[0, 0] = False  # DC is the image's mean level, not a beat
    return band


def beat(img, src_w, src_h, pattern=None):
    """RMS of everything slower than the content and the pattern, in 8-bit levels.

    A 1px checkerboard is a single pair of impulses at half a cycle per source
    pixel with harmonics above, so nothing legitimate lives below that. Anything
    over about 0.4 is visible.
    """
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
    band = _band(out_w, out_h, src_w, src_h, pattern, fx, fy)
    return float(np.sqrt((np.abs(F[band]) ** 2).sum()))


def moire(ctx, progs, name, case, source=None, **override):
    sw, sh, ow, oh = case
    src = (source or c.checkerboard)(sw, sh)
    img = c.render(ctx, progs, name, src, ow, oh, **override)
    return beat(img, sw, sh, pattern_freq(name, sw, sh, ow, oh))


# --------------------------------------------------------------------------
# moire under curvature
#
# Measuring a curved render directly does not work, and the reason is worth
# keeping: barrel distortion varies the local magnification on purpose, so block
# sizes genuinely change across the frame. A band-limited FFT scores that
# intended variation as beat - it reads 4 to 20 where the flat metric reads 0.26,
# and none of it is an artifact. Same trap as above wearing a different hat.

def _supersampled(src_u8, out_w, out_h, curvature, ss=4):
    """Ground truth for the warped scale: ss x ss rays per output pixel through
    the warp, nearest source texel each, averaged. No footprint model is used -
    the mean of point samples over the pixel IS what a footprint model
    approximates."""
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


def curvature_residual(shaded, src_u8, curvature, src_w, src_h, pattern,
                       tile=128, ss=(8, 16)):
    """Worst tile-local low-frequency energy in the residual against truth.

    Differencing against a supersampled reference of the same warp cancels the
    intended geometry and the black surround, leaving only what the shader got
    wrong.

    THE REFERENCE IS NOISY AND THE NOISE LOOKS EXACTLY LIKE THE ANSWER. Each ray
    takes one nearest texel, so a reference from n samples per pixel quantises to
    1/n, and on a 1px checkerboard that is enormous: 16.2 at 2x2, 8.0 at 4x4, 3.8
    at 8x8, 1.9 at 16x16, 0.9 at 32x32. Halving on every doubling is the
    signature of a 1/ss error and nothing to do with the shader - but any one of
    those figures reads as a confident, damning measurement.

    So the error is extrapolated away rather than sampled away: with e = C/ss,
    two references at ss and 2*ss give 2*r(2ss) - r(ss) with the C term removed.
    That reads -0.06 where ss=8 alone reads 3.8, and it is stable across which
    pair is used, which is the check that the model of the error is right.
    """
    r = []
    for n in ss:
        truth = _supersampled(src_u8, shaded.shape[1], shaded.shape[0],
                              curvature, n)
        resid = (shaded.astype(np.float64) / 255.0 - truth).mean(axis=2) * 255.0
        r.append(_worst_tile(resid, curvature, src_w, src_h, pattern, tile))
    return max(2.0 * r[1][0] - r[0][0], 0.0), r[1][1]


# --------------------------------------------------------------------------
# pattern geometry
#
# Both of these are computed from the geometry rather than measured from the
# image, and that is not a shortcut. Aliasing does not remove pattern energy, it
# relocates it, so a strength or uniformity metric reads an aliased pattern as
# perfectly healthy - the naive implementation measured MORE uniform than the
# correct one. Only the geometry can tell you.

def source_lock(src_h, out_h, curvature, min_pitch=None, lift=False):
    """Pattern cycles per source line. 1.000 means the pattern still lands on
    the source rows.

    This is the check that was missing while v7, v8 and v9 shipped. Every
    curvature test measured a flat grey field, or a checkerboard with the
    patterns switched off, so none of them had a source with rows in it and none
    could see the pattern drifting off. Those versions lifted the pitch floor by
    the frame's worst magnification to protect the corners, which rescaled the
    pattern everywhere: 240 source lines came out as 201 scanlines at curvature
    0.10, and the only reason it was caught is that someone looked at the screen.

    lift=True models that older behaviour, as the control.
    """
    min_pitch = c.MIN_PITCH if min_pitch is None else min_pitch
    jmax = (1.0 + 4.0 * curvature) / (1.0 + curvature)
    src_pitch = out_h / max(src_h, 1)
    floor = min_pitch * jmax if lift else min_pitch
    return src_pitch / max(src_pitch, floor)


def min_local_pitch(src_h, out_h, curvature, min_pitch=None, lift=True):
    """Smallest output pixels per pattern cycle anywhere in the frame.

    A pattern locked to the source cannot also be locked to the output grid, so
    under warp its screen pitch varies, and it is finest where the magnification
    is greatest, at the corners.

    lift=False is the control: the obvious implementation, which sets the floor
    from the source and band-limits on a frame-wide frequency.
    """
    min_pitch = c.MIN_PITCH if min_pitch is None else min_pitch
    jmax = (1.0 + 4.0 * curvature) / (1.0 + 2.0 * curvature)
    src_pitch = out_h / max(src_h, 1)
    floor = min_pitch * jmax if lift else min_pitch
    return max(src_pitch, floor) / jmax


def pattern_strength(img, tile=16):
    """RMS about the local mean, in tile x tile windows.

    Orientation-independent on purpose. The obvious measure - peak-to-peak of a
    tile's row mean - is only valid while the scanlines are horizontal. On a
    curved image they are not, and averaging along tile rows smears them: a
    perfectly healthy warped pattern read 34.7 at the centre and 3.2 at the
    corner, a 10x collapse that looks like catastrophic aliasing and is entirely
    the metric. RMS about the local mean reports 12.4 against 12.1.
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


# --------------------------------------------------------------------------
# grid geometry

def lit_level(profile):
    """The level the picture sits at, as opposed to the grid.

    Returns (level, ambiguous). Whichever extreme holds more samples, which is
    polarity-agnostic: a DMG's grid is LIGHTER than a lit pixel and every other
    panel's is darker, and this has to read both.

    A median is wrong at the one place it matters. A line exactly half the cell
    splits the samples evenly, so the median lands between the clusters, every
    sample reads equally far from "lit", the profile comes back as one run and
    the grid vanishes. That case is genuinely ambiguous rather than awkward - at
    50% duty no measurement can say which half is the line - so it is reported.
    """
    lo, hi = float(profile.min()), float(profile.max())
    if hi - lo < 1e-9:
        return lo, True
    mid = 0.5 * (lo + hi)
    n_hi, n_lo = int((profile > mid).sum()), int((profile < mid).sum())
    ambiguous = abs(n_hi - n_lo) / max(n_hi + n_lo, 1) < 0.05
    return (hi if n_hi >= n_lo else lo), ambiguous


def find_lines(profile, frac=0.15):
    """Grid lines in a 1D profile, as (centre, width) in output pixels.

    Centres are ink-weighted centroids, not threshold crossings: a line drawn as
    one solid pixel plus a partial one has a centre half a pixel off the solid
    one, and calling it whole is what made two earlier attempts read a perfectly
    even grid as uneven.

    Width is total ink over peak ink - the equivalent rectangular width. For a
    hard 1px line that is 1.0; for a 1.28px line drawn as one full pixel plus 28%
    of the next it is 1.28, which is the analytic answer.
    """
    g = np.abs(profile - lit_level(profile)[0])
    peak = g.max()
    if peak <= 1e-9:
        return []
    mask = g > frac * peak
    lines, i, n = [], 0, len(g)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        # runs touching an edge are cut off, so their centroid and their width
        # both measure the crop rather than the grid
        if i > 0 and j < n:
            w = g[i:j]
            xs = np.arange(i, j) + 0.5
            lines.append((float((xs * w).sum() / w.sum()), float(w.sum() / peak)))
        i = j
    return lines


def synthetic(period, width, n=1024):
    """A perfectly even grid, box-filtered in closed form, with no shader.

    The spacing is exact by construction, so whatever CV this measures is the
    metric reading edge softness rather than unevenness.
    """
    x = np.arange(n, dtype=np.float64)

    def area(t):
        k = np.floor(t / period)
        return k * width + np.clip(t - k * period, 0.0, width)

    return 1.0 - (area(x + 1.0) - area(x))


def axis_report(img, along):
    """Spacing and width of the grid lines along one axis, 'x' or 'y'.

    Profiled by averaging over the other axis. Exact rather than convenient: the
    coverage is separable, so averaging down a column leaves the horizontal
    profile proportional to the horizontal coverage alone.

    `cv` conflates two faults on purpose, because a viewer cannot tell a lattice
    on the wrong pitch from a line too soft to sit still. An author has to, so
    `cv_lattice` subtracts the softness part, measured from a synthetic grid of
    the same spacing and width. Getting this backwards cost a shipped shader: a
    bare cv says a 2px line is forty times better than a 1.3px one, which drove
    dmg-perfect-v1 to force 2px lines - the first thing anyone noticed was wrong
    with it. The wide line scored well because it was smooth, not well placed.
    """
    lum = img.astype(np.float64).mean(axis=2)
    prof = lum.mean(axis=0) if along == "x" else lum.mean(axis=1)
    if lit_level(prof)[1]:
        return None
    lines = find_lines(prof)
    if len(lines) < 3:
        return None
    centres = np.array([p for p, _ in lines])
    widths = np.array([w for _, w in lines])
    gaps = np.diff(centres)
    spacing, width = float(gaps.mean()), float(widths.mean())
    cv = float(gaps.std() / gaps.mean() * 100.0) if gaps.mean() else 0.0

    cv_soft = 0.0
    if spacing > 1.0 and 0.0 < width < spacing:
        ideal = find_lines(synthetic(spacing, width, n=max(len(prof), 256)))
        if len(ideal) >= 3:
            g = np.diff(np.array([p for p, _ in ideal]))
            cv_soft = float(g.std() / g.mean() * 100.0) if g.mean() else 0.0

    return dict(count=len(lines), spacing=spacing, cv=cv, cv_soft=cv_soft,
                cv_lattice=max(cv - cv_soft, 0.0), width=width,
                width_spread=float(widths.max() - widths.min()))


def grid(ctx, progs, name, case, level=128, **override):
    """Grid geometry on both axes for one case, or None where there is no grid."""
    sw, sh, ow, oh = case
    img = c.render(ctx, progs, name, c.flat(sw, sh, level), ow, oh, **override)
    return axis_report(img, "x"), axis_report(img, "y")


# --------------------------------------------------------------------------
# the scaler reference
#
# pixel-perfect is the one shader here with a genuine third-party implementation
# to check against, and every other shader in the repo is built on the same
# scaler, so this anchors all of them.

def worst_diff(a, b):
    """Largest absolute difference, in 8-bit levels."""
    return float(np.abs(a.astype(np.int32) - b.astype(np.int32)).max())


def box_scale(src_u8, out_w, out_h):
    """An exact area average, written from scratch.

    The construction every shader here is defined against, so it is a statement
    of the specification rather than a model of any particular shader.
    """
    src = src_u8.astype(np.float64)
    in_h, in_w = src.shape[:2]
    xs, ys = np.arange(in_w), np.arange(in_h)
    xe = np.arange(out_w + 1) * in_w / out_w
    ye = np.arange(out_h + 1) * in_h / out_h
    wx = np.clip(np.minimum(xs[None, :] + 1, xe[1:, None])
                 - np.maximum(xs[None, :], xe[:-1, None]), 0, None)
    wy = np.clip(np.minimum(ys[None, :] + 1, ye[1:, None])
                 - np.maximum(ys[None, :], ye[:-1, None]), 0, None)
    wx /= wx.sum(axis=1, keepdims=True)
    wy /= wy.sum(axis=1, keepdims=True)
    # separably, one axis at a time. Doing it in one einsum is O(out * in) in
    # all four dimensions and takes minutes at 320x240 -> 1024x768.
    rows = (wy @ src.reshape(in_h, -1)).reshape(out_h, in_w, 3)
    return (wx @ rows.transpose(1, 0, 2).reshape(in_w, -1)
            ).reshape(out_w, out_h, 3).transpose(1, 0, 2)


def against_pixellate(ctx, progs, name, case, **override):
    """This shader against the vendored pixellate, in its non-linear mode.

    pixellate has two modes. INTERPOLATE_IN_LINEAR_GAMMA = 0 blends in the
    encoded domain; = 1, its default, linearises each tap first, which is itself
    a moire source. pixel-perfect targets the former, so that is what is
    compared - and it is passed explicitly, because leaving the uniform at 0
    would select the right mode by accident, which is not the same thing.
    """
    sw, sh, ow, oh = case
    src = c.scene(sw, sh)
    a = c.render(ctx, progs, "pixellate.glsl", src, ow, oh,
                 params={"INTERPOLATE_IN_LINEAR_GAMMA": 0.0})
    b = c.render(ctx, progs, name, src, ow, oh, **override)
    return worst_diff(a, b)


# --------------------------------------------------------------------------
# self-test
#
# A metric that has never been checked against a known-good and a known-bad case
# is how the last three tooling bugs produced confident, wrong figures. None of
# these constructions has a shader in it.

def self_test(report):
    sw, sh, ow, oh = 320, 240, 1024, 768
    src = c.checkerboard(sw, sh)
    clean = box_scale(src, ow, oh)

    b = beat(clean, sw, sh)
    report.check(b < 0.05, "a clean box average has no beat",
                 f"{b:.3f}, want < 0.05")

    # The documented moire source: a non-linearity applied across the scaler's
    # blend. At a non-integer scale a source pixel covers three or four output
    # pixels, so partial-coverage counts vary block to block, and anything
    # non-linear gives those pixels a coverage-dependent shift that beats.
    dirty = np.clip(clean * 1.6, 0, 255)
    b = beat(dirty, sw, sh)
    report.check(b > c.MOIRE, "a clamp from gain > 1 does",
                 f"{b:.3f}, want > {c.MOIRE}")

    # A band that does not exclude the effect under test measures the effect.
    # The case that bites is a pattern whose period has grown to stay clear of
    # the pixel grid, so it ends up BELOW the content: at 480x272 into 640x480
    # the mesh sits under half a cycle per source pixel. A band that only ducks
    # under the content then scores the shader's own mesh as moire, which is how
    # a correct mesh once read 15.4.
    psw, psh, pow_, poh = 480, 272, 640, 480
    base = box_scale(c.checkerboard(psw, psh), pow_, poh)
    mesh = base * (1.0 + 0.2 * np.cos(2 * np.pi * 0.25 * np.arange(poh))[:, None, None])
    told = beat(mesh, psw, psh, pattern=(1.0, 0.25))
    not_told = beat(mesh, psw, psh)
    # Judged as a ratio. The declared figure is not zero and cannot be: the mesh
    # is not commensurate with the frame, so a rectangular window smears it into
    # neighbouring bins with only 1/offset decay, and the band edge sits 0.04
    # cycles away. Bounding that skirt is what the 0.85 guard in _band is for.
    report.check(not_told > 20 * told and not_told > c.MOIRE,
                 "a declared pattern is excluded, an undeclared one is counted",
                 f"{told:.3f} declared against {not_told:.3f} undeclared")

    # Grid geometry against a construction whose answer is known analytically.
    # The 0.03 is the metric's own accuracy: the 15% ink threshold clips the
    # shallowest tails, so a line reads a little narrower than it is drawn.
    lines = find_lines(synthetic(6.4, 1.28, n=512))
    gaps = np.diff([p for p, _ in lines])
    width = float(np.mean([w for _, w in lines]))
    report.check(abs(gaps.mean() - 6.4) < 0.01 and abs(width - 1.28) < 0.03,
                 "grid geometry recovers a known lattice",
                 f"spacing {gaps.mean():.3f} want 6.4, width {width:.3f} want 1.28")

    cv = float(gaps.std() / gaps.mean() * 100.0)
    report.check(cv < 2.0, "an exact lattice measures as exact",
                 f"cv {cv:.2f}%, softness only")


# --------------------------------------------------------------------------

def run(names, report, cases=None, verbose=False):
    ctx = c.context()
    progs = c.Programs(ctx)
    cases = cases or c.CASES

    for name in names:
        worst, worst_at = 0.0, ""
        for case in cases:
            r = moire(ctx, progs, name, case)
            allowed = c.moire_allowance(name, case)
            if allowed is not None:
                report.note(f"{name} {c.golden_key(case)}: moire {r:.3f}, "
                            f"recorded exception at {allowed:.3f}")
                if r > allowed + 0.05:
                    worst, worst_at = r, c.golden_key(case) + " (over its exception)"
            elif r > worst:
                worst, worst_at = r, c.golden_key(case)
        report.check(worst <= c.MOIRE, f"{name} moire",
                     f"worst {worst:.3f} at {worst_at}")

    if verbose:
        for name in names:
            for case in cases:
                gx, gy = grid(ctx, progs, name, case)
                for axis, g in (("x", gx), ("y", gy)):
                    if g is not None:
                        report.note(f"{name} {c.golden_key(case)} {axis}: "
                                    f"spacing {g['spacing']:.3f} "
                                    f"cv {g['cv']:.1f}% "
                                    f"(lattice {g['cv_lattice']:.1f}%) "
                                    f"line {g['width']:.2f}px")
    return report


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--self-test" in sys.argv:
        r = c.Report("measure self-test")
        self_test(r)
    else:
        r = c.Report("measure")
        run(c.resolve(args), r, verbose="-v" in sys.argv)
    sys.exit(r.done())
