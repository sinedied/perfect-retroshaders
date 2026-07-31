"""pixel-perfect: a scaler with a colour grade bolted on top.

The grade's whole claim is that it costs nothing when it is neutral, which is
only true if neutral really is a no-op. That is a property, not a comment.
The neutral half is checked in contracts.py against the plain scaler; this is
the other half, without which a control that never changed anything would pass.
"""

import numpy as np

import common as c

CURRENT = "pixel-perfect-v6.glsl"

MOVED = [("pp_brightness", 1.0, 1.4),
         ("pp_contrast", 1.0, 1.4),
         ("pp_saturation", 1.0, 0.0),
         ("pp_gamma", 1.0, 0.7),
         ("pp_temperature", 0.0, 0.5),
         ("pp_tint", 0.0, 0.5)]


def _colour(w=64, h=48):
    """Has to carry colour, not just level. Flat grey has no saturation to
    remove, so pp_saturation looked broken against it - the test was wrong,
    not the shader."""
    src = np.zeros((h, w, 3), np.uint8)
    src[..., 0], src[..., 1], src[..., 2] = 200, 90, 40
    return src


def run(names, ctx, progs, report, cases=None):
    src = _colour()
    for param, neutral, moved in MOVED:
        a = c.render(ctx, progs, CURRENT, src, 256, 192, **{param: neutral})
        b = c.render(ctx, progs, CURRENT, src, 256, 192, **{param: moved})
        d = int(np.abs(a.astype(int) - b.astype(int)).max())
        report.check(d > 1, f"pixel {param} actually does something",
                     f"{d}/255 between {neutral:g} and {moved:g}")

    out = c.render(ctx, progs, CURRENT, src, 256, 192, pp_saturation=0.0)
    spread = int((out.max(axis=2).astype(int) - out.min(axis=2)).max())
    report.check(spread <= 1, "pixel saturation 0 is grey",
                 f"{spread}/255 of colour left")
    return report
