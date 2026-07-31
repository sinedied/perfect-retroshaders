#!/usr/bin/env python3
"""Prove pixel-perfect.glsl matches the vendored pixellate.glsl.

pixellate has two modes. INTERPOLATE_IN_LINEAR_GAMMA = 0 blends in the encoded
domain; = 1 (its default) linearises each tap first. pixel-perfect targets the
former, because the latter is itself a moire source - this script measures both.

Section 6 answers the same question for the vendored sharp-shimmerless, which
computes the identical area average with ONE tap by handing the blend to the
texture unit. That is the one-tap LINEAR construction AGENTS.md records as
prototyped and rejected here, so it is measured rather than argued about: it
matches, it is the cheapest thing in the repo, and what it costs is a dependency
on the GPU's subtexel filtering precision, which this section quantifies.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python equivalence.py
"""
import collections
import sys

import numpy as np

import moderngl
from core.gpu import gl_render
from core.shader_source import stage_source
from core import manifest
from models.lcd import DEFAULTS_PP_V3, DEFAULTS_PP_V5, DEFAULTS_PP_V6
from core.paths import shader_path

PIXELLATE = shader_path("pixellate.glsl")
PIXEL_PERFECT = shader_path("pixel-perfect.glsl")
PIXEL_PERFECT_V3 = shader_path("pixel-perfect-v3.glsl")
PIXEL_PERFECT_V4 = shader_path("pixel-perfect-v4.glsl")
PIXEL_PERFECT_V5 = shader_path("pixel-perfect-v5.glsl")
PIXEL_PERFECT_V6 = shader_path("pixel-perfect-v6.glsl")

# v6 swaps v5's three channel gains for the two axes a white balance actually
# has. The grade around them is untouched, so with the balance neutral it has
# to reproduce v5 exactly - and any (r,g,b) that IS reachable on those two axes
# has to land on the same pixels, which is the claim that the basis is right
# rather than merely plausible.
V6_REACHABLE = [
    # (label, temperature, tint, the equivalent r/g/b for v5)
    ("warm 0.20", 0.20, 0.00, (1.20, 1.00, 0.80)),
    ("cool 0.20", -0.20, 0.00, (0.80, 1.00, 1.20)),
    ("magenta 0.20", 0.00, 0.20, (0.90, 1.20, 0.90)),
    ("green 0.20", 0.00, -0.20, (1.10, 0.80, 1.10)),
    ("warm + green", 0.15, -0.10, (1.20, 0.90, 0.90)),
]

# v5 folds a per-channel trim into v4's affine map. Two things have to hold and
# they are different claims: with the trim neutral it must reproduce v4 at every
# OTHER setting, which is what says the fold did not disturb the existing
# coefficients; and at its own defaults it must be the bare scaler.
V5_VS_V4 = [
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
]
SHIMMERLESS = shader_path("sharp-shimmerless.glsl")
# read from the one declaration, so section 6 cannot drift from what preview.py
# and bench_glsl.py render the same shader with
SS_LINEAR = manifest.sampler("sharp-shimmerless.glsl") == manifest.LINEAR

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


PROBE_VERT = """#version 410 core
in vec4 VertexCoord;
void main() { gl_Position = VertexCoord; }
"""

# Sweeps one texel spacing of a two-texel LINEAR texture holding 0.0 and 1.0, so
# the value read back IS the interpolator's blend weight. Rendered to float32,
# because an 8-bit target quantises harder than any plausible ladder and would
# report every GPU as exact.
PROBE_FRAG = """#version 410 core
uniform sampler2D Texture;
uniform float Width;
out vec4 FragColor;
void main() {
    float u = 0.25 + 0.5 * floor(gl_FragCoord.x) / (Width - 1.0);
    FragColor = vec4(texture(Texture, vec2(u, 0.5)).r);
}
"""


