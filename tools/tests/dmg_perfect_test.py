"""dmg-perfect: a negative display, where the sign of everything is reversed."""

import numpy as np
import pytest

from conftest import CASES, flat
from core import manifest
from core.gpu import gl_render
from models.registry import REGISTRY

pytestmark = pytest.mark.gpu

CURRENT = manifest.current("dmg-perfect")


def _r(ctx, progs, src, ow, oh, **over):
    return gl_render(ctx, progs(CURRENT), src, ow, oh,
                     dict(REGISTRY[CURRENT].defaults, **over))


def test_the_shadow_falls_down_and_right(ctx, progs):
    """A cast shadow has a direction, and getting it backwards looks like a
    lighting bug rather than an error. One lit cell on the substrate: the
    darkening the shadow adds must sit below and right of it."""
    src = flat(32, 24, 255)
    src[12, 16] = 0                                  # one dark cell
    off = _r(ctx, progs, src, 512, 384, dp_shadow=0.0).astype(float).mean(axis=2)
    on = _r(ctx, progs, src, 512, 384, dp_shadow=0.5).astype(float).mean(axis=2)
    darker = off - on
    ys, xs = np.nonzero(darker > darker.max() * 0.3)
    assert ys.size, "dp_shadow changed nothing"
    cy, cx = 384 * 12.5 / 24, 512 * 16.5 / 32
    assert ys.mean() > cy, "the shadow is above the cell"
    assert xs.mean() > cx, "the shadow is left of the cell"


def test_the_shadow_is_off_by_default(ctx, progs):
    assert REGISTRY[CURRENT].defaults["dp_shadow"] == 0.0


def test_undriven_cells_cast_nothing(ctx, progs):
    """On a negative display the substrate is the lit state. A blank screen has
    no cells driven, so nothing may cast a shadow onto it."""
    src = flat(32, 24, 255)
    a = _r(ctx, progs, src, 256, 192, dp_shadow=0.0)
    b = _r(ctx, progs, src, 256, 192, dp_shadow=0.6)
    assert np.abs(a.astype(int) - b.astype(int)).max() <= 1


def test_neutral_channel_gains_change_nothing(ctx, progs):
    src = flat(32, 24, 200)
    a = _r(ctx, progs, src, 256, 192)
    b = _r(ctx, progs, src, 256, 192, dp_red=1.0, dp_green=1.0, dp_blue=1.0)
    assert np.abs(a.astype(int) - b.astype(int)).max() == 0


@pytest.mark.parametrize("case,src_wh,out_wh", CASES)
def test_the_grid_never_extinguishes_the_substrate(ctx, progs, case,
                                                   src_wh, out_wh):
    out = _r(ctx, progs, flat(*src_wh, 255), *out_wh)
    assert out.max(axis=2).min() > 0
