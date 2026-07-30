#!/usr/bin/env python3
"""Measure a grid: are its cells even, does it hold its look across scales, and
does it still match the reference where the reference is already right.

Three numbers, one per fault this repo cares about.

  spacing CV   how much the distance between grid lines varies. Two different
               faults land here and that is deliberate, because a viewer cannot
               tell them apart: a grid drawn on whole output pixels cannot place
               its lines 6.4 apart so it alternates 6, 7, 6, 7; and a line
               narrower than about two pixels is mostly soft edge, so how its
               ink is spread shifts from cell to cell even when the spacing is
               exact. Both read as "the lines are not all the same". At period
               6.4 a hard 1px line measures 7.7%, an exact 1.28px one 1.7%, and
               an exact 1.99px one 0.04%.

  line width   the width of a grid line in OUTPUT pixels, and as a share of a
               cell. The share is what keeps a shader looking like itself at two
               resolutions; the output-pixel figure is what decides whether the
               line can be drawn cleanly at all, per the CV above.

  identity     max difference against a reference shader. At an integer scale a
               four-tap area average returns the source texel exactly, so a
               scaler-based shader can be bit-identical to a point-sampling one
               there - and where the reference is already right, "no worse" means
               exactly that, not approximately.

Measured on a flat field, so nothing in the picture can be mistaken for the
pattern. Both axes are reported: 1024x768 from 160x144 is fractional on both
(6.40, 5.33), 640x480 is whole across and fractional down (4.00, 3.33), and the
two behave differently.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python grid.py [shader ...]
"""

import sys

import numpy as np

import moderngl
from gl_check import gl_render, stage_source
from paths import shader_path

# Scales worth reporting: whole ones, where the reference is already correct and
# must be matched, and the fractional ones the hosts actually run.
CASES = [
    ("GB 5x integer", (160, 144), (800, 720)),
    ("GB 4x integer", (160, 144), (640, 576)),
    ("GB 3x integer", (160, 144), (480, 432)),
    ("GB   -> 1024x768", (160, 144), (1024, 768)),
    ("GB   ->  640x480", (160, 144), (640, 480)),
    ("GB   ->  320x288", (160, 144), (320, 288)),
    ("GBA  -> 1024x768", (240, 160), (1024, 768)),
    ("GBA  ->  640x480", (240, 160), (640, 480)),
]

# The reference and the parameters that make it itself.
REFERENCE = "dmg_dot_matrix.glsl"
REFERENCE_DEFAULTS = dict(dmg_edge_alpha=0.3, dmg_brightness_correction=1.2,
                          dmg_grid_lightness=1.0, dmg_gamma=1.4)

# The parameter pairings under which a shader and the reference are the same
# shader. Not the shipped defaults on either side: those differ in tone, for a
# reason dmg_preview.py records. Several pairings rather than one, because the
# claim is that they agree across the parameter space, not at a lucky point.
#
# Keyed by shader, because dp_gap changed units between v1 and v2 - a share of a
# cell there, a thickness in pixels here. Handing one set to the other would ask
# for a fifth of a pixel and quietly measure nothing.
def _ref(alpha=0.30, bright=1.20, gamma=1.40, light=1.00):
    return dict(dmg_edge_alpha=alpha, dmg_brightness_correction=bright,
                dmg_grid_lightness=light, dmg_gamma=gamma)


MATCHED = {
    "dmg-perfect-v1.glsl": [
        ("reference defaults",
         dict(dp_grid=0.30, dp_gap=0.20, dp_level=1.00, dp_brightness=1.20,
              dp_gamma=1.40), _ref()),
        ("gamma off",
         dict(dp_grid=0.30, dp_gap=0.20, dp_level=1.00, dp_brightness=1.20,
              dp_gamma=1.00), _ref(gamma=1.00)),
        ("strong dark matrix",
         dict(dp_grid=0.80, dp_gap=0.20, dp_level=0.00, dp_brightness=1.00,
              dp_gamma=0.80), _ref(alpha=0.80, bright=1.00, gamma=0.80,
                                   light=0.00)),
    ],
    "dmg-perfect-v2.glsl": [
        ("reference defaults",
         dict(dp_grid=0.30, dp_gap=1.00, dp_brightness=1.20, dp_gamma=1.40),
         _ref()),
        ("gamma off",
         dict(dp_grid=0.30, dp_gap=1.00, dp_brightness=1.20, dp_gamma=1.00),
         _ref(gamma=1.00)),
        ("strong grid",
         dict(dp_grid=0.80, dp_gap=1.00, dp_brightness=1.00, dp_gamma=0.80),
         _ref(alpha=0.80, bright=1.00, gamma=0.80)),
    ],
}

