"""Contracts every shader here has to keep, regardless of what it draws.

These are the claims AGENTS.md used to make in prose. Prose does not fail when a
shader stops honouring it - crt-perfect-v7 cropped the whole image border away
while every check in the repo stayed green, and it was caught by a person
looking at a screenshot. Anything asserted about *all* shaders belongs here.
"""

import numpy as np
import pytest

from conftest import CASES, SHIPPING, border_grid, checkerboard, flat
from core import manifest
from core.gpu import gl_render
from core.shader_source import pragma_defaults
from models.registry import REGISTRY

pytestmark = pytest.mark.gpu


def test_manifest_matches_disk():
    assert manifest.check() == []


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_model_defaults_match_the_shader(name):
    """A model that disagrees with its shader is testing a different shader.

    gl_check feeds one dict of parameters to both sides, so a drift here is
    invisible there: the two implementations agree perfectly about a
    configuration nobody runs.
    """
    declared = pragma_defaults(name)
    if not declared:
        pytest.skip("no #pragma parameters")
    model = REGISTRY[name].defaults
    assert set(declared) == set(model)
    for k in declared:
        assert declared[k] == pytest.approx(model[k]), k


@pytest.mark.parametrize("name", SHIPPING)
def test_no_nan_at_parameter_endpoints(ctx, progs, name):
    """Every parameter driven to each end of its declared range still renders.

    A uniform at an endpoint has already produced NaN here: pow(0, k) is
    undefined and turned whole scanline rows black on a real driver, and a
    parameter reaching a divisor made every pixel NaN. Both look like a black
    screen, not like an error.
    """
    ranges = _ranges(name)
    src = checkerboard(64, 48)
    base = dict(REGISTRY[name].defaults)
    for param, (lo, hi) in ranges.items():
        for value in (lo, hi):
            out = gl_render(ctx, progs(name), src, 256, 192,
                            dict(base, **{param: value}),
                            filter_linear=manifest.sampler(name) == manifest.LINEAR)
            assert np.isfinite(out).all(), f"{param}={value} produced non-finite output"
            assert out.max() > 0, f"{param}={value} rendered a black frame"


@pytest.mark.parametrize("name", SHIPPING)
def test_output_covers_the_frame(ctx, progs, name):
    """A shader that leaves the screen black somewhere it should not.

    Curvature is allowed rounded corners; nothing else may drop pixels, and even
    curvature has to reach every edge midpoint.
    """
    out = gl_render(ctx, progs(name), flat(320, 240, 255), 512, 384,
                    dict(REGISTRY[name].defaults),
                    filter_linear=manifest.sampler(name) == manifest.LINEAR)
    lum = out.max(axis=2)
    h, w = lum.shape
    assert lum[h // 2, 0] > 0 and lum[h // 2, -1] > 0, "left/right edge is black"
    assert lum[0, w // 2] > 0 and lum[-1, w // 2] > 0, "top/bottom edge is black"


@pytest.mark.parametrize("name", SHIPPING)
def test_every_source_border_survives(ctx, progs, name):
    """All four edges of the *source* still appear somewhere in the output.

    This is the crt-perfect-v7 defect as an assertion. It normalised its warp by
    the corner value, which put the whole border off-screen: the image looked
    plausible, 89.8% of the source was gone, and no measurement noticed.
    """
    src = border_grid(320, 240)
    out = gl_render(ctx, progs(name), src, 512, 384,
                    dict(REGISTRY[name].defaults),
                    filter_linear=manifest.sampler(name) == manifest.LINEAR)
    red = (out[..., 0].astype(int) - out[..., 2]) > 40      # top/bottom edges
    blue = (out[..., 2].astype(int) - out[..., 0]) > 40     # left/right edges
    assert red.any(), "the source's top/bottom border is nowhere in the output"
    assert blue.any(), "the source's left/right border is nowhere in the output"


def _ranges(name):
    """min/max for each #pragma parameter of a shader."""
    import re

    from core.paths import shader_path

    out = {}
    for line in open(shader_path(name)):
        m = re.match(r'#pragma parameter\s+(\w+)\s+"[^"]*"\s+'
                     r'(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)', line)
        if m:
            out[m.group(1)] = (float(m.group(3)), float(m.group(4)))
    return out
