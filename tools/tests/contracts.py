"""Properties every shader here has to keep, whatever it draws.

These were prose in AGENTS.md. Prose does not fail when a shader stops honouring
it: crt-perfect-v7 cropped the whole image border away while every check in the
repo stayed green, and a person looking at a screenshot caught it.

The neutral-reduction check is the one that replaced the numpy twins. Every
shader here is built on the same area-averaging scaler, and pixel-perfect is
proven equal to the vendored pixellate, so turning a shader's effects off and
diffing it against pixel-perfect anchors the whole repo to a third-party
implementation. It costs one render.
"""

import numpy as np

import common as c
import measure as m


def _endpoints(name):
    """Every parameter at each end of its declared range, one at a time."""
    for param, (_label, _default, lo, hi, _step) in c.parameters(name).items():
        for v in (lo, hi):
            yield param, v


def run(names, ctx, progs, report, cases=None):
    cases = cases or c.CASES

    for name in names:
        bad = []
        for param, v in _endpoints(name):
            out = c.render(ctx, progs, name, c.checkerboard(320, 240), 512, 384,
                           **{param: v})
            if not np.isfinite(out).all() or out.max() == 0:
                bad.append(f"{param}={v:g}")
        report.check(not bad, f"{name} survives its parameter endpoints",
                     ", ".join(bad))

    for name in names:
        worst, at = 0, ""
        for case in cases:
            sw, sh, ow, oh = case
            out = c.render(ctx, progs, name, c.flat(sw, sh, 255), ow, oh)
            # A grid may darken. It may not extinguish: a fully black pixel on
            # a white source means a cell landed exactly on a matrix line.
            dark = int(out.max(axis=2).min())
            if dark == 0:
                worst, at = 1, c.golden_key(case)
        report.check(not worst, f"{name} never extinguishes a lit field", at)

    # The scaler anchor. Skipped where a shader declares no neutral setting,
    # which means it has no configuration in which it is just a scaler.
    base = "pixel-perfect.glsl"
    for name in names:
        neutral = c.declared(name).get("neutral")
        if neutral is None or name == base:
            continue
        worst, at = 0.0, ""
        for case in cases:
            sw, sh, ow, oh = case
            src = c.scene(sw, sh)
            a = c.render(ctx, progs, base, src, ow, oh)
            b = c.render(ctx, progs, name, src, ow, oh, **neutral)
            d = m.worst_diff(a, b)
            if d > worst:
                worst, at = d, c.golden_key(case)
        report.check(worst <= c.TOLERANCE, f"{name} neutral is the plain scaler",
                     f"worst {worst:.0f}/255 at {at}")

    # And the other end of the chain: the plain scaler against a third party.
    worst, at = 0.0, ""
    for case in cases:
        d = m.against_pixellate(ctx, progs, base, case)
        if d > worst:
            worst, at = d, c.golden_key(case)
    report.check(worst <= c.TOLERANCE, f"{base} is the vendored pixellate",
                 f"worst {worst:.0f}/255 at {at}")
    return report
