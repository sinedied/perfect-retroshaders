#!/usr/bin/env python3
"""Compiling and running a shader offscreen, the way the frontend would.

One place decides how a program is built and how a draw is set up, so every
tool that renders agrees on the sampler, the quad and the uniform block. They
did not always, and a comparison table once described a shader nobody runs
because one tool sampled it NEAREST and its .glslp asks for LINEAR.
"""

import numpy as np

import moderngl

from core import manifest
from core.shader_source import stage_source

def gl_render(ctx, prog, src_u8, out_w, out_h, params, filter_linear=False):
    """Render one pass and read it back, rows in the source's order.

    filter_linear is for shaders whose own .glslp asks for it - the vendored
    sharp-shimmerless takes a single tap and has the texture unit do the blend,
    so measuring it through NEAREST measures a different shader. Everything this
    repo ships needs the default: it computes its own average from four taps,
    and a LINEAR sampler underneath filters the result twice.
    """
    in_h, in_w = src_u8.shape[:2]
    tex = ctx.texture((in_w, in_h), 3, src_u8.tobytes())
    f = moderngl.LINEAR if filter_linear else moderngl.NEAREST
    tex.filter = (f, f)
    tex.repeat_x = tex.repeat_y = False  # CLAMP_TO_EDGE
    tex.use(0)

    for k, v in params.items():
        if k in prog:
            prog[k].value = float(v)
    # a shader that does not use one of these has it optimised out of the
    # program entirely, so every one has to be guarded, not just the optional
    for k, v in (("Texture", 0),
                 ("OutputSize", (float(out_w), float(out_h))),
                 ("TextureSize", (float(in_w), float(in_h))),
                 ("InputSize", (float(in_w), float(in_h))),
                 ("OrigInputSize", (float(in_w), float(in_h)))):
        if k in prog:
            prog[k].value = v
    if "MVPMatrix" in prog:
        prog["MVPMatrix"].write(np.identity(4, "f4").tobytes())

    # same quad runShaderPass() uploads: x,y,z,w, u,v,s,t
    verts = np.array([
        -1.0,  1.0, 0.0, 1.0,  0.0, 1.0, 0.0, 0.0,
        -1.0, -1.0, 0.0, 1.0,  0.0, 0.0, 0.0, 0.0,
         1.0,  1.0, 0.0, 1.0,  1.0, 1.0, 0.0, 0.0,
         1.0, -1.0, 0.0, 1.0,  1.0, 0.0, 0.0, 0.0,
    ], "f4")
    vbo = ctx.buffer(verts.tobytes())
    names = [n for n in ("VertexCoord", "TexCoord") if n in prog]
    vao = ctx.vertex_array(prog, [(vbo, " ".join("4f4" for _ in names), *names)])

    fbo = ctx.framebuffer(color_attachments=[ctx.texture((out_w, out_h), 3)])
    fbo.use()
    ctx.viewport = (0, 0, out_w, out_h)
    fbo.clear(0.0, 0.0, 0.0, 1.0)
    vao.render(moderngl.TRIANGLE_STRIP)

    data = np.frombuffer(fbo.read(components=3), np.uint8).reshape(out_h, out_w, 3)
    for o in (tex, vbo, vao, fbo):
        o.release()
    return data




def program(ctx, name):
    """Compile and link a shader by name, the way the frontend loads it."""
    from core.paths import shader_path
    src = open(shader_path(name)).read()
    return ctx.program(vertex_shader=stage_source(src, "vert"),
                       fragment_shader=stage_source(src, "frag"))


def render(ctx, name, src_u8, out_w, out_h, params, prog=None):
    """Render a named shader, sampled the way its manifest entry says.

    Taking the sampler from the manifest rather than from the caller is the
    point: a caller that forgets it gets the shader's declared behaviour, not
    whatever moderngl defaults to.
    """
    prog = prog or program(ctx, name)
    linear = manifest.sampler(name) == manifest.LINEAR
    return gl_render(ctx, prog, src_u8, out_w, out_h, params,
                     filter_linear=linear)
