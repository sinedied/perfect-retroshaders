#!/usr/bin/env python3
"""Run the real crt-perfect.glsl on the GPU and diff it against crt_preview.py.

Loads the shipped .glsl, applies the same preprocessing generic_video.c does
(minus the ESSL version, since macOS only offers a 4.1 core context), feeds it
the uniforms runShaderPass() would set, renders into an FBO the size of the
on-screen rect, and compares the readback with the numpy reference model.

Run:  /tmp/crtvenv/bin/python gl_check.py
"""

import os
import sys

import numpy as np

import moderngl
from crt_preview import DEFAULTS, SOURCES, render_crt

from paths import SHADERS as GLSL, shader_path

SHADER = shader_path("crt-perfect.glsl")

HEADER = "#version 410 core\n"


def stage_source(src, stage):
    body = "".join(
        l + "\n" for l in src.split("\n") if not l.startswith("#pragma parameter")
    )
    define = "#define VERTEX\n" if stage == "vert" else "#define FRAGMENT\n#define PARAMETER_UNIFORM\n"
    return HEADER + define + body


def gl_render(ctx, prog, src_u8, out_w, out_h, params):
    in_h, in_w = src_u8.shape[:2]
    tex = ctx.texture((in_w, in_h), 3, src_u8.tobytes())
    tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
    tex.repeat_x = tex.repeat_y = False  # CLAMP_TO_EDGE
    tex.use(0)

    p = dict(DEFAULTS, **(params or {}))
    for k, v in p.items():
        if k in prog:
            prog[k].value = float(v)
    prog["Texture"].value = 0
    prog["OutputSize"].value = (float(out_w), float(out_h))
    prog["TextureSize"].value = (float(in_w), float(in_h))
    prog["InputSize"].value = (float(in_w), float(in_h))
    prog["MVPMatrix"].write(np.identity(4, "f4").tobytes())

    # same quad runShaderPass() uploads: x,y,z,w, u,v,s,t
    verts = np.array([
        -1.0,  1.0, 0.0, 1.0,  0.0, 1.0, 0.0, 0.0,
        -1.0, -1.0, 0.0, 1.0,  0.0, 0.0, 0.0, 0.0,
         1.0,  1.0, 0.0, 1.0,  1.0, 1.0, 0.0, 0.0,
         1.0, -1.0, 0.0, 1.0,  1.0, 0.0, 0.0, 0.0,
    ], "f4")
    vbo = ctx.buffer(verts.tobytes())
    binding = []
    if "VertexCoord" in prog:
        binding.append("4f4")
    if "TexCoord" in prog:
        binding.append("4f4")
    names = [n for n in ("VertexCoord", "TexCoord") if n in prog]
    vao = ctx.vertex_array(prog, [(vbo, " ".join(binding), *names)])

    fbo = ctx.framebuffer(color_attachments=[ctx.texture((out_w, out_h), 3)])
    fbo.use()
    ctx.viewport = (0, 0, out_w, out_h)
    fbo.clear(0.0, 0.0, 0.0, 1.0)
    vao.render(moderngl.TRIANGLE_STRIP)

    data = np.frombuffer(fbo.read(components=3), np.uint8).reshape(out_h, out_w, 3)
    for o in (tex, vbo, vao, fbo):
        o.release()
    return data


def main():
    ctx = moderngl.create_standalone_context()
    src = open(SHADER).read()
    prog = ctx.program(
        vertex_shader=stage_source(src, "vert"),
        fragment_shader=stage_source(src, "frag"),
    )
    print("shader linked ok\n")

    cases = [
        ("240p->1024x768 default", (320, 240), (1024, 768), "scene", {}),
        ("240p->1024x768 white",   (320, 240), (1024, 768), "white", {}),
        ("224p->1024x768 bars",    (256, 224), (1024, 768), "bars",  {}),
        ("144p->1024x768 scene",   (160, 144), (1024, 768), "scene", {}),
        ("240p->1280x720 slot",    (320, 240), (1280, 720), "bars",  dict(Mask_Type=2.0)),
        ("480p->1280x720 fade",    (640, 480), (1280, 720), "scene", {}),
        ("effects off",            (320, 240), (1024, 768), "bars",
         dict(Scanlines=0.0, RGB_Mask=0.0, Brightness=1.0)),
        ("strong",                 (320, 240), (1024, 768), "scene",
         dict(Scanlines=1.0, RGB_Mask=1.0, Beam_Width=1.0, Mask_Size=0.5, Brightness=2.0)),
    ]

    worst = 0
    for name, (sw, sh), (ow, oh), sname, params in cases:
        s = SOURCES[sname](sw, sh)
        gpu = gl_render(ctx, prog, s, ow, oh, params).astype(int)
        ref = render_crt(s, ow, oh, params).astype(int)
        d = np.abs(gpu - ref)
        worst = max(worst, d.max())
        pct = (d > 2).mean() * 100
        print(f"  {name:26s} max diff {d.max():3d}   mean {d.mean():5.3f}   "
              f"px >2: {pct:5.2f}%   {'OK' if d.max() <= 4 else 'MISMATCH'}")

    print(f"\nworst absolute difference across all cases: {worst}/255")
    return 0 if worst <= 4 else 1


if __name__ == "__main__":
    sys.exit(main())
