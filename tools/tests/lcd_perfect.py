"""lcd-perfect: the panel geometry claims, as checks."""

import numpy as np

import common as c

# The shader under test is whichever version is current, read from the manifest.
# Naming it here is how this file spent a release testing v4 while v5 shipped:
# the constant was right when it was written and nothing rechecks a constant.
CURRENT = c.current("lcd-perfect")

# The rearrangement claim is about two specific versions and stays pinned to
# them. v4 is v3's arithmetic rearranged, not retuned: the mesh, its box filter
# and the stripes all live on the same angle, so one sine and one cosine of it
# replace four evaluations through the angle-sum identities. That is a claim
# about the picture, so it is checked as one.
REARRANGED = "lcd-perfect-v4.glsl"
PREVIOUS = "lcd-perfect-v3.glsl"

# The controls. These are real lcd-perfect versions with real differences from
# v3, so an equivalence check that cannot tell them apart is not checking
# anything. v2a is the closest - the same sinusoid mesh, before the Nyquist
# fade and the whole-cell period came back - and v1 is the trapezoid aperture.
SUPERSEDED = ["lcd-perfect-v2a.glsl", "lcd-perfect-v1.glsl"]

# Every branch the rewrite touches, not just the defaults. lp_gamma exercises
# the pow() path, lp_min_pitch at 6 forces the N > 1 regime where the period
# spans several cells, and lp_subpixels drives the stripe block that lost its
# two cosines.
SWEEP = [
    {},
    {"lp_grid": 0.0},
    {"lp_grid": 1.0},
    {"lp_balance": 0.0},
    {"lp_balance": 1.0},
    {"lp_subpixels": 0.0},
    {"lp_subpixels": 1.0},
    {"lp_layout": 1.0},
    {"lp_gamma": 0.5},
    {"lp_gamma": 2.0},
    {"lp_min_pitch": 2.0},
    {"lp_min_pitch": 6.0},
    {"lp_grid": 1.0, "lp_subpixels": 1.0, "lp_balance": 1.0},
]


def _worst(ctx, progs, other, cases, sweep, subject=None):
    """Worst 8-bit difference between `subject` and another version."""
    subject = subject or CURRENT
    worst, at = 0, ""
    for case in cases:
        sw, sh, ow, oh = case
        src = c.scene(sw, sh)
        for params in sweep:
            a = c.render(ctx, progs, subject, src, ow, oh, **params)
            b = c.render(ctx, progs, other, src, ow, oh, **params)
            d = int(np.abs(a.astype(int) - b.astype(int)).max())
            if d > worst:
                worst = d
                at = f"{c.golden_key(case)} {params or 'defaults'}"
    return worst, at


def run(names, ctx, progs, report, cases=None):
    cases = cases or c.CASES

    # The rewrite's whole claim: same picture, less arithmetic.
    worst, at = _worst(ctx, progs, PREVIOUS, cases, SWEEP, REARRANGED)
    report.check(worst <= c.TOLERANCE,
                 f"{REARRANGED} is {PREVIOUS} rearranged",
                 f"worst {worst}/255 at {at}")

    # ... and the control, so that check means something. These have to differ
    # by more than the tolerance or the comparison above proves nothing.
    for old in SUPERSEDED:
        seen, at = _worst(ctx, progs, old, cases, [{}], REARRANGED)
        report.check(seen > c.TOLERANCE,
                     f"{old} is NOT {REARRANGED}, so the check can fail",
                     f"worst {seen}/255 at {at}")

    # lp_layout is documented as stripe order. If it really is only that, BGR
    # is RGB with red and blue exchanged and nothing else.
    src = c.flat(64, 48, 200)
    rgb = c.render(ctx, progs, CURRENT, src, 256, 192,
                   lp_layout=0.0, lp_subpixels=1.0)
    bgr = c.render(ctx, progs, CURRENT, src, 256, 192,
                   lp_layout=1.0, lp_subpixels=1.0)
    d = int(np.abs(rgb[..., ::-1].astype(int) - bgr.astype(int)).max())
    report.check(d <= c.TOLERANCE, "lcd BGR is RGB with the channels swapped",
                 f"{d}/255")

    # Both patterns off must leave a flat field flat. Anything left is the
    # shader painting something it was told not to.
    out = c.render(ctx, progs, CURRENT, c.flat(64, 48, 180), 256, 192,
                   lp_grid=0.0, lp_subpixels=0.0)
    report.check(out.std() < 1.0, "lcd patterns switch off",
                 f"std {out.std():.3f}")

    # Turning the grid up must cost light, and turning it off must give it back.
    # A grid that changed nothing would pass every other check here.
    src = c.flat(64, 48, 180)
    off = c.render(ctx, progs, CURRENT, src, 256, 192, lp_grid=0.0).mean()
    on = c.render(ctx, progs, CURRENT, src, 256, 192, lp_grid=0.6).mean()
    report.check(on < off, "lcd grid costs light",
                 f"{on:.1f} lit against {off:.1f} unlit")
    return report
