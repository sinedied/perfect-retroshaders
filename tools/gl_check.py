#!/usr/bin/env python3
"""Run the real shipped .glsl files on the GPU and diff them against their models.

For every entry in shaders.py: loads the .glsl, applies the same preprocessing
generic_video.c does (minus the ESSL version, since macOS only offers a 4.1 core
context), feeds it the uniforms runShaderPass() would set, renders into an FBO the
size of the on-screen rect, and compares the readback with the numpy model.

The two implementations are independent on purpose - an error has to be made
identically in GLSL and in numpy to slip through. Target is worst <= 1/255, which
is pure float32-vs-float64 rounding; anything above that means one of the two is
wrong.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python gl_check.py [-v] [shader ...]
"""

import re
import sys

import numpy as np

import moderngl
from crt_preview import SOURCES

from paths import shader_path
from shaders import REGISTRY

HEADER = "#version 410 core\n"

# rounding between float32 on the GPU and float64 in the model
TOLERANCE = 1

# Vendored shaders whose own .glslp asks for filter_linear0 = true. Both
# sharp-shimmerless variants take a SINGLE tap and have the texture unit perform
# the blend, so under NEAREST they are not a softer version of themselves - they
# are nearest-neighbour, with the whole scaler gone and nothing in the output to
# say so. Everything this repo ships wants the opposite: it computes its own
# average from four taps, and a LINEAR sampler underneath filters it twice.
#
# This is declared once and read by every tool that renders. It did not used to
# be, and the consequence is on the record: the sharp-shimmerless-grid row in
# the lcd-perfect comparison table was measured through NEAREST, so it described
# a shader nobody runs.
LINEAR_SAMPLED = frozenset({
    "sharp-shimmerless.glsl",
    "sharp-shimmerless-grid.glsl",
})


def essl1_to_410(src, stage):
    """Translate an ESSL-1.00 shader well enough for a 4.1 core context.

    The shaders this repo ships carry the COMPAT_* macro block, so they compile
    at either version and are returned untouched. Vendored references often do
    not - dmg_dot_matrix.glsl is written straight against ESSL 1.00 - and macOS
    offers no context old enough to take them as they are.

    Only the keywords that actually changed are rewritten, per stage, and the
    vendor file is never modified on disk. The #ifdef VERTEX / #else pair needs
    no help: the fragment stage leaves VERTEX undefined and falls into the else.
    """
    if "COMPAT_VARYING" in src:
        return src
    out = re.sub(r"\battribute\b", "in", src)
    out = re.sub(r"\bvarying\b", "out" if stage == "vert" else "in", out)
    out = re.sub(r"\btexture2D\b", "texture", out)
    if stage == "frag" and "gl_FragColor" in out:
        # gl_ is a reserved prefix, so this cannot be done with a #define
        out = "out vec4 FragColor;\n" + re.sub(r"\bgl_FragColor\b", "FragColor",
                                               out)
    return out


def stage_source(src, stage):
    src = essl1_to_410(src, stage)
    body = "".join(
        l + "\n" for l in src.split("\n") if not l.startswith("#pragma parameter")
    )
    define = ("#define VERTEX\n" if stage == "vert"
              else "#define FRAGMENT\n#define PARAMETER_UNIFORM\n")
    return HEADER + define + body