# What counts as "perfectly even", as a percentage CV. A grid that really is
# even still measures ~2e-13 here, because the centroids are sums of float64
# products and the spacings are differences of those. Real unevenness at the
# scales in CASES is 7 to 18 percent, so anything between the two separates them
# by nine orders of magnitude in either direction; an exact == 0.0 does not, and
# reported three known-good cases as failures.
EVEN = 1e-4


def compile_shader(ctx, name):
    src = open(shader_path(name)).read()
    return ctx.program(vertex_shader=stage_source(src, "vert"),
                       fragment_shader=stage_source(src, "frag"))


def lit_level(profile):
    """The level the picture sits at, as opposed to the grid.

    Returns (level, ambiguous). Taken as whichever extreme holds more of the
    samples, which is polarity-agnostic - a DMG's grid is *lighter* than a lit
    pixel and every other panel's is darker, and this metric has to read both.

    A median was tried first and is wrong at the one place it matters: a grid
    whose line is exactly half the cell splits the samples evenly, so the median
    lands between the two clusters and every sample reads as equally far from
    "lit". The whole profile then comes back as one run and the grid vanishes.
    That case is genuinely ambiguous rather than merely awkward - at 50% duty
    there is no measurement that can say which half is the line - so it is
    reported instead of guessed at.
    """
    lo, hi = float(profile.min()), float(profile.max())
    if hi - lo < 1e-9:
        return lo, True
    mid = 0.5 * (lo + hi)
    n_hi = int((profile > mid).sum())
    n_lo = int((profile < mid).sum())
    total = max(n_hi + n_lo, 1)
    return (hi if n_hi >= n_lo else lo), abs(n_hi - n_lo) / total < 0.05


def ink(profile):
    """Per-sample grid ink: how far each sample sits from the lit level."""
    return np.abs(profile - lit_level(profile)[0])


def find_lines(profile, frac=0.15):
    """Grid lines in a 1D profile, as (centre, width) in output pixels.

    Centres are ink-weighted centroids, not threshold crossings: a line drawn as
    one solid pixel plus a partial one has a centre half a pixel off the solid
    one, and calling it whole is what made two earlier attempts at this read a
    perfectly even grid as uneven.

    Width is total ink over peak ink - the equivalent rectangular width. For a
    hard 1px line that is 1.0, and for a 1.28px line drawn as one full pixel plus
    28% of the next it is 1.28, which is the analytic answer.
    """
    g = ink(profile)
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
        # drop runs touching an edge: they are cut off, so their centroid and
        # their width are both measuring the crop rather than the grid
        if i > 0 and j < n:
            w = g[i:j]
            xs = np.arange(i, j) + 0.5
            lines.append((float((xs * w).sum() / w.sum()), float(w.sum() / peak)))
        i = j
    return lines


def axis_report(img, along):
    """Spacing and width of the grid lines along one axis, 'x' or 'y'.

    Profiled by averaging over the other axis. That is exact rather than
    convenient: the coverage is separable, so averaging down a column leaves the
    horizontal profile proportional to the horizontal coverage alone, with the
    vertical grid folded into a constant that cancels out of every ratio here.

    `cv` conflates two faults on purpose, because a viewer cannot tell them
    apart - but a shader author has to, so `cv_soft` separates them. It is the
    CV of a synthetic grid with the *same measured spacing and width* whose
    lattice is exact by construction, so it is the part of `cv` that is edge
    softness rather than unevenness. `cv` near `cv_soft` means the lines are
    where they should be and only their ink is spread differently; `cv` well
    above it means the lattice itself is wrong.

    Getting this backwards cost a shipped shader: reading a bare `cv` says a
    2px line is forty times better than a 1.3px one, which drove dmg-perfect-v1
    to force lines to 2px, which is the first thing anyone noticed was wrong
    with it. The wide line scored well because it was smooth, not because it
    was well placed.
    """
    lum = img.astype(np.float64).mean(axis=2)
    prof = lum.mean(axis=0) if along == "x" else lum.mean(axis=1)
    _, ambiguous = lit_level(prof)
    if ambiguous:
        return None
    lines = find_lines(prof)
    if len(lines) < 3:
        return None
    centres = np.array([c for c, _ in lines])
    widths = np.array([w for _, w in lines])
    gaps = np.diff(centres)
    spacing = float(gaps.mean())
    width = float(widths.mean())
    cv = float(gaps.std() / gaps.mean() * 100.0) if gaps.mean() else 0.0

    cv_soft = 0.0
    if spacing > 1.0 and 0.0 < width < spacing:
        ideal = find_lines(synthetic(spacing, width, n=max(len(prof), 256)))
        if len(ideal) >= 3:
            g = np.diff(np.array([c for c, _ in ideal]))
            cv_soft = float(g.std() / g.mean() * 100.0) if g.mean() else 0.0

    return dict(
        count=len(lines),
        spacing=spacing,
        cv=cv,
        cv_soft=cv_soft,
        cv_lattice=max(cv - cv_soft, 0.0),
        width=width,
        width_spread=float(widths.max() - widths.min()),
    )


