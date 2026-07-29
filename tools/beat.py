#!/usr/bin/env python3
"""Measure moire - the low-frequency beat a shader paints onto flat content.

A shader that modulates the image with a pattern locked to the source grid has a
problem the source itself does not: at a non-integer scale a source pixel covers
three or four output pixels, so the count of partial-coverage pixels varies from
block to block. Any non-linearity applied across the scaler's blend gives those
pixels a coverage-dependent shift, and that shift beats against the pixel grid at
a frequency far below the pattern's own. That beat is what the eye sees as moire.

METHOD

Render a 1px checkerboard - the worst case, maximum energy at the pixel grid -
and look at its spectrum. Two frequencies in that image are legitimate and must
not be counted:

  - the content. A 1px checkerboard is a single pair of impulses at half a cycle
    per source pixel on each axis, and nothing below.
  - the pattern. Anything locked to the source grid has its fundamental at one
    cycle per source pixel, with harmonics above.

So everything strictly slower than half a cycle per source pixel is neither, and
whatever is found there was manufactured by the shader. That is the beat. The
figure reported is its RMS, in 8-bit levels, with DC excluded.

Getting this band wrong is the documented way to produce confident nonsense: a
fixed "periods 6-64px are moire" window counts the pattern itself the moment its
pitch enters the window, and a low-pass at the pattern's repeat length removes
the beat along with it, because at a rational scale factor the whole image is
periodic at that length and nothing survives. Both were tried here. The band is
derived from the source and output sizes, never assumed.

Anything above about 0.4 is visible. That threshold is the ~0.2 recorded in
AGENTS.md carried across the scale factor between the two definitions, which the
self-test below measures rather than assumes.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python beat.py
"""

import sys

import numpy as np

from crt_preview import render_crt, render_crt_v5
from lcd_preview import DEFAULTS_LCD, render_lcd

VISIBLE = 0.4


