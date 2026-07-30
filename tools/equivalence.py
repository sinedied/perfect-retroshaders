#!/usr/bin/env python3
"""Prove pixel-perfect.glsl matches the vendored pixellate.glsl.

pixellate has two modes. INTERPOLATE_IN_LINEAR_GAMMA = 0 blends in the encoded
domain; = 1 (its default) linearises each tap first. pixel-perfect targets the
former, because the latter is itself a moire source - this script measures both.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python equivalence.py
"""
import collections
import sys

import numpy as np

import moderngl
from gl_check import stage_source, gl_render
from lcd_preview import DEFAULTS_PP_V3
from paths import shader_path

PIXELLATE = shader_path("pixellate.glsl")
PIXEL_PERFECT = shader_path("pixel-perfect.glsl")
PIXEL_PERFECT_V3 = shader_path("pixel-perfect-v3.glsl")
PIXEL_PERFECT_V4 = shader_path("pixel-perfect-v4.glsl")

# v4 guards v3's affine block with an exact uniform test, so the two must agree
# at EVERY setting, not merely at the one that skips the block. Near-neutral
# values are in here on purpose: an epsilon guard would skip them and disagree
# with v3 over a whole range, which is the reason the guard is exact.
V4_SWEEP = [
    ("defaults", {}),
    ("greyscale", dict(pp_saturation=0.0)),
    ("oversaturated", dict(pp_saturation=1.8)),
    ("flat", dict(pp_contrast=0.4)),
    ("clipped contrast", dict(pp_contrast=2.0)),
    ("dim", dict(pp_brightness=0.6)),
    ("clipped gain", dict(pp_brightness=2.0)),
    ("gamma 0.7", dict(pp_gamma=0.7)),
    ("gamma 1.4", dict(pp_gamma=1.4)),
    ("full grade", dict(pp_saturation=1.3, pp_contrast=1.2,
                        pp_brightness=1.1, pp_gamma=0.9)),
    ("barely graded", dict(pp_contrast=1.0003)),
    ("cancelling deviations", dict(pp_brightness=1.1, pp_contrast=0.9)),
]

# The exact text of v4's guard, so the unreachable-branch control below can
# replace it. Asserted at use, because a silent miss would turn the control
# into a copy of v4 and it would agree with itself.
COND_V4 = """    if (pp_brightness != 1.0 || pp_contrast != 1.0
        || pp_saturation != 1.0) {"""


def transition_mask(iw, ih, ow, oh):
    """Output pixels whose footprint straddles a texel boundary on either axis.

    These are the only pixels where the blend does any arithmetic at all -
    everywhere else a weight clamps to exactly 0 or 1 and the result is a texel
    copied through - so they are the only ones a change in how that arithmetic
    is contracted can possibly move.
    """
    u = (np.arange(ow) + 0.5) / ow * iw
    v = (np.arange(oh) + 0.5) / oh * ih
    hx, hy = 0.4995 * iw / ow, 0.4995 * ih / oh
    wx = np.clip((np.floor(u + 0.5) - u + hx) / (2 * hx), 0, 1)
    wy = np.clip((np.floor(v + 0.5) - v + hy) / (2 * hy), 0, 1)
    return ((wx > 0) & (wx < 1))[None, :] | ((wy > 0) & (wy < 1))[:, None]

CASES = [(320, 240, 1024, 768), (256, 224, 1024, 768), (352, 240, 1024, 768),
         (368, 240, 1280, 720), (320, 240, 1280, 720), (160, 144, 1024, 768),
         (640, 480, 1024, 768), (512, 240, 1024, 768), (320, 240, 640, 480),
         (256, 224, 640, 480), (240, 160, 800, 600), (384, 224, 1024, 768)]


