"""crt-perfect: the properties its versions have actually got wrong.

Each check here has a negative control - the archived version that failed it -
because a property nobody can regress into is a property with no proof. Two of
these defects shipped, and both were found by a person looking at a screen while
every number in the harness stayed green.
"""

import numpy as np
import pytest

from conftest import CASES, border_grid, flat
from core.gpu import gl_render, program
from models.registry import REGISTRY

pytestmark = pytest.mark.gpu

CURRENT = "crt-perfect-v10.glsl"
FLAT = "crt-perfect.glsl"
CURVED = ["crt-perfect-v6.glsl", "crt-perfect-v8.glsl",
          "crt-perfect-v9.glsl", "crt-perfect-v10.glsl"]
# Normalised its warp by the corner value, which put the entire image border
# off-screen. It is kept as the control for the border check.
CROPS_THE_BORDER = "crt-perfect-v7.glsl"
# Lifted the pattern pitch by the frame's worst magnification, which rescaled
# the pattern everywhere: 240 source lines came out as 201 scanlines.
BREAKS_THE_LOCK = ["crt-perfect-v8.glsl", "crt-perfect-v9.glsl"]


def _render(ctx, progs, name, src, ow, oh, **over):
    p = dict(REGISTRY[name].defaults, **over)
    return gl_render(ctx, progs(name), src, ow, oh, p)


def border_retention(ctx, progs, name, k=0.10):
    """How much of the source's coloured border survives switching curvature on.

    Ratio against the same shader with curvature off, so it measures what the
    feature did rather than how big the border happens to be.
    """
    src = border_grid(320, 240)

    def count(curv):
        o = _render(ctx, progs, name, src, 512, 384, cp_curvature=curv)
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
    img = _render(ctx, progs, name, flat(sw, sh), ow, oh, **over)
    prof = img.astype(float).mean(axis=2)[:, ow // 3:2 * ow // 3].mean(axis=1)
    prof = prof - prof.mean()
    mag = np.abs(np.fft.rfft(prof * np.hanning(len(prof))))
    # cycles per output pixel -> cycles per source line
    per_line = np.fft.rfftfreq(len(prof)) * oh / sh
    band = per_line > 0.2
    peak = per_line[band][np.argmax(mag[band])]
    return peak


@pytest.mark.parametrize("name", CURVED)
def test_curvature_keeps_the_source_border(ctx, progs, name):
    assert border_retention(ctx, progs, name) > 0.5


def test_the_cropping_version_still_fails_the_border_check(ctx, progs):
    """v7's defect, kept executable. If this ever passes, the check has rotted."""
    assert border_retention(ctx, progs, CROPS_THE_BORDER) < 0.2


@pytest.mark.parametrize("sw,sh,ow,oh", [(320, 240, 1024, 768),
                                         (256, 224, 1024, 768)])
def test_curvature_keeps_one_scanline_per_source_line(ctx, progs, sw, sh, ow, oh):
    """The pattern stays locked to the source when the image is curved.

    Measured down the centre of the frame, so what it reads is the tube-space
    rate scaled by the centre magnification, 1/(1+k) - a screen-space FFT cannot
    see anything else, because under curvature the screen-space rate genuinely
    varies down the column. A shader holding the lock reads that figure; one
    that rescales the pitch reads lower.

    v8 and v9 read 0.771 against v10's 0.921 here, which is the defect: they
    lifted the pitch by the frame's worst magnification and drew 201 scanlines
    for 240 source lines.
    """
    k = 0.10
    flat_rate = scanline_cycles(ctx, progs, CURRENT, sw, sh, ow, oh,
                                cp_curvature=0.0)
    curved = scanline_cycles(ctx, progs, CURRENT, sw, sh, ow, oh, cp_curvature=k)
    assert flat_rate == pytest.approx(1.0, abs=0.05)
    assert curved == pytest.approx(flat_rate / (1.0 + k), rel=0.05)


@pytest.mark.parametrize("name", BREAKS_THE_LOCK)
def test_the_rescaling_versions_still_fail_the_lock_check(ctx, progs, name):
    """v8 and v9 drew 201 scanlines for 240 source lines. Kept as the control."""
    k = 0.10
    curved = scanline_cycles(ctx, progs, name, 320, 240, 1024, 768,
                             cp_curvature=k)
    assert curved < 0.9 / (1.0 + k)


@pytest.mark.parametrize("name", CURVED)
def test_curvature_off_is_the_flat_shader(ctx, progs, name):
    """Disabling a feature must give back exactly the shader without it.

    v10 is bit-identical here; the earlier ones differ by rounding, so this
    allows one level rather than demanding equality.
    """
    src = border_grid(320, 240)
    p = dict(REGISTRY[name].defaults)
    p.pop("cp_curvature", None)
    a = gl_render(ctx, progs(FLAT), src, 512, 384,
                  {k: v for k, v in p.items() if k in REGISTRY[FLAT].defaults})
    b = _render(ctx, progs, name, src, 512, 384, cp_curvature=0.0)
    assert np.abs(a.astype(int) - b.astype(int)).max() <= 1


def test_the_current_version_is_exactly_the_flat_shader_when_off(ctx, progs):
    """Stronger than the above, and only v10 earns it: 0/255, not 1/255."""
    src = border_grid(320, 240)
    base = dict(REGISTRY[FLAT].defaults)
    a = gl_render(ctx, progs(FLAT), src, 512, 384, base)
    b = gl_render(ctx, progs(CURRENT), src, 512, 384,
                  dict(base, cp_curvature=0.0))
    assert np.abs(a.astype(int) - b.astype(int)).max() == 0
