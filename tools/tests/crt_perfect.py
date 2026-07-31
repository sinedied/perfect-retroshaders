"""crt-perfect: the properties its versions have actually got wrong.

Each check has a negative control - the archived version that failed it -
because a property nobody can regress into is a property with no proof. Two of
these defects shipped, and both were found by a person looking at a screen while
every number in the harness stayed green.
"""

import numpy as np

import common as c

FLAT = "crt-perfect.glsl"
CURRENT = "crt-perfect-v10.glsl"
CURVED = ["crt-perfect-v6.glsl", "crt-perfect-v8.glsl",
          "crt-perfect-v9.glsl", "crt-perfect-v10.glsl"]
# Normalised its warp by the corner value, which put the entire image border
# off-screen. Kept as the control for the border check.
CROPS_THE_BORDER = "crt-perfect-v7.glsl"
# Lifted the pattern pitch by the frame's worst magnification, which rescaled
# the pattern everywhere: 240 source lines came out as 201 scanlines.
BREAKS_THE_LOCK = ["crt-perfect-v8.glsl", "crt-perfect-v9.glsl"]

K = 0.10


def border_retention(ctx, progs, name, k=K):
    """How much of the source's coloured border survives switching curvature on.

    A ratio against the same shader with curvature off, so it measures what the
    feature did rather than how big the border happens to be.
    """
    src = c.border_grid(320, 240)

    def count(curv):
        o = c.render(ctx, progs, name, src, 512, 384, cp_curvature=curv)
        return (((o[..., 0].astype(int) - o[..., 2]) > 40).sum(),
                ((o[..., 2].astype(int) - o[..., 0]) > 40).sum())

    r0, b0 = count(0.0)
    r1, b1 = count(k)
    return min(r1 / max(r0, 1), b1 / max(b0, 1))


def scanline_cycles(ctx, progs, name, sw, sh, ow, oh, **over):
    """Scanline cycles per source line, read off the render.

    Measured, not computed: the pitch formula is the thing under test, so
    deriving the answer from it would assert nothing.

    The source is a flat field on purpose. Alternating source rows look like the
    obvious choice - they are what scanlines land on - but a square wave at half
    the line frequency has a second harmonic sitting exactly on the scanline
    frequency, so the measurement cannot tell the pattern from the content. On a
    flat field the only vertical periodicity in the output is the shader's own.
    """
    img = c.render(ctx, progs, name, c.flat(sw, sh), ow, oh, **over)
    prof = img.astype(float).mean(axis=2)[:, ow // 3:2 * ow // 3].mean(axis=1)
    prof = prof - prof.mean()
    mag = np.abs(np.fft.rfft(prof * np.hanning(len(prof))))
    per_line = np.fft.rfftfreq(len(prof)) * oh / sh  # cycles per source line
    band = per_line > 0.2
    return per_line[band][np.argmax(mag[band])]


def run(names, ctx, progs, report, cases=None):
    for name in CURVED:
        r = border_retention(ctx, progs, name)
        report.check(r > 0.5, f"{name} keeps the source border under curvature",
                     f"{r:.2f} of it survives")

    # v7's defect, kept executable. If this ever passes, the check has rotted.
    r = border_retention(ctx, progs, CROPS_THE_BORDER)
    report.check(r < 0.2, f"control: {CROPS_THE_BORDER} still crops the border",
                 f"{r:.2f} survives, want < 0.2")

    # The pattern stays locked to the source when the image is curved. Measured
    # down the centre of the frame, so what it reads is the tube-space rate
    # scaled by the centre magnification 1/(1+k) - a screen-space FFT cannot see
    # anything else, because under curvature the screen-space rate genuinely
    # varies down the column.
    for sw, sh, ow, oh in ((320, 240, 1024, 768), (256, 224, 1024, 768)):
        flat_rate = scanline_cycles(ctx, progs, CURRENT, sw, sh, ow, oh,
                                    cp_curvature=0.0)
        curved = scanline_cycles(ctx, progs, CURRENT, sw, sh, ow, oh,
                                 cp_curvature=K)
        want = flat_rate / (1.0 + K)
        report.check(abs(flat_rate - 1.0) < 0.05 and abs(curved - want) < 0.05 * want,
                     f"{CURRENT} keeps one scanline per source line "
                     f"at {sw}x{sh}->{ow}x{oh}",
                     f"flat {flat_rate:.3f}, curved {curved:.3f}, want {want:.3f}")

    for name in BREAKS_THE_LOCK:
        curved = scanline_cycles(ctx, progs, name, 320, 240, 1024, 768,
                                 cp_curvature=K)
        report.check(curved < 0.9 / (1.0 + K),
                     f"control: {name} still rescales the pattern",
                     f"{curved:.3f} cycles per source line, want < "
                     f"{0.9 / (1.0 + K):.3f}")

    # Disabling a feature must give back the shader without it. v10 is
    # bit-identical; the earlier ones differ by rounding.
    src = c.border_grid(320, 240)
    base = c.defaults(FLAT)
    a = c.render(ctx, progs, FLAT, src, 512, 384, params=base)
    for name in CURVED:
        p = {k: v for k, v in c.defaults(name).items() if k in base}
        b = c.render(ctx, progs, name, src, 512, 384,
                     params=dict(p, cp_curvature=0.0))
        ref = c.render(ctx, progs, FLAT, src, 512, 384, params=p)
        d = int(np.abs(ref.astype(int) - b.astype(int)).max())
        report.check(d <= c.TOLERANCE, f"{name} with curvature off is the flat "
                     f"shader", f"{d}/255")

    b = c.render(ctx, progs, CURRENT, src, 512, 384,
                 params=dict(base, cp_curvature=0.0))
    d = int(np.abs(a.astype(int) - b.astype(int)).max())
    report.check(d == 0, f"{CURRENT} with curvature off is EXACTLY the flat "
                 f"shader", f"{d}/255")
    return report
