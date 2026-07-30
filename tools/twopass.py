#!/usr/bin/env python3
"""The two-pass pipeline dmg-perfect-v2 reproduces, built literally, as ground
truth.

Draw the dot matrix at a whole scale factor - where a 1px line is exactly a 1px
line and nothing is soft - then area-average that up to the output. That is what
a frontend does with `dmg_dot_matrix` at integer scaling plus a `pixellate` pass,
and it is the arrangement this shader was asked to match, because at a fractional
scale it holds together where a single naive pass does not.

Both halves are linear, so the composite has a closed form and dmg-perfect-v2
evaluates it directly in one pass. This module exists to check that claim rather
than assert it: it builds the intermediate image for real, resamples it with an
exact box filter written from scratch, and diffs.

Nothing here shares code with the shader's model on purpose. An independent
implementation is only worth having if it is independent.

Two things it deliberately does not vary:

  gamma       held at 1.00. The real two-pass applies its curve in pass one, so
              *before* the upscale, where dmg-perfect applies it after - which it
              must, to stay bit-identical to dmg_dot_matrix at a whole scale.
              The two placements agree exactly wherever pass two is an identity,
              which is every whole scale, so comparing them anywhere else would
              be measuring that known difference rather than the geometry.

  gap width   a whole number of pixels. The intermediate has no sub-pixel
              detail by construction, so a fractional line has no meaning in it.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python twopass.py [shader ...]
"""

import sys

import numpy as np

import moderngl
from gl_check import gl_render
from grid import compile_shader

CASES = [
    # label, source, output, and whether the frontend letterboxed or stretched
    ("GB 5x integer", (160, 144), (800, 720)),
    ("GB 4x integer", (160, 144), (640, 576)),
    ("GB 3x integer", (160, 144), (480, 432)),
    ("GB aspect 1024x768", (160, 144), (853, 768)),
    ("GB fill   1024x768", (160, 144), (1024, 768)),
    ("GB aspect  640x480", (160, 144), (533, 480)),
    ("GB fill    640x480", (160, 144), (640, 480)),
]


def fit_scale(in_w, in_h, out_w, out_h):
    """The largest whole scale that fits, which is what a frontend's integer
    mode picks and what pass one renders at. 5 at 1024x768, 3 at 640x480.

    The nudge is not decoration: floor() on a division result is a recorded trap
    here, and reading 4 instead of 5 at exactly 5.0 would change the answer.
    """
    return max(int(np.floor(min(out_w / in_w, out_h / in_h) + 1e-3)), 1)


def box_resample_axis(img, axis, n_out):
    """Exact area average along one axis, by explicit overlap weights.

    Written as a dense weight matrix rather than anything clever: this is the
    reference, so being obviously right matters more than being quick.
    """
    n_in = img.shape[axis]
    edges = np.linspace(0.0, n_in, n_out + 1)
    lo, hi = edges[:-1, None], edges[1:, None]
    cells = np.arange(n_in)[None, :]
    w = np.clip(np.minimum(cells + 1, hi) - np.maximum(cells, lo), 0.0, None)
    w /= w.sum(axis=1, keepdims=True)
    return np.tensordot(w, img, axes=([1], [axis])) if axis == 0 else \
        np.moveaxis(np.tensordot(w, img, axes=([1], [axis])), 0, axis)


