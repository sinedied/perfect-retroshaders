"""Shared fixtures.

The GL context is session-scoped because creating one costs far more than any
single render, and every test that needs a GPU wants the same one.

Tests are tiered with markers so the default run stays quick enough to sit in a
loop:

    pytest                          fast: contracts, defaults, the current
                                    version of each family
    pytest -m ""                    everything, archive included
    pytest -m slow                  only the long sweeps
    pytest -k crt                   one family

Anything that walks every archived version, supersamples, or renders a full
matrix is marked `slow` and is not in the default run. The point of the default
run is that it is cheap enough to be run every time; if it stops being that,
nobody runs it and the tier has failed.
"""

import numpy as np
import pytest

import moderngl

from core import manifest
from core.gpu import program


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: excluded from the default run")
    config.addinivalue_line("markers", "gpu: needs a GL context")


def pytest_collection_modifyitems(config, items):
    """Default to skipping the slow tier unless -m was given explicitly."""
    if config.option.markexpr:
        return
    skip = pytest.mark.skip(reason="slow tier; run with -m slow or -m ''")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def ctx():
    return moderngl.create_standalone_context()


@pytest.fixture(scope="session")
def progs(ctx):
    """Compiled programs, built once and shared. Compiling is the slow part."""
    cache = {}

    def get(name):
        if name not in cache:
            cache[name] = program(ctx, name)
        return cache[name]

    return get


def flat(w=320, h=240, level=128):
    return np.full((h, w, 3), level, np.uint8)


def checkerboard(w=320, h=240):
    yy, xx = np.mgrid[0:h, 0:w]
    return (((yy + xx) % 2) * 255).astype(np.uint8)[..., None].repeat(3, axis=2)


def rows(w=320, h=240, on=200):
    """Alternating source lines - the content a scanline pattern lands on."""
    img = np.zeros((h, w, 3), np.uint8)
    img[::2] = on
    return img


def border_grid(w=320, h=240, step=20):
    """A grid with a differently coloured edge on each side.

    The only pattern that shows what a geometric change did to the *borders*.
    crt-perfect-v7 shipped having cropped its entire border off-screen and every
    number in the harness read perfect.
    """
    img = np.full((h, w, 3), 20, np.uint8)
    img[::step, :] = 255
    img[:, ::step] = 255
    img[0:3, :] = img[-3:, :] = (255, 60, 60)
    img[:, 0:3] = img[:, -3:] = (60, 160, 255)
    return img


# The scale factors that actually matter on the target, including the awkward
# ones. Declared once so a test cannot quietly cover a different set from its
# neighbour, which is how two tools ended up disagreeing about what "all scales"
# meant.
CASES = [
    ("240p -> 1024x768", (320, 240), (1024, 768)),
    ("224p -> 1024x768", (256, 224), (1024, 768)),
    ("PSP  -> 1024x768", (480, 272), (1024, 768)),
    ("GB   -> 1024x768", (160, 144), (1024, 768)),
    ("240p ->  640x480", (320, 240), (640, 480)),
    ("GB   ->  640x480", (160, 144), (640, 480)),
]

CURRENT = [manifest.current(f) for f in manifest.families()]
RELEASED = [manifest.released(f) for f in manifest.families()]
SHIPPING = sorted(set(CURRENT) | set(RELEASED))