def subtexel_bits(ctx, n=4096):
    """How many distinct weights this GPU's bilinear unit can produce.

    There is no GL query for it - it is a fixed-point ladder whose width is a
    hardware property - and it is exactly what a one-tap scaler's accuracy rests
    on, so it has to be measured. n bounds what is resolvable: a result equal to
    n means the ladder is finer than the probe, not that it is exact.
    """
    tex = ctx.texture((2, 1), 1, bytes([0, 255]))
    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
    tex.repeat_x = tex.repeat_y = False
    tex.use(0)
    prog = ctx.program(vertex_shader=PROBE_VERT, fragment_shader=PROBE_FRAG)
    prog["Texture"].value = 0
    prog["Width"].value = float(n)
    vbo = ctx.buffer(np.array([-1, 1, 0, 1, -1, -1, 0, 1,
                                1, 1, 0, 1,  1, -1, 0, 1], "f4").tobytes())
    vao = ctx.vertex_array(prog, [(vbo, "4f4", "VertexCoord")])
    fbo = ctx.framebuffer(color_attachments=[ctx.texture((n, 1), 1, dtype="f4")])
    fbo.use()
    ctx.viewport = (0, 0, n, 1)
    vao.render(moderngl.TRIANGLE_STRIP)
    vals = np.frombuffer(fbo.read(components=1, dtype="f4"), "f4")
    steps = int(len(np.unique(vals)))
    for o in (tex, vbo, vao, fbo):
        o.release()
    if steps >= n:
        return f">{int(np.log2(n))}", steps
    return f"{np.log2(max(steps - 1, 1)):.1f}", steps


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
                       ("pixel-perfect-v4", PIXEL_PERFECT_V4),
                       ("pixel-perfect-v5", PIXEL_PERFECT_V5),
                       ("pixel-perfect-v6", PIXEL_PERFECT_V6),
                       ("sharp-shimmerless", SHIMMERLESS)):
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

    print("\n6. sharp-shimmerless (vendor): the same average from ONE tap\n")
    print("   It computes the same box footprint, then instead of taking four"
          "\n   NEAREST taps and weighting them, it solves for the one texcoord"
          "\n   whose bilinear fetch already IS that weighted sum. Same maths,"
          "\n   50 ops against 292, one tap against four, and it needs"
          "\n   filter_linear0 = true - the opposite sampler to everything here.\n")
    print(f"   {'source':>10s} {'output':>10s} {'scale':>12s} "
          f"{'vs pixellate':>13s} {'vs pixel-perfect':>17s}")
    worst_ss = 0
    for iw, ih, ow, oh in CASES:
        mx_px = mx_pp = 0
        for _, s6 in sources(iw, ih, rng):
            ss = gl_render(ctx, prog["sharp-shimmerless"], s6, ow, oh, {},
                           filter_linear=SS_LINEAR).astype(int)
            a = gl_render(ctx, prog["pixellate"], s6, ow, oh,
                          {"INTERPOLATE_IN_LINEAR_GAMMA": 0.0}).astype(int)
            b = gl_render(ctx, prog["pixel-perfect"], s6, ow, oh,
                          {"pp_sharpness": 1.0}).astype(int)
            mx_px = max(mx_px, int(np.abs(ss - a).max()))
            mx_pp = max(mx_pp, int(np.abs(ss - b).max()))
        worst_ss = max(worst_ss, mx_pp)
        print(f"   {iw}x{ih:<6d} {ow}x{oh:<5d} {ow/iw:5.2f}x{oh/ih:<5.2f} "
              f"{mx_px:10d}/255 {mx_pp:14d}/255")
    print(f"\n   worst: {worst_ss}/255 - the same answer, by a different route")

    print("\n   Block structure at 320x240 -> 1024x768 (3.2x)\n")
    for name, params, lin in (("pixellate", {"INTERPOLATE_IN_LINEAR_GAMMA": 0.0}, False),
                              ("pixel-perfect", {"pp_sharpness": 1.0}, False),
                              ("sharp-shimmerless", {}, SS_LINEAR)):
        w, blended = block_widths(
            gl_render(ctx, prog[name], src, 1024, 768, params, filter_linear=lin), 400)
        print(f"   {name:18s} widths {w}  transition px/row {blended}")

    print("\n   Moire (checkerboard, lower is better)\n")
    print(f"   {'scale':<22s} {'pixellate g=1':>14s} {'pixel-perfect':>14s} "
          f"{'sharp-shimmerless':>18s}")
    for iw, ih, ow, oh in CASES[:6]:
        yy, xx = np.mgrid[0:ih, 0:iw]
        chk = (((yy + xx) % 2) * 255).astype(np.uint8)[..., None].repeat(3, 2)
        g1 = beat(gl_render(ctx, prog["pixellate"], chk, ow, oh,
                            {"INTERPOLATE_IN_LINEAR_GAMMA": 1.0}))
        pp = beat(gl_render(ctx, prog["pixel-perfect"], chk, ow, oh,
                            {"pp_sharpness": 1.0}))
        ss = beat(gl_render(ctx, prog["sharp-shimmerless"], chk, ow, oh, {},
                            filter_linear=SS_LINEAR))
        label = f"{iw}x{ih} -> {ow}x{oh}"
        print(f"   {label:<22s} {g1:14.3f} {pp:14.3f} {ss:18.3f}")
    print("\n   The g=1 column is pixellate's own DEFAULT, and it is the only"
          "\n   thing separating these three: one tap or four does not decide"
          "\n   moire, the gamma round-trip does. sharp-shimmerless has no such"
          "\n   knob to get wrong - it has no parameters at all.")

    bits, steps = subtexel_bits(ctx)
    print("\n   What it trades away, 1: the blend weight is no longer computed"
          "\n   in the shader, it is whatever the texture unit's subtexel"
          "\n   interpolator produces. That is a fixed-point ladder, not a"
          "\n   float, and its width is a hardware property with no GL query.\n")
    print(f"   this GPU: {steps} distinct weights across one texel spacing "
          f"= {bits} bits")
    print("   8-bit output hides a ladder this fine, so the rows above cannot"
          "\n   see it. A coarser interpolator would show up as banding on"
          "\n   every soft transition pixel, and the only way to know what the"
          "\n   Mali G31 does is to run it there.")

    print("\n   What it trades away, 2: it fails SILENTLY under the wrong"
          "\n   sampler. Everything this repo ships needs NEAREST and is merely"
          "\n   filtered twice under LINEAR; a one-tap scaler under NEAREST"
          "\n   loses the whole blend, because the tap it placed between two"
          "\n   texel centres snaps back to one of them.\n")
    print(f"   {'320x240 -> 1024x768':<28s} {'transition px/row':>17s} "
          f"{'vs pixel-perfect':>17s}")
    ref = gl_render(ctx, prog["pixel-perfect"], src, 1024, 768,
                    {"pp_sharpness": 1.0}).astype(int)
    for label, lin in (("with filter_linear0 = true", True),
                       ("with a NEAREST sampler", False)):
        img = gl_render(ctx, prog["sharp-shimmerless"], src, 1024, 768, {},
                        filter_linear=lin)
        _, blended = block_widths(img, 400)
        print(f"   {label:<28s} {blended:17d} "
              f"{int(np.abs(img.astype(int) - ref).max()):14d}/255")
    print("\n   That is nearest-neighbour: the uneven, crawling blocks the"
          "\n   shader exists to remove, with nothing in the output to say so.")

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

    print("\n8. pixel-perfect-v5 vs v4: does adding the trim disturb it?\n")
    print("   v5 adds a per-channel trim as one multiply inside v4's existing"
          "\n   guard. With the trim neutral that multiply is by 1.0, which is"
          "\n   exact, so every other setting has to be untouched - not close,"
          "\n   identical.\n")
    print(f"   {'configuration':<24s} {'max diff':>9s}")
    worst_v5 = 0
    for label, over in V5_VS_V4:
        mx = 0
        for iw, ih, ow, oh in CASES[:6]:
            for _, s in sources(iw, ih, rng):
                p4 = dict(DEFAULTS_PP_V3, **over)
                a = gl_render(ctx, prog["pixel-perfect-v4"], s, ow, oh, p4).astype(int)
                b = gl_render(ctx, prog["pixel-perfect-v5"], s, ow, oh,
                              dict(p4, pp_red=1.0, pp_green=1.0, pp_blue=1.0)).astype(int)
                mx = max(mx, int(np.abs(a - b).max()))
        worst_v5 = max(worst_v5, mx)
        print(f"   {label:<24s} {mx:6d}/255")
    print(f"\n   worst: {worst_v5}/255   "
          f"{'the trim is exactly neutral' if worst_v5 == 0 else 'ADDING THE TRIM CHANGED v4'}")

    # And the weaker statement, with the right bar on it. v5 carries the same
    # post-blend branch as v4, so it inherits v4's contraction difference
    # against the branchless scaler - section 7 measures that and proves with an
    # unreachable-branch control that it is the branch and not the grade. The
    # check here is that v5 brings nothing NEW: its difference set against the
    # scaler has to be the same pixels as v4's, not merely the same size.
    worst_v5d, same_as_v4 = 0, True
    for iw, ih, ow, oh in CASES:
        for _, s in sources(iw, ih, rng):
            base = gl_render(ctx, prog["pixel-perfect"], s, ow, oh,
                             {"pp_sharpness": 1.0}).astype(int)
            d4 = np.abs(gl_render(ctx, prog["pixel-perfect-v4"], s, ow, oh,
                                  DEFAULTS_PP_V3).astype(int) - base)
            d5 = np.abs(gl_render(ctx, prog["pixel-perfect-v5"], s, ow, oh,
                                  DEFAULTS_PP_V5).astype(int) - base)
            worst_v5d = max(worst_v5d, int(d5.max()))
            same_as_v4 &= bool((d4 == d5).all())
    print(f"   v5 at its defaults vs pixel-perfect: {worst_v5d}/255, and the"
          f"\n   same pixels as v4: {'yes' if same_as_v4 else 'NO'}"
          f"  <- section 7's branch effect,"
          f"\n   inherited unchanged rather than anything the trim added")
    print("\n   A trim is a diagonal matrix, so it CAN be folded into the"
          "\n   affine map's coefficients - and that is 4 instructions worse,"
          "\n   not better, because it widens the luma term from scalar to"
          "\n   vec3. Measured with the parameters live and again with them"
          "\n   constant-folded, so hoisting cannot explain it away. It is a"
          "\n   separate multiply, and it still has to come after the"
          "\n   saturation mix: dot(col*t, LUMA) is not t*dot(col, LUMA).")

    # Three different claims, three different bars, and they are not
    # interchangeable. pixellate is a different formulation of the same maths,
    # so it is equal to float32 rounding; v3 at its defaults is the SAME code
    # path with the grade folding to col*1 + 0, so it is exactly equal and
    # anything else is a bug; v4 is the same computation with a branch after it,
    # which the driver contracts differently, so it is rounding again - but with
    # the unreachable-branch control alongside to prove that is all it is. v5
    # has the same branch as v4, so with the trim neutral it is exactly v4.
    print("\n9. pixel-perfect-v6: two balance axes instead of three gains\n")
    print("   Three channel gains carry one redundant degree of freedom, since"
          "\n   overall level is already pp_brightness. v6 spends the other two"
          "\n   on the axes a white balance actually has. Two claims: with the"
          "\n   balance neutral it is still v5, and where the two axes CAN"
          "\n   reach an r/g/b triple they must agree with v5 set to it.\n")
    print(f"   {'configuration':<32s} {'vs v5':>9s}")
    worst_v6 = 0
    for label, over in V5_VS_V4:
        mx = 0
        for iw, ih, ow, oh in CASES[:4]:
            for _, s in sources(iw, ih, rng):
                base = dict(DEFAULTS_PP_V3, **over)
                a = gl_render(ctx, prog["pixel-perfect-v5"], s, ow, oh,
                              dict(base, pp_red=1.0, pp_green=1.0, pp_blue=1.0)).astype(int)
                b = gl_render(ctx, prog["pixel-perfect-v6"], s, ow, oh,
                              dict(base, pp_temperature=0.0, pp_tint=0.0)).astype(int)
                mx = max(mx, int(np.abs(a - b).max()))
        worst_v6 = max(worst_v6, mx)
        print(f"   {label + ', balance off':<32s} {mx:6d}/255")

    for label, temp, tint, (r, g, b) in V6_REACHABLE:
        mx = 0
        for iw, ih, ow, oh in CASES[:4]:
            for _, s in sources(iw, ih, rng):
                a = gl_render(ctx, prog["pixel-perfect-v5"], s, ow, oh,
                              dict(DEFAULTS_PP_V5, pp_red=r, pp_green=g,
                                   pp_blue=b)).astype(int)
                bb = gl_render(ctx, prog["pixel-perfect-v6"], s, ow, oh,
                               dict(DEFAULTS_PP_V6, pp_temperature=temp,
                                    pp_tint=tint)).astype(int)
                mx = max(mx, int(np.abs(a - bb).max()))
        worst_v6 = max(worst_v6, mx)
        print(f"   {label + f' = rgb {r:.2f}/{g:.2f}/{b:.2f}':<32s} {mx:6d}/255")

    print(f"\n   worst: {worst_v6}/255   "
          f"{'the basis is exact' if worst_v6 == 0 else 'v6 IS NOT A REPARAMETERISATION'}")
    print("   Deliberately not normalised on luma, so an axis shifts the level"
          "\n   a little as well as the colour; pp_brightness takes that out.")

    return 0 if (worst <= 1 and worst_v3 == 0 and ok_v4
                 and worst_v5 == 0 and worst_v5d <= 1 and same_as_v4
                 and worst_v6 == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
