#!/usr/bin/env python3
"""GPU timing for the shaders in ../shaders, using timer queries.

NOTE ON METHOD: timing a loop of identical draws with glFinish at the end does
NOT work here - the driver coalesces them and the cost/draw falls as the loop
grows (8.6 -> 4.8 us/draw for 100 -> 1600 draws), which is not real work. Use
per-draw GL timer queries and take the median.

Absolute numbers come from an Apple GPU, so only the RATIO against the shipped
pixellate.glsl is meaningful for the Mali G31 on device.

Run:  /tmp/crtvenv/bin/python bench_glsl.py
"""
import os

import numpy as np

import moderngl
from gl_check import stage_source

from paths import shader_path
OW, OH = 1024, 768
IW, IH = 320, 240
DRAWS = 200

CASES = [
    ("pixellate.glsl (shipped)", "pixellate.glsl", {"INTERPOLATE_IN_LINEAR_GAMMA": 1.0}),
    ("crt-perfect v1 default", "crt-perfect.glsl", {}),
    ("crt-perfect v2 default", "crt-perfect-v2.glsl", {}),
    ("crt-perfect v3 default", "crt-perfect-v3.glsl", {}),
    ("crt-perfect v3 slot", "crt-perfect-v3.glsl", {"Mask_Type": 2.0}),
    ("crt-perfect v4 default", "crt-perfect-v4.glsl", {}),
    ("crt-perfect v4 slot", "crt-perfect-v4.glsl", {"Mask_Type": 2.0}),
    ("crt-perfect v5 default", "crt-perfect-v5.glsl", {}),
    ("crt-perfect v5b default", "crt-perfect-v5b.glsl", {}),
    ("crt-perfect slot mask", "crt-perfect.glsl", {"Mask_Type": 2.0}),
    ("crt-perfect scanlines only", "crt-perfect.glsl", {"RGB_Mask": 0.0}),
    ("crt-perfect effects off", "crt-perfect.glsl", {"Scanlines": 0.0, "RGB_Mask": 0.0}),
]


def build(ctx, fn, params):
    src = open(shader_path(fn)).read()
    p = ctx.program(vertex_shader=stage_source(src, "vert"),
                    fragment_shader=stage_source(src, "frag"))
    for k, v in params.items():
        if k in p:
            p[k].value = float(v)
    for n, v in (("OutputSize", (float(OW), float(OH))),
                 ("TextureSize", (float(IW), float(IH))),
                 ("InputSize", (float(IW), float(IH))),
                 ("OrigTextureSize", (float(IW), float(IH))),
                 ("OrigInputSize", (float(IW), float(IH)))):
        if n in p:
            p[n].value = v
    if "MVPMatrix" in p:
        p["MVPMatrix"].write(np.identity(4, "f4").tobytes())
    if "Texture" in p:
        p["Texture"].value = 0
    return p


def main():
    ctx = moderngl.create_standalone_context()
    q = ctx.query(time=True)
    rng = np.random.default_rng(1)
    tex = ctx.texture((IW, IH), 3,
                      rng.integers(0, 255, (IH, IW, 3), dtype=np.uint8).tobytes())
    tex.use(0)
    verts = np.array([-1, 1, 0, 1, 0, 1, 0, 0, -1, -1, 0, 1, 0, 0, 0, 0,
                       1, 1, 0, 1, 1, 1, 0, 0,  1, -1, 0, 1, 1, 0, 0, 0], "f4")
    vbo = ctx.buffer(verts.tobytes())
    fbo = ctx.framebuffer(color_attachments=[ctx.texture((OW, OH), 3)])
    fbo.use()
    ctx.viewport = (0, 0, OW, OH)

    print(f"{OW}x{OH} output, {IW}x{IH} source, median of {DRAWS} timer-queried draws")
    print("(Apple GPU - compare ratios, not absolutes)\n")
    base = None
    for label, fn, params in CASES:
        prog = build(ctx, fn, params)
        names = [n for n in ("VertexCoord", "TexCoord") if n in prog]
        vao = ctx.vertex_array(prog, [(vbo, " ".join(["4f4"] * len(names)), *names)])
        for _ in range(50):
            vao.render(moderngl.TRIANGLE_STRIP)
        ctx.finish()
        s = []
        for _ in range(DRAWS):
            with q:
                vao.render(moderngl.TRIANGLE_STRIP)
            s.append(q.elapsed)
        s.sort()
        ms = s[len(s) // 2] / 1e6
        if base is None:
            base = ms
        print(f"  {label:30s} {ms:7.4f} ms   {ms/base*100:5.1f}% of pixellate")
        vao.release()


if __name__ == "__main__":
    main()