def sources(w, h, rng):
    yy, xx = np.mgrid[0:h, 0:w]
    yield "noise", rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    yield "checker", (((yy + xx) % 2) * 255).astype(np.uint8)[..., None].repeat(3, 2)
    a = np.zeros((h, w, 3), np.uint8)
    a[:, ::3] = 255
    a[::4, :] = 128
    yield "grid", a
    yield "ramp", (xx * 255 // max(w - 1, 1)).astype(np.uint8)[..., None].repeat(3, 2)


def beat(img):
    """Low-frequency energy: what the eye reads as moire."""
    out = []
    for prof in (img.astype(float).mean(axis=(1, 2)), img.astype(float).mean(axis=(0, 2))):
        p = prof - prof.mean()
        f = np.abs(np.fft.rfft(p * np.hanning(len(p)))) / len(p) * 2
        fr = np.fft.rfftfreq(len(p))
        band = (fr > 1 / 64) & (fr < 1 / 6)
        out.append(f[band].max())
    return max(out)


def block_widths(img, row=None):
    r = img[row if row is not None else img.shape[0] // 2, :, 0]
    runs = []
    c = 1
    for i in range(1, len(r)):
        if (r[i] > 250) == (r[i - 1] > 250):
            c += 1
        else:
            runs.append(c)
            c = 1
    blended = int(((r > 0) & (r < 255)).sum())
    return dict(sorted(collections.Counter(runs[1:-1]).items())), blended


def main():
    ctx = moderngl.create_standalone_context()
    prog = {}
    for name, path in (("pixellate", PIXELLATE), ("pixel-perfect", PIXEL_PERFECT),
                       ("pixel-perfect-v3", PIXEL_PERFECT_V3),
                       ("pixel-perfect-v4", PIXEL_PERFECT_V4)):
        s = open(path).read()
        prog[name] = ctx.program(vertex_shader=stage_source(s, "vert"),
                                 fragment_shader=stage_source(s, "frag"))
    rng = np.random.default_rng(0)

    print("1. Output equivalence vs pixellate INTERPOLATE_IN_LINEAR_GAMMA = 0\n")
    print(f"   {'source':>10s} {'output':>10s} {'scale':>12s} {'max':>4s} {'>1/255':>7s}")
    worst = 0
    for iw, ih, ow, oh in CASES:
        mx = 0
        pc = 0.0
        for _, src in sources(iw, ih, rng):
            a = gl_render(ctx, prog["pixellate"], src, ow, oh,
                          {"INTERPOLATE_IN_LINEAR_GAMMA": 0.0}).astype(int)
            b = gl_render(ctx, prog["pixel-perfect"], src, ow, oh,
                          {"pp_sharpness": 1.0}).astype(int)
            d = np.abs(a - b)
            mx = max(mx, int(d.max()))
            pc = max(pc, (d > 1).mean() * 100)
        worst = max(worst, mx)
        print(f"   {iw}x{ih:<6d} {ow}x{oh:<5d} {ow/iw:5.2f}x{oh/ih:<5.2f} {mx:4d} {pc:6.2f}%")
    print(f"\n   worst: {worst}/255")
    print("   1/255 here is float32 rounding, not a disagreement: the four"
          "\n   corner-area products and the divide factor into one horizontal"
          "\n   and one vertical weight, which is exact to 2.5e-15 in float64"
          "\n   but is a different order of operations on the GPU. The >1/255"
          "\n   column is the one that would have to be 0.00% either way.")

    print("\n2. Block structure at 320x240 -> 1024x768 (3.2x)\n")
    src = np.zeros((240, 320, 3), np.uint8)
    src[:, ::2] = 255
    for name, params in (("pixellate", {"INTERPOLATE_IN_LINEAR_GAMMA": 0.0}),
                         ("pixel-perfect", {"pp_sharpness": 1.0})):
        w, blended = block_widths(gl_render(ctx, prog[name], src, 1024, 768, params), 400)
        print(f"   {name:16s} widths {w}  transition px/row {blended}")

    print("\n3. Moire of the scaler alone (checkerboard, lower is better)\n")
    print(f"   {'scale':<22s} {'pixellate g=1':>14s} {'pixellate g=0':>14s} {'pixel-perfect':>14s}")
    for iw, ih, ow, oh in CASES[:6]:
        yy, xx = np.mgrid[0:ih, 0:iw]
        chk = (((yy + xx) % 2) * 255).astype(np.uint8)[..., None].repeat(3, 2)
        g1 = beat(gl_render(ctx, prog["pixellate"], chk, ow, oh,
                            {"INTERPOLATE_IN_LINEAR_GAMMA": 1.0}))
        g0 = beat(gl_render(ctx, prog["pixellate"], chk, ow, oh,
                            {"INTERPOLATE_IN_LINEAR_GAMMA": 0.0}))
        pp = beat(gl_render(ctx, prog["pixel-perfect"], chk, ow, oh, {"pp_sharpness": 1.0}))
        label = f"{iw}x{ih} -> {ow}x{oh}"
        print(f"   {label:<22s} {g1:14.3f} {g0:14.3f} {pp:14.3f}")

    print("\n4. pp_sharpness response, 320x240 -> 1024x768\n")
    print(f"   {'value':>6s} {'transition px/row':>18s}")
    for sh in (1.0, 0.8, 0.6, 0.4, 0.2):
        _, blended = block_widths(
            gl_render(ctx, prog["pixel-perfect"], src, 1024, 768, {"pp_sharpness": sh}), 400)
        print(f"   {sh:6.2f} {blended:18d}")
    print("\n   Which is why v3 drops it: below 1.00 the footprint stops covering"
          "\n   the output pixel, so the area average degrades toward nearest-"
          "\n   neighbour - the uneven, crawling blocks this shader exists to"
          "\n   remove. The knob's only effect is to undo the shader.")

    print("\n5. pixel-perfect-v3 at its defaults vs pixel-perfect\n")
    print("   Its grade is affine, and an affine map is exactly neutral at unity"
          "\n   gain - so 'off' has to mean bit-identical, not nearly. Anything"
          "\n   but 0 here means the fold rounds and must be branch-guarded.\n")
    print(f"   {'source':>10s} {'output':>10s} {'scale':>12s} {'max':>4s}")
    worst_v3 = 0
    for iw, ih, ow, oh in CASES:
        mx = 0
        for _, s in sources(iw, ih, rng):
            a = gl_render(ctx, prog["pixel-perfect"], s, ow, oh,
                          {"pp_sharpness": 1.0}).astype(int)
            b = gl_render(ctx, prog["pixel-perfect-v3"], s, ow, oh,
                          DEFAULTS_PP_V3).astype(int)
            mx = max(mx, int(np.abs(a - b).max()))
        worst_v3 = max(worst_v3, mx)
        print(f"   {iw}x{ih:<6d} {ow}x{oh:<5d} {ow/iw:5.2f}x{oh/ih:<5.2f} {mx:4d}")
    verdict = "bit-identical" if worst_v3 == 0 else "NOT NEUTRAL AT DEFAULTS"
    print(f"\n   worst: {worst_v3}/255   {verdict}")

    print("\n7. pixel-perfect-v4 vs v3, over the whole parameter range\n")
    print("   v4 only guards v3's affine block behind an exact uniform test, so"
          "\n   it has to agree with v3 at EVERY setting, not just at the one"
          "\n   that skips the block. The near-neutral rows are the point: an"
          "\n   epsilon guard would skip those and quietly disagree with v3"
          "\n   across a whole band of settings.\n")
    print(f"   {'configuration':<24s} {'max diff':>9s} {'px':>7s}")
    worst_v4, ndiff = 0, 0
    for label, over in V4_SWEEP:
        mx, n = 0, 0
        for iw, ih, ow, oh in CASES[:6]:
            for _, s in sources(iw, ih, rng):
                p3 = dict(DEFAULTS_PP_V3, **over)
                a = gl_render(ctx, prog["pixel-perfect-v3"], s, ow, oh, p3).astype(int)
                b = gl_render(ctx, prog["pixel-perfect-v4"], s, ow, oh, p3).astype(int)
                mx = max(mx, int(np.abs(a - b).max()))
                n += int((np.abs(a - b) > 0).any(axis=2).sum())
        worst_v4 = max(worst_v4, mx)
        ndiff += n
        print(f"   {label:<24s} {mx:6d}/255 {n:7d}")

    # The control. Same shader, but the branch is one the driver cannot fold
    # away and can never take, so the affine block is unreachable and the grade
    # cannot be what differs. If this reproduces v4's divergence exactly, the
    # divergence belongs to the branch's presence and not to anything v4 does.
    src4 = open(PIXEL_PERFECT_V4).read()
    if COND_V4 not in src4:
        raise SystemExit("equivalence.py: the v4 guard moved; fix COND_V4")
    never = src4.replace(COND_V4, "    if (OutputSize.x < 0.0) {")
    prog["never"] = ctx.program(vertex_shader=stage_source(never, "vert"),
                                fragment_shader=stage_source(never, "frag"))
    same, tr_only = True, True
    for iw, ih, ow, oh in CASES[:6]:
        for _, s in sources(iw, ih, rng):
            d = dict(DEFAULTS_PP_V3)
            a = gl_render(ctx, prog["pixel-perfect-v3"], s, ow, oh, d).astype(int)
            b = gl_render(ctx, prog["pixel-perfect-v4"], s, ow, oh, d).astype(int)
            c = gl_render(ctx, prog["never"], s, ow, oh, d).astype(int)
            same &= bool((np.abs(a - b) == np.abs(a - c)).all())
            tr_only &= bool((np.abs(a - b) > 0).any(axis=2)[
                transition_mask(iw, ih, ow, oh) == False].sum() == 0)

    print(f"\n   worst: {worst_v4}/255 over {ndiff} pixels")
    print(f"   an unreachable branch reproduces it exactly: "
          f"{'yes' if same else 'NO'}")
    print(f"   confined to transition pixels: {'yes' if tr_only else 'NO'}")
    print("\n   So this is not the grade. Putting ANY branch after the blend"
          "\n   changes how the driver contracts the blend's own arithmetic, and"
          "\n   the only pixels that can show it are the ones whose weights are"
          "\n   strictly between 0 and 1. v3 and v4 are the same computation"
          "\n   rounded two ways; gl_check scores both at 1/255 against the"
          "\n   float64 model, so neither is the more correct one.")

    ok_v4 = worst_v4 <= 1 and same and tr_only
    # Three different claims, three different bars, and they are not
    # interchangeable. pixellate is a different formulation of the same maths,
    # so it is equal to float32 rounding; v3 at its defaults is the SAME code
    # path with the grade folding to col*1 + 0, so it is exactly equal and
    # anything else is a bug; v4 is the same computation with a branch after it,
    # which the driver contracts differently, so it is rounding again - but with
    # the unreachable-branch control alongside to prove that is all it is.
    return 0 if worst <= 1 and worst_v3 == 0 and ok_v4 else 1


if __name__ == "__main__":
    sys.exit(main())