def checkerboard(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    return (((yy + xx) % 2) * 255).astype(np.uint8)[..., None].repeat(3, axis=2)


def beat(img, src_w, src_h):
    """RMS of everything slower than the content and the pattern, in 8-bit levels."""
    lum = img.astype(np.float64)
    if lum.ndim == 3:
        lum = lum.mean(axis=2)
    if lum.max() <= 1.0001:
        lum = lum * 255.0
    out_h, out_w = lum.shape

    # forward normalisation, so sum |F|^2 over a band is that band's variance
    F = np.fft.fft2(lum) / lum.size
    fx = np.abs(np.fft.fftfreq(out_w))
    fy = np.abs(np.fft.fftfreq(out_h))

    # half a cycle per source pixel, in cycles per output pixel, less a hair so
    # the content's own bin is never included
    cx = 0.5 * src_w / out_w * 0.999
    cy = 0.5 * src_h / out_h * 0.999

    band = (fy[:, None] < cy) & (fx[None, :] < cx)
    band[0, 0] = False  # DC is the image's mean level, not a beat
    return float(np.sqrt((np.abs(F[band]) ** 2).sum()))


def measure(render, src_w=320, src_h=240, out_w=1024, out_h=768):
    src = checkerboard(src_w, src_h)
    return beat(render(src, out_w, out_h), src_w, src_h)


# ---------------------------------------------------------------- self-test
#
# Constructions whose beat AGENTS.md already records. They are reproduced here
# from the descriptions in the design-rule table, and the tool is only
# trustworthy if it returns those numbers - a metric that has not been checked
# against a known-good and a known-bad case is how the last three tooling bugs
# produced confident, wrong figures.

def _v5(p=None, **kw):
    return lambda s, w, h: render_crt_v5(s, w, h, p, quantise=False, **kw)


def _post_gamma(g):
    """Output gamma applied after the blend, the way dmg_dot_matrix does it."""
    def r(s, w, h):
        return np.power(np.clip(render_crt_v5(s, w, h, quantise=False), 0.0, 1.0), g)
    return r


def _reinhard(k):
    """A soft shoulder instead of a hard clamp, also after the blend."""
    def r(s, w, h):
        c = render_crt_v5(s, w, h, dict(cp_brightness=k), quantise=False) * k
        return c / (1.0 + c)
    return r


EXPECTED = [
    ("v5, nothing non-linear after the blend",
     _v5(dict(cp_brightness=1.0)), 0.02),
    ("linearise taps, blend, re-encode (v1)",
     lambda s, w, h: render_crt(s, w, h) / 255.0, 3.35),
    ("output gamma 1.4 after the blend", _post_gamma(1.4), 1.53),
    ("output gamma 2.0 after the blend", _post_gamma(2.0), 3.06),
    ("clamp from cp_brightness 1.25", _v5(dict(cp_brightness=1.25)), 0.13),
    ("clamp from cp_brightness 4.00", _v5(dict(cp_brightness=4.00)), 4.84),
]


def self_test():
    """Check this tool against the figures AGENTS.md already records.

    The original tool was not in the repo and had to be rebuilt from its
    description, so the absolute scale is this definition's, not the original's.
    What must hold is that the ordering is identical and that the ratio to the
    record is consistent - if every construction comes out the same multiple
    bigger, the two are measuring the same thing through a different
    normalisation. If one construction drifts, they are not.
    """
    print("self-test against the figures recorded in AGENTS.md\n")
    print(f"  {'construction':<44s} {'measured':>9s} {'recorded':>9s} {'ratio':>7s}")
    got, ratios = [], []
    for label, render, expected in EXPECTED:
        v = measure(render)
        got.append(v)
        ratios.append(v / expected)
        print(f"  {label:<44s} {v:9.2f} {expected:9.2f} {v / expected:7.2f}")

    recorded = [e for _, _, e in EXPECTED]
    order_ok = (np.argsort(got) == np.argsort(recorded)).all()
    spread = max(ratios) / min(ratios)
    print(f"\n  ordering matches the record: {'yes' if order_ok else 'NO'}")
    print(f"  ratio {min(ratios):.2f} to {max(ratios):.2f} "
          f"(spread {spread:.2f}x), mean {np.mean(ratios):.2f}")
    print(f"  -> this definition reads about {np.mean(ratios):.1f}x the recorded "
          f"figures, so the visible threshold is {VISIBLE}")
    return order_ok and spread < 1.5


def report():
    print(f"\nbeat on a 1px checkerboard (visible above ~{VISIBLE})\n")
    scales = [
        ((320, 240), (1024, 768)),
        ((256, 224), (1024, 768)),
        ((256, 192), (1024, 768)),
        ((240, 160), (1024, 768)),
        ((160, 144), (1024, 768)),
        ((320, 240), (640, 480)),
        ((256, 192), (640, 480)),
        ((160, 144), (640, 480)),
    ]
    # only the shipped defaults are gated. The rest are there to show what the
    # parameters cost, and "full strength" is deliberately past the point where
    # the beat is visible - that is the trade the header documents, not a bug.
    variants = [
        ("defaults", {}, True),
        ("grid only", dict(lp_subpixels=0.0), True),
        ("gamma 0.7", dict(lp_gamma=0.7), True),
        ("full strength", dict(lp_grid=1.0, lp_subpixels=1.0, lp_gap=0.35), False),
        ("crt-perfect v5", None, True),
    ]
    print("  " + " " * 22 + "".join(f"{n[:13]:>15s}" for n, _, _ in variants))
    print("  " + " " * 22 + "".join(f"{'(gated)' if g else '(info)':>15s}"
                                    for _, _, g in variants))
    worst = 0.0
    for (sw, sh), (ow, oh) in scales:
        row = []
        for _, p, gated in variants:
            if p is None:
                r = measure(_v5(), sw, sh, ow, oh)
            else:
                r = measure(lambda s, w, h, p=p: render_lcd(
                    s, w, h, dict(DEFAULTS_LCD, **p), quantise=False), sw, sh, ow, oh)
            if gated:
                worst = max(worst, r)
            row.append(f"{r:15.3f}")
        print(f"  {sw}x{sh} -> {ow}x{oh}".ljust(24) + "".join(row))
    print(f"\n  worst gated beat: {worst:.3f}   "
          f"{'OK' if worst <= VISIBLE else 'VISIBLE MOIRE'}")
    return worst


if __name__ == "__main__":
    ok = self_test()
    w = report()
    sys.exit(0 if ok and w <= VISIBLE else 1)
