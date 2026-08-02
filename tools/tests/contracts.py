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

    # A release is a byte copy of an iteration, so every tool must measure the
    # two the same way. This is checked on the raw declaration rather than
    # through a render, because the failure it guards against was invisible in
    # the output: the release lost its `pattern` key, the moire band was then
    # derived on the wrong rule, and the copy scored 5.823 against its source's
    # 0.365 while both files were identical on disk.
    for fam in c.families():
        rel, src = c.released(fam), c.current(fam)
        if rel is None:
            continue
        shared = [k for k in c.declared(src)
                  if k not in ("name", "role", "source")]
        differ = [k for k in shared
                  if c.declared(rel).get(k) != c.declared(src).get(k)]
        report.check(not differ, f"{rel} is measured like {src}",
                     f"differs on {differ}" if differ else "")

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
    # A `neutral` block that omits a parameter silently tests less than it
    # claims. Rather than keep a hand-written list of which omissions are fine -
    # which would rot the moment a parameter gained an effect - each one is
    # proved irrelevant: with the neutral block applied, sweeping it to either
    # end of its range must change nothing at all.
    src = c.scene(320, 240)
    for name in names:
        neutral = c.declared(name).get("neutral")
        if neutral is None:
            continue
        ref = c.render(ctx, progs, name, src, 1024, 768, **neutral)
        live = []
        for param, (_lab, _d, lo, hi, _st) in c.parameters(name).items():
            if param in neutral:
                continue
            for v in (lo, hi):
                out = c.render(ctx, progs, name, src, 1024, 768,
                               **dict(neutral, **{param: v}))
                if m.worst_diff(ref, out) > c.TOLERANCE:
                    live.append(f"{param}={v:g}")
        report.check(not live, f"{name} neutral block covers everything that acts",
                     f"still changes the picture: {', '.join(live)}"
                     if live else "")

    base = c.SCALER_REFERENCE
    for name in names:
        neutral = c.declared(name).get("neutral")
        if neutral is None or name == base:
            continue
        # A shader that does no scaling has its own anchor below; comparing it
        # to the plain scaler would only prove it is not one.
        if c.declared(name).get("passthrough"):
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

    # The mini line's anchor. These draw a panel and nothing else, so the thing
    # to prove is that they are TRANSPARENT: sitting behind a scaler, at 1:1 and
    # with every pattern off, the picture has to come through untouched.
    #
    # Checked at 1:1 rather than across the matrix on purpose. Standalone they
    # are whatever their sampler does to an upscale, which is a property of the
    # sampler and not of the shader; behind a scaler - which is what they are
    # for - 1:1 is the only geometry they ever see.
    for name in names:
        if not c.declared(name).get("passthrough"):
            continue
        neutral = c.declared(name).get("neutral") or {}
        worst, at = 0, ""
        for sw, sh in ((320, 240), (256, 224), (480, 272)):
            src = c.scene(sw, sh)
            out = c.render(ctx, progs, name, src, sw, sh, **neutral)
            d = int(np.abs(out.astype(int) - src.astype(int)).max())
            if d > worst:
                worst, at = d, f"{sw}x{sh}"
        report.check(worst <= c.TOLERANCE, f"{name} neutral passes the picture through",
                     f"worst {worst}/255 at {at}")

    # And the other end of the chain: the plain scaler against a third party.
    worst, at = 0.0, ""
    for case in cases:
        d = m.against_pixellate(ctx, progs, base, case)
        if d > worst:
            worst, at = d, c.golden_key(case)
    report.check(worst <= c.TOLERANCE, f"{base} is the vendored pixellate",
                 f"worst {worst:.0f}/255 at {at}")
    return report
