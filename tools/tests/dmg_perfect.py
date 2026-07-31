"""dmg-perfect: a negative display, where the sign of everything is reversed."""

import numpy as np

import common as c

CURRENT = "dmg-perfect-v8.glsl"


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

    src = c.flat(32, 24, 200)
    a = c.render(ctx, progs, CURRENT, src, 256, 192)
    b = c.render(ctx, progs, CURRENT, src, 256, 192,
                 dp_red=1.0, dp_green=1.0, dp_blue=1.0)
    d = int(np.abs(a.astype(int) - b.astype(int)).max())
    report.check(d == 0, "dmg neutral channel gains change nothing", f"{d}/255")
    return report