def render_two_pass(src_u8, out_w, out_h, grid=0.30, level=1.0, brightness=1.0,
                    gap_px=1, N=None, quantise=True):
    """Pass one: nearest at a whole scale, hard grid. Pass two: area average."""
    s = src_u8.astype(np.float64) / 255.0
    in_h, in_w = s.shape[:2]
    N = N or fit_scale(in_w, in_h, out_w, out_h)
    gap = int(round(gap_px))

    # pass one, entirely in integer space: every cell is N pixels and the grid
    # line is the last `gap` of them, on both axes
    mid = np.repeat(np.repeat(s, N, axis=0), N, axis=1) * brightness
    on_x = (np.arange(in_w * N) % N) >= (N - gap)
    on_y = (np.arange(in_h * N) % N) >= (N - gap)
    mask = np.maximum(on_x[None, :], on_y[:, None]).astype(np.float64)[..., None]
    mid = mid + (level - mid) * (grid * mask)

    # pass two
    out = box_resample_axis(box_resample_axis(mid, 0, out_h), 1, out_w)
    out = np.clip(out, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


def check(ctx, name, params, cases=CASES, sources=("gray", "scene"),
          tolerance=1, verbose=False):
    from crt_preview import SOURCES

    prog = compile_shader(ctx, name)
    print(f"\n{name} against the two-pass pipeline")
    print(f"  {'case':20s} {'scale':13s} {'N':>2s}  {'max diff':>9s}")
    worst, worst_at = 0, ""
    for label, (sw, sh), (ow, oh) in cases:
        N = fit_scale(sw, sh, ow, oh)
        worst_case = 0
        for sname in sources:
            s = SOURCES[sname](sw, sh)
            gpu = gl_render(ctx, prog, s, ow, oh, params).astype(int)
            ref = render_two_pass(s, ow, oh, grid=params.get("dp_grid", 0.30),
                                  brightness=params.get("dp_brightness", 1.0),
                                  gap_px=params.get("dp_gap", 1.0)).astype(int)
            d = int(np.abs(gpu - ref).max())
            if verbose:
                print(f"    {label:20s} {sname:6s} {d}")
            worst_case = max(worst_case, d)
        if worst_case > worst:
            worst, worst_at = worst_case, label
        note = "exact" if worst_case == 0 else ""
        print(f"  {label:20s} {ow/sw:5.2f}x{oh/sh:5.2f} {N:2d}  "
              f"{worst_case:6d}/255  {note}")
    ok = worst <= tolerance
    print(f"  worst {worst}/255 at {worst_at or 'nowhere'}   "
          f"{'OK' if ok else 'DIFFERS FROM THE PIPELINE'}")
    return worst


def selftest():
    """The reference has to be right before anything is measured against it.

    At a whole scale factor pass two is an identity, so the whole pipeline
    reduces to pass one - a nearest-neighbour upscale with a hard 1px line. That
    is checkable without any resampling at all, which is what makes it a test:
    it pins the reference against something simpler than itself.
    """
    ok = True

    def claim(cond, what):
        nonlocal ok
        ok = ok and cond
        print(f"    {'pass' if cond else 'FAIL'}  {what}")

    print("  self-test of the reference")
    rng = np.random.default_rng(0)
    src = rng.integers(0, 256, (144, 160, 3), dtype=np.uint8)

    for N in (3, 4, 5):
        out = render_two_pass(src, 160 * N, 144 * N, grid=0.30, quantise=False)
        direct = np.repeat(np.repeat(src.astype(np.float64) / 255.0, N, 0), N, 1)
        on = (np.arange(160 * N) % N) >= (N - 1)
        onv = (np.arange(144 * N) % N) >= (N - 1)
        m = np.maximum(on[None, :], onv[:, None]).astype(float)[..., None]
        direct = direct + (1.0 - direct) * (0.30 * m)
        claim(np.abs(out - direct).max() < 1e-12,
              f"at {N}x, pass two is an identity and the result is pass one")

    # a flat field must survive both passes untouched wherever no grid is drawn
    flat = np.full((144, 160, 3), 128, np.uint8)
    out = render_two_pass(flat, 1024, 768, grid=0.0, quantise=False)
    claim(abs(out.max() - 128 / 255) < 1e-12 and abs(out.min() - 128 / 255) < 1e-12,
          "with the grid off, an area average of a flat field is flat")

    # every row of the resample must sum to one, or the image changes brightness
    w_ok = True
    for n_in, n_out in ((800, 1024), (720, 768), (480, 533)):
        e = np.linspace(0, n_in, n_out + 1)
        c = np.arange(n_in)[None, :]
        w = np.clip(np.minimum(c + 1, e[1:, None]) - np.maximum(c, e[:-1, None]), 0, None)
        w_ok = w_ok and np.allclose(w.sum(axis=1), n_in / n_out)
    claim(w_ok, "the resample weights partition the source exactly")

    print(f"  self-test {'ok' if ok else 'FAILED'}")
    return ok


def main(argv):
    from shaders import REGISTRY

    verbose = "-v" in argv
    wanted = [a for a in argv[1:] if a != "-v"]
    if not wanted:
        wanted = [n for n in REGISTRY if n.startswith("dmg-perfect-v2")]
    if not selftest():
        print("\nthe reference is wrong; nothing below can be trusted")
        return 1
    if not wanted:
        print("\nno v2 shader in the registry yet; name one explicitly")
        return 0

    ctx = moderngl.create_standalone_context()
    over = 0
    for name in wanted:
        params = dict(REGISTRY[name].defaults) if name in REGISTRY else {}
        over = max(over, check(ctx, name, params, verbose=verbose))
    print(f"\n{'matches the two-pass pipeline' if over <= 1 else f'off by {over}/255'}")
    return 1 if over > 1 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
