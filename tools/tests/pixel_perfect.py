"""pixel-perfect: a scaler with a colour grade bolted on top.

The grade's whole claim is that it costs nothing when it is neutral, which is
only true if neutral really is a no-op. That is a property, not a comment.
The neutral half is checked in contracts.py against the plain scaler; this is
the other half, without which a control that never changed anything would pass.
"""

import numpy as np

import common as c

FAMILY = "pixel-perfect"

# The two halves of the grade, as they appear in the shader. Used to build the
# negative control by swapping them back.
BALANCE = """        col *= 1.0 + pp_temperature * vec3(1.0, 0.0, -1.0)
                   + pp_tint        * vec3(-0.5, 1.0, -0.5);

"""
# Where the folded mix starts, matched by its opening rather than quoted whole:
# the right-hand side changes with the version - v7 folds brightness into it,
# v2 of the turbo line takes brightness out and gives it to the exponent - and
# quoting it in full made this control assert its way out of the suite the first
# time that happened.
MIX_PREFIX = "        float ga = "
# Where the folded mix ends. Anchoring the control here rather than on the
# clamp keeps it working across versions: v6 clamped inside the grade guard,
# v7 clamps once at the end, so the clamp line is not a stable landmark.
END_OF_MIX = """            + (dot(col, LUMA) * (ga * (1.0 - pp_saturation)) + gb);"""

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


def run(names, ctx, progs, report, cases=None, family=FAMILY):
    CURRENT = c.current(family)
    src = _colour()
    for param, neutral, moved in MOVED:
        a = c.render(ctx, progs, CURRENT, src, 256, 192, **{param: neutral})
        b = c.render(ctx, progs, CURRENT, src, 256, 192, **{param: moved})
        d = int(np.abs(a.astype(int) - b.astype(int)).max())
        report.check(d > 1, f"pixel {param} actually does something",
                     f"{d}/255 between {neutral:g} and {moved:g}")

    # Saturation 0 means monochrome, and it has to survive a balance being set:
    # the two controls run in the same guarded block, so their order decides
    # whether one undoes the other. With the balance applied last - which is how
    # v6 shipped at first, and what pixel-perfect-v5 still does - a tint puts
    # colour straight back into the image saturation had just flattened, and
    # (200, 90, 40) came out (82, 165, 82) instead of grey.
    for label, extra in (("", {}),
                         (" with a tint", {"pp_tint": 0.5}),
                         (" with a temperature", {"pp_temperature": 0.5})):
        out = c.render(ctx, progs, CURRENT, src, 256, 192,
                       pp_saturation=0.0, **extra)
        spread = int((out.max(axis=2).astype(int) - out.min(axis=2)).max())
        report.check(spread <= 1, f"pixel saturation 0 is grey{label}",
                     f"{spread}/255 of colour left")

    # The control has to be built rather than borrowed: no archived version has
    # these parameters at all, so there is nothing on disk that fails this. The
    # order is swapped in the source and compiled on the spot, which is the only
    # way to show the check is measuring the order and not something else.
    src_txt = c.read(CURRENT)
    mix = next((l for l in src_txt.split("\n") if l.startswith(MIX_PREFIX)), None)
    assert mix is not None and src_txt.count(BALANCE) == 1 \
        and src_txt.count(mix) == 1 and src_txt.count(END_OF_MIX) == 1, \
        "the grade block moved; fix the control"
    swapped = src_txt.replace(BALANCE + mix, mix)
    swapped = swapped.replace(END_OF_MIX,
                              END_OF_MIX + "\n\n" + BALANCE.rstrip())
    assert swapped != src_txt
    prog = ctx.program(vertex_shader=c.stage_source(swapped, "vert"),
                       fragment_shader=c.stage_source(swapped, "frag"))
    out = c.draw(ctx, prog, src, 256, 192,
                 dict(c.defaults(CURRENT), pp_saturation=0.0, pp_tint=0.5))
    spread = int((out.max(axis=2).astype(int) - out.min(axis=2)).max())
    report.check(spread > 1,
                 "control: balancing after the mix does let colour through",
                 f"{spread}/255 of colour left")
    return report
