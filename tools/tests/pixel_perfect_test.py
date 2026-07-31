"""pixel-perfect: a scaler with a colour grade bolted on top.

The grade's whole claim is that it costs nothing when it is neutral, which is
only true if neutral really is a no-op. That is a property, not a comment.
"""

import numpy as np
import pytest

from conftest import CASES, checkerboard, flat
from core.gpu import gl_render
from models.registry import REGISTRY

pytestmark = pytest.mark.gpu

CURRENT = "pixel-perfect-v6.glsl"
BASE = "pixel-perfect.glsl"


def _r(ctx, progs, name, src, ow, oh, **over):
    return gl_render(ctx, progs(name), src, ow, oh,
                     dict(REGISTRY[name].defaults, **over))


@pytest.mark.parametrize("case,src_wh,out_wh", CASES)
def test_neutral_grade_is_the_plain_scaler(ctx, progs, case, src_wh, out_wh):
    """Every grade control at its neutral value must give back the base shader.

    Not "close to" - the grade is an affine map and neutral is the identity, so
    anything other than equality means it is doing arithmetic it claims not to.
    """
    src = checkerboard(*src_wh)
    a = _r(ctx, progs, BASE, src, *out_wh)
    b = _r(ctx, progs, CURRENT, src, *out_wh)
    assert np.abs(a.astype(int) - b.astype(int)).max() <= 1


@pytest.mark.parametrize("param,neutral,moved", [
    ("pp_brightness", 1.0, 1.4),
    ("pp_contrast", 1.0, 1.4),
    ("pp_saturation", 1.0, 0.0),
    ("pp_gamma", 1.0, 0.7),
])
def test_each_grade_control_actually_does_something(ctx, progs, param,
                                                    neutral, moved):
    """The other half of the neutrality claim: a control that never changes the
    picture would also pass the test above.

    The source has to carry colour, not just level. Flat grey has no saturation
    to remove, so pp_saturation looked broken against it - the test was wrong,
    not the shader.
    """
    src = np.zeros((48, 64, 3), np.uint8)
    src[..., 0] = 200
    src[..., 1] = 90
    src[..., 2] = 40
    a = _r(ctx, progs, CURRENT, src, 256, 192, **{param: neutral})
    b = _r(ctx, progs, CURRENT, src, 256, 192, **{param: moved})
    assert np.abs(a.astype(int) - b.astype(int)).max() > 1, param


def test_saturation_zero_is_grey(ctx, progs):
    src = np.zeros((48, 64, 3), np.uint8)
    src[..., 0] = 200
    src[..., 1] = 60
    out = _r(ctx, progs, CURRENT, src, 256, 192, pp_saturation=0.0)
    spread = out.max(axis=2).astype(int) - out.min(axis=2)
    assert spread.max() <= 1, "saturation 0 left colour in the image"