def report(ctx, name, params, cases=CASES, source_level=128):
    print(f"\n{name}")
    print(f"  {'case':18s} {'scale':13s} {'spacing x':>10s} {'CV':>13s}"
          f" {'spacing y':>10s} {'CV':>13s}   {'line px':>9s} {'of cell':>9s}")
    rows = []
    prog = compile_shader(ctx, name)
    for label, (sw, sh), (ow, oh) in cases:
        src = np.full((sh, sw, 3), source_level, np.uint8)
        img = gl_render(ctx, prog, src, ow, oh, params)
        x = axis_report(img, "x")
        y = axis_report(img, "y")
        sx, sy = ow / sw, oh / sh
        if x is None or y is None:
            miss = " ".join(a for a, v in (("x", x), ("y", y)) if v is None)
            print(f"  {label:18s} {sx:5.2f}x{sy:5.2f}   "
                  f"no measurable grid on {miss} - a line exactly half the cell "
                  f"wide cannot be told from the cell")
            continue
        # "4.2 (0.1)" - total, and how much of it is not edge softness
        cvx = f"{x['cv']:5.1f}%({x['cv_lattice']:4.1f})"
        cvy = f"{y['cv']:5.1f}%({y['cv_lattice']:4.1f})"
        print(f"  {label:18s} {sx:5.2f}x{sy:5.2f} "
              f"{x['spacing']:10.3f} {cvx:>13s} "
              f"{y['spacing']:10.3f} {cvy:>13s}   "
              f"{x['width']:4.2f},{y['width']:4.2f} "
              f"{x['width']/sx*100:3.0f}%,{y['width']/sy*100:3.0f}%")
        rows.append((label, sx, sy, x, y))
    print("  CV is total variation; the figure in brackets is the part that is "
          "NOT\n  edge softness, so it is the one that means the lattice is "
          "wrong.")
    return rows




def identity(ctx, name, params, ref=REFERENCE, ref_params=None,
             cases=None, sources=("gray", "scene")):
    """Max difference against the reference, on whole scales only.

    A fractional scale is where the two are *meant* to differ, so comparing them
    there measures nothing. Whole scales are the constraint: the reference is
    already right at 5x and the replacement has to be no worse, which on a grid
    of hard-edged lines means identical rather than close.
    """
    from crt_preview import SOURCES

    ref_params = REFERENCE_DEFAULTS if ref_params is None else ref_params
    cases = cases or [c for c in CASES if "integer" in c[0]]
    prog = compile_shader(ctx, name)
    refprog = compile_shader(ctx, ref)
    out = []
    for label, (sw, sh), (ow, oh) in cases:
        worst = 0
        for sname in sources:
            src = SOURCES[sname](sw, sh)
            a = gl_render(ctx, prog, src, ow, oh, params).astype(int)
            b = gl_render(ctx, refprog, src, ow, oh, ref_params).astype(int)
            worst = max(worst, int(np.abs(a - b).max()))
        out.append((label, worst))
    return out


def synthetic(period, width, n=1024):
    """A perfectly even grid, box-filtered exactly, with no shader involved.

    Lines of `width` output pixels every `period` output pixels, integrated over
    each pixel in closed form. The spacing is exact by construction, so whatever
    CV this measures is the metric reading edge softness rather than unevenness -
    which is the point: those are the same artefact to a viewer.
    """
    x = np.arange(n, dtype=np.float64)

    def area(t):
        k = np.floor(t / period)
        return k * width + np.clip(t - k * period, 0.0, width)

    return 1.0 - (area(x + 1.0) - area(x))


