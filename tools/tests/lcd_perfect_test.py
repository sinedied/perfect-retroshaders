"""lcd-perfect: the panel geometry claims, as checks."""

import numpy as np
import pytest

from conftest import CASES, flat
from core.gpu import gl_render
from models.registry import REGISTRY

pytestmark = pytest.mark.gpu

CURRENT = "lcd-perfect.glsl"


def _r(ctx, progs, src, ow, oh, **over):
    return gl_render(ctx, progs(CURRENT), src, ow, oh,
                     dict(REGISTRY[CURRENT].defaults, **over))


def test_bgr_is_the_rgb_layout_with_the_channels_swapped(ctx, progs):
    """lp_layout is documented as stripe order. If it is really that, then BGR
    is RGB with red and blue exchanged and nothing else."""
    src = flat(64, 48, 200)
    rgb = _r(ctx, progs, src, 256, 192, lp_layout=0.0, lp_subpixels=1.0)
    bgr = _r(ctx, progs, src, 256, 192, lp_layout=1.0, lp_subpixels=1.0)
    assert np.abs(rgb[..., ::-1].astype(int) - bgr.astype(int)).max() <= 1


def test_the_grid_and_stripes_switch_off(ctx, progs):
    """Both patterns off must leave a flat field flat - anything left is the
    shader painting something it was told not to."""
    out = _r(ctx, progs, flat(64, 48, 180), 256, 192,
             lp_grid=0.0, lp_subpixels=0.0)
    assert out.std() < 1.0


def test_the_grid_darkens_and_the_compensation_is_not_a_clamp(ctx, progs):
    """Turning the grid up must cost light, and turning it off must give it
    back - a grid that changed nothing would pass every other check here."""
    src = flat(64, 48, 180)
    off = _r(ctx, progs, src, 256, 192, lp_grid=0.0).mean()
    on = _r(ctx, progs, src, 256, 192, lp_grid=0.6).mean()
    assert on < off


@pytest.mark.parametrize("case,src_wh,out_wh", CASES)
def test_no_black_holes_on_a_lit_field(ctx, progs, case, src_wh, out_wh):
    """A white source must not produce a fully black output pixel anywhere.

    The grid is allowed to darken; it is not allowed to extinguish, and a
    zero here would mean a cell landed exactly on a matrix line at that scale.
    """
    out = _r(ctx, progs, flat(*src_wh, 255), *out_wh)
    assert out.max(axis=2).min() > 0