def pragma_defaults(fn):
    """A shader's own declared defaults, read straight out of the file.

    For vendored references, which have no entry in the registry. Falling back
    to {} instead is not "the defaults" - a uniform nothing sets is 0, and
    PARAMETER_UNIFORM is defined, so an empty dict renders a shader at whatever
    zero happens to mean for it. For pixellate that silently selects
    INTERPOLATE_IN_LINEAR_GAMMA = 0, the mode it does NOT ship in and the one
    without the gamma round-trip, so every preview flattered it.
    """
    out = {}
    for line in open(shader_path(fn)):
        m = re.match(r'#pragma parameter\s+(\w+)\s+"[^"]*"\s+(-?[\d.]+)', line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


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


def check(ctx, name, model, verbose=False):
    src = open(shader_path(name)).read()
    try:
        prog = ctx.program(vertex_shader=stage_source(src, "vert"),
                           fragment_shader=stage_source(src, "frag"))
    except Exception as exc:
        print(f"  {name:24s} FAILED TO LINK\n{exc}")
        return None

    # The model's defaults and the shader's own #pragma defaults have to agree
    # before either is used, because this function then feeds one dict to both
    # sides. Feeding model.defaults to the GPU as well meant the shipped
    # defaults were never once exercised here: the two implementations agreed
    # perfectly about a configuration that need not be the one users get. The
    # dicts are compared rather than merged - a mismatch is a bug in one of
    # them, and picking a winner would hide it.
    declared = pragma_defaults(name)
    if declared:
        only_shader = set(declared) - set(model.defaults)
        only_model = set(model.defaults) - set(declared)
        differ = {k for k in set(declared) & set(model.defaults)
                  if abs(declared[k] - model.defaults[k]) > 1e-9}
        if only_shader or only_model or differ:
            print(f"  {name:24s} DEFAULTS DISAGREE")
            for k in sorted(only_shader):
                print(f"      {k}: in the shader, missing from the model")
            for k in sorted(only_model):
                print(f"      {k}: in the model, missing from the shader")
            for k in sorted(differ):
                print(f"      {k}: shader {declared[k]:g}, "
                      f"model {model.defaults[k]:g}")
            return 1

        # Every declared parameter must actually reach the program. A uniform
        # the harness never sets is 0, and 0 is a legal-looking value for most
        # of these, so an unset one does not crash - it renders something else.
        unset = [k for k in declared if k in prog and k not in model.defaults]
        if unset:
            print(f"  {name:24s} UNINITIALISED UNIFORMS: {', '.join(unset)}")
            return 1

    runs = [("defaults", {})] + model.variants
    worst, worst_where, worst_out = 0, "", 0
    for label, overrides in runs:
        params = dict(model.defaults, **overrides)
        for case, (sw, sh), (ow, oh) in model.cases:
            for sname in model.sources:
                s = SOURCES[sname](sw, sh)
                gpu = gl_render(ctx, prog, s, ow, oh, params).astype(int)
                ref = model.render(s, ow, oh, params).astype(int)
                dmap = np.abs(gpu - ref).max(axis=2)
                n_over = int((dmap > TOLERANCE).sum())
                worst_out = max(worst_out, n_over)
                if model.outliers and dmap.size > model.outliers:
                    # ignore the N worst pixels, then judge the rest
                    d = int(np.partition(dmap, -(model.outliers + 1), axis=None)
                            [-(model.outliers + 1)])
                else:
                    d = int(dmap.max())
                if verbose:
                    print(f"    {label:14s} {case:18s} {sname:6s} max {d}"
                          + (f" ({n_over} over)" if n_over else ""))
                if d > worst:
                    worst, worst_where = d, f"{label} / {case} / {sname}"

    ok = worst <= model.tolerance
    if worst <= TOLERANCE and not worst_out:
        note = ""
    elif ok:
        note = f"   tolerated: {model.reason}"
        if model.outliers:
            note = (f"   {worst_out} outlier px/case (allowed {model.outliers}): "
                    f"{model.reason}")
    else:
        note = f"   worst at {worst_where}"
    if model.outliers and worst_out > model.outliers:
        ok = False
        note = (f"   {worst_out} outlier px/case exceeds the allowed "
                f"{model.outliers}")
    status = ("OK" if worst <= TOLERANCE and not worst_out
              else ("tolerated" if ok else "MISMATCH"))
    print(f"  {name:24s} worst diff {worst:3d}/255 "
          f"(tol {model.tolerance:2d})   {status}{note}")
    return worst - model.tolerance if ok else max(worst - model.tolerance, 1)


def main(argv):
    verbose = "-v" in argv
    wanted = [a for a in argv[1:] if a != "-v"] or list(REGISTRY)
    unknown = [n for n in wanted if n not in REGISTRY]
    if unknown:
        print(f"not in the registry: {', '.join(unknown)}")
        return 2

    ctx = moderngl.create_standalone_context()
    over = 0
    failed = False
    for name in wanted:
        r = check(ctx, name, REGISTRY[name], verbose)
        if r is None:
            failed = True
        else:
            over = max(over, r)

    print(f"\n{'all shaders within their tolerance' if over <= 0 else f'over tolerance by {over}/255'}")
    return 1 if failed or over > 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