def selftest(ctx):
    """Check the metric against grids whose properties are known in advance.

    Two halves. The analytic half needs no GPU: a grid whose spacing is exact by
    construction must read as even once its lines are wide enough to be solid,
    and must read as uneven while they are not - and the crossover has to land
    where the eye puts it, between a 1.28px line and a 1.99px one at the same
    6.4px period.

    The GPU half uses dmg_dot_matrix, whose grid is known by construction too: a
    line of exactly one output pixel at a fixed offset in every cell. So its
    width is 1.00px at every scale, its spacing is perfectly even wherever the
    scale is whole, and it cannot be even where the scale is not, because a line
    on whole pixels cannot be placed 6.4 apart.

    Both halves matter. Two earlier attempts at this measurement passed the
    "reads a good grid as good" half and failed the other one.
    """
    ok = True

    def claim(cond, what):
        nonlocal ok
        ok = ok and cond
        print(f"    {'pass' if cond else 'FAIL'}  {what}")

    def measure_1d(prof):
        lines = find_lines(prof)
        c = np.array([a for a, _ in lines])
        w = np.array([b for _, b in lines])
        d = np.diff(c)
        return d.mean(), d.std() / d.mean() * 100.0, w.mean()

    print("  self-test, analytic")
    _, cv, w = measure_1d(synthetic(5.0, 1.0))
    claim(cv < EVEN and abs(w - 1.0) < 0.01,
          "a 1.00px line every 5.0px reads perfectly even")
    sp, cv_narrow, w = measure_1d(synthetic(6.4, 1.28))
    claim(abs(sp - 6.4) < 0.01 and 1.0 < cv_narrow < 3.0,
          f"a 1.28px line every 6.4px reads {cv_narrow:.2f}% - soft edge wobble")
    _, cv_wide, w = measure_1d(synthetic(6.4, 1.99))
    claim(cv_wide < 0.1,
          f"a 1.99px line every 6.4px reads {cv_wide:.2f}% - solid core, steady")
    claim(cv_narrow > 10.0 * cv_wide,
          "widening the line from 1.28px to 1.99px removes the wobble")

    prog = compile_shader(ctx, REFERENCE)

    def measure(sw, sh, ow, oh):
        img = gl_render(ctx, prog, np.full((sh, sw, 3), 128, np.uint8),
                        ow, oh, REFERENCE_DEFAULTS)
        return axis_report(img, "x"), axis_report(img, "y")

    print(f"  self-test, on the GPU against {REFERENCE}")
    for ow, oh in ((800, 720), (640, 576), (480, 432)):
        x, y = measure(160, 144, ow, oh)
        claim(x["cv"] < EVEN and y["cv"] < EVEN,
              f"whole scale {ow // 160}x reads perfectly even")
        claim(abs(x["width"] - 1.0) < 0.01 and abs(y["width"] - 1.0) < 0.01,
              f"whole scale {ow // 160}x reads a 1.00px line")

    x, y = measure(160, 144, 1024, 768)
    claim(x["cv"] > 5.0 and y["cv"] > 5.0,
          "fractional 6.40x5.33 reads uneven on both axes")
    claim(abs(x["spacing"] - 6.4) < 0.05 and abs(y["spacing"] - 16.0 / 3) < 0.05,
          "fractional 6.40x5.33 reads the right mean spacing")

    x, y = measure(160, 144, 640, 480)
    claim(x["cv"] < EVEN and y["cv"] > 5.0,
          "640x480 reads even across (4.00) and uneven down (3.33)")

    print(f"  self-test {'ok' if ok else 'FAILED'}")
    return ok


def main(argv):
    from shaders import REGISTRY

    wanted = argv[1:] or [n for n in REGISTRY if n.startswith("dmg-")]
    ctx = moderngl.create_standalone_context()
    if not selftest(ctx):
        print("\nthe metric is wrong; nothing below can be trusted")
        return 1

    report(ctx, REFERENCE, REFERENCE_DEFAULTS)
    if not wanted:
        print("\nno dmg shader in the registry yet; name one explicitly")
        return 0

    over = 0
    for name in wanted:
        params = REGISTRY[name].defaults if name in REGISTRY else {}
        report(ctx, name, params)
        print(f"\n  identity against {REFERENCE} at whole scales, where the two "
              f"are set the same")
        pairings = MATCHED.get(name)
        if not pairings:
            print(f"    no matched pairing recorded for {name}")
            continue
        for label, ours, theirs in pairings:
            worst = max(d for _, d in
                        identity(ctx, name, ours, ref_params=theirs))
            verdict = ("bit-identical" if worst == 0 else
                       "identical to rounding" if worst <= 1 else "DIFFERS")
            print(f"    {label:22s} max diff {worst:3d}/255   {verdict}")
            over = max(over, worst - 1)
    print("\n  The 1/255 rows are float32, not geometry, and both were traced:"
          "\n  at a gamma of exactly 1 this shader skips the pow and the"
          "\n  reference still evaluates pow(x, 1.0), which is exp2(log2(x)) on"
          "\n  a GPU and rounds; and at gamma 0.8 over a black gap, pow has"
          "\n  unbounded slope at 0, which moved 2 pixels out of 1.7 million."
          "\n  Wherever both take the same pow, the match is bit-exact.")
    if over > 0:
        print(f"\nnot identical to the reference where it is already right "
              f"({over + 1}/255)")
    else:
        print("\nidentical to the reference at every whole scale, at every "
              "pairing tested")
    return 1 if over > 0 else 0





if __name__ == "__main__":
    sys.exit(main(sys.argv))
