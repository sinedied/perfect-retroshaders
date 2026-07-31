"""lcd-perfect: the panel geometry claims, as checks."""

import numpy as np

import common as c

CURRENT = "lcd-perfect-v3.glsl"


def run(names, ctx, progs, report, cases=None):
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
