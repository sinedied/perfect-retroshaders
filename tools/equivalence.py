#!/usr/bin/env python3
"""Prove pixel-perfect.glsl matches the vendored pixellate.glsl.

pixellate has two modes. INTERPOLATE_IN_LINEAR_GAMMA = 0 blends in the encoded
domain; = 1 (its default) linearises each tap first. pixel-perfect targets the
former, because the latter is itself a moire source - this script measures both.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python equivalence.py
"""
import collections

import numpy as np

import moderngl
from gl_check import stage_source, gl_render
from paths import shader_path

PIXELLATE = shader_path("pixellate.glsl")
PIXEL_PERFECT = shader_path("pixel-perfect.glsl")

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
    for name, path in (("pixellate", PIXELLATE), ("pixel-perfect", PIXEL_PERFECT)):
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


if __name__ == "__main__":
    main()
