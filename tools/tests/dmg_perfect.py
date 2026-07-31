"""dmg-perfect: a negative display, where the sign of everything is reversed."""

import numpy as np

import common as c

CURRENT = "dmg-perfect-v9.glsl"


def _palette(w=64, h=48):
    """A balance has nothing to shift on a neutral grey, so the source has to
    carry colour. This is roughly a DMG green: dark, and nowhere near neutral,
    which is the case the control exists for."""
    src = np.zeros((h, w, 3), np.uint8)
    src[..., 0], src[..., 1], src[..., 2] = 100, 130, 60
    return src


def run(names, ctx, progs, report, cases=None):
    # A cast shadow has a direction, and getting it backwards looks like a
    # lighting bug rather than an error. One driven cell on the substrate: the
    # darkening the shadow adds must sit below and right of it.
    src = c.flat(32, 24, 255)
    src[12, 16] = 0
    off = c.render(ctx, progs, CURRENT, src, 512, 384,
                   dp_shadow=0.0).astype(float).mean(axis=2)
    on = c.render(ctx, progs, CURRENT, src, 512, 384,
                  dp_shadow=0.5).astype(float).mean(axis=2)
    darker = off - on
    ys, xs = np.nonzero(darker > darker.max() * 0.3)
    cy, cx = 384 * 12.5 / 24, 512 * 16.5 / 32
    report.check(ys.size and ys.mean() > cy and xs.mean() > cx,
                 "dmg shadow falls down and right",
                 f"centroid ({xs.mean():.0f}, {ys.mean():.0f}) against the cell "
                 f"at ({cx:.0f}, {cy:.0f})" if ys.size else "changed nothing")

    report.check(c.defaults(CURRENT)["dp_shadow"] == 0.0,
                 "dmg shadow is off by default")

    # On a negative display the substrate is the lit state, so a blank screen
    # has no cells driven and nothing may cast a shadow onto it.
    src = c.flat(32, 24, 255)
    a = c.render(ctx, progs, CURRENT, src, 256, 192, dp_shadow=0.0)
    b = c.render(ctx, progs, CURRENT, src, 256, 192, dp_shadow=0.6)
    d = int(np.abs(a.astype(int) - b.astype(int)).max())
    report.check(d <= c.TOLERANCE, "dmg undriven cells cast nothing", f"{d}/255")

    src = _palette()
    a = c.render(ctx, progs, CURRENT, src, 256, 192)
    b = c.render(ctx, progs, CURRENT, src, 256, 192,
                 dp_temperature=0.0, dp_tint=0.0)
    d = int(np.abs(a.astype(int) - b.astype(int)).max())
    report.check(d == 0, "dmg neutral balance changes nothing", f"{d}/255")

    # A control that never moved anything would pass the check above, so both
    # axes have to be shown to do something - and to do the RIGHT thing. A
    # balance wired to the wrong channel still reads as "different".
    for param, moved in (("dp_temperature", 0.5), ("dp_tint", 0.5)):
        b = c.render(ctx, progs, CURRENT, src, 256, 192, **{param: moved})
        d = int(np.abs(a.astype(int) - b.astype(int)).max())
        report.check(d > 1, f"dmg {param} actually does something",
                     f"{d}/255 between 0 and {moved:g}")

    warm = c.render(ctx, progs, CURRENT, src, 256, 192, dp_temperature=0.5)
    dr, db = (warm.astype(float) - a).mean(axis=(0, 1))[[0, 2]]
    report.check(dr > 1 and db < -1, "dmg warm raises red and lowers blue",
                 f"red {dr:+.1f}, blue {db:+.1f}")

    magenta = c.render(ctx, progs, CURRENT, src, 256, 192, dp_tint=0.5)
    dg = (magenta.astype(float) - a).mean(axis=(0, 1))[1]
    report.check(dg > 1, "dmg tint raises green", f"green {dg:+.1f}")
    return report
