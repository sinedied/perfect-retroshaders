#!/usr/bin/env python3
"""GPU timing for the shaders in ../shaders, using timer queries.

TWO THINGS ABOUT METHOD, both learned the hard way.

Timing a loop of identical draws with one glFinish at the end does NOT work: the
driver coalesces them and the cost per draw falls as the loop grows, 8.6 to 4.8
us/draw going from 100 to 1600 draws, which is not real work. Use per-draw GL
timer queries and take the median.

Measuring each shader to completion before starting the next does not work
either. The GPU clocks around during a run, so a case measured late can read
slow for reasons that have nothing to do with it - which is how pixellate once
came out both the fastest and the slowest thing in the table on different runs.
Interleave instead: one pass measures every case in turn, and the whole set is
repeated. Drift then lands on all cases roughly equally, and the spread across
passes is reported so a difference smaller than the noise cannot be read as
real.

Absolute numbers come from an Apple GPU, so only the RATIO against the vendored
pixellate.glsl means anything for the Mali G31 on device - and even the ratio is
a different chip. The static SFU count from spirv_cost.py remains the figure to
trust for the device.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python bench_glsl.py
"""
import os

import numpy as np

import moderngl
from gl_check import stage_source

from paths import shader_path
from shaders import REGISTRY
OW, OH = 1024, 768
IW, IH = 320, 240
DRAWS = 200

# Identical overrides on v6 and v8 so the only difference is the code, plus each
# shader at its own shipped defaults. Gamma "on" is 1.40; at 1.00 the shader
# skips the pow() entirely on a uniform branch, which is the point of measuring
# both. Curvature "on" is 0.10, mid-range for both versions.
GAMMA_ON = 1.40
CURV_ON = 0.10

CASES = [
    ("pixellate (vendor)", "pixellate.glsl", {"INTERPOLATE_IN_LINEAR_GAMMA": 1.0}),
    ("crt-perfect (flat)", "crt-perfect.glsl", {}),

    ("v6 defaults", "crt-perfect-v6.glsl", {}),
    ("v6 curve on, gamma off", "crt-perfect-v6.glsl",
     {"cp_curvature": CURV_ON, "cp_gamma": 1.0}),
    ("v6 curve off, gamma on", "crt-perfect-v6.glsl",
     {"cp_curvature": 0.0, "cp_gamma": GAMMA_ON}),
    ("v6 curve on, gamma on", "crt-perfect-v6.glsl",
     {"cp_curvature": CURV_ON, "cp_gamma": GAMMA_ON}),

    ("v8 defaults", "crt-perfect-v8.glsl", {}),
    ("v8 curve on, gamma off", "crt-perfect-v8.glsl",
     {"cp_curvature": CURV_ON, "cp_gamma": 1.0}),
    ("v8 curve off, gamma on", "crt-perfect-v8.glsl",
     {"cp_curvature": 0.0, "cp_gamma": GAMMA_ON}),
    ("v8 curve on, gamma on", "crt-perfect-v8.glsl",
     {"cp_curvature": CURV_ON, "cp_gamma": GAMMA_ON}),
]


def build(ctx, fn, params):
    src = open(shader_path(fn)).read()
    p = ctx.program(vertex_shader=stage_source(src, "vert"),
                    fragment_shader=stage_source(src, "frag"))
    # Start from the shader's own defaults, then apply the overrides. Setting
    # only the overrides leaves every other uniform at 0, which is not "the
    # defaults" - it is a different shader. With cp_scanlines and cp_rgb_mask at
    # 0 both pattern branches are skipped, cp_gamma at 0 forces the pow branch
    # that a default of 1.0 skips, and cp_min_pitch at 0 divides by zero. Every
    # figure this tool produced before this line was measuring that.
    full = dict(REGISTRY[fn].defaults) if fn in REGISTRY else {}
    full.update(params)
    for k, v in full.items():
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


PASSES = 15
# Whole passes thrown away before anything is recorded. The instability is not
# per-case, it is temporal: the opening passes of a run are erratic no matter
# what is in them, and with rotation that noise lands on whichever cases happen
# to be scheduled early. Discarding the run-in flattens the spread from 34-52%
# to a couple of percent across the board.
WARMUP_PASSES = 8


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

    vaos = []
    for label, fn, params in CASES:
        prog = build(ctx, fn, params)
        names = [n for n in ("VertexCoord", "TexCoord") if n in prog]
        vaos.append(ctx.vertex_array(
            prog, [(vbo, " ".join(["4f4"] * len(names)), *names)]))

    for vao in vaos:                      # warm every program before timing any
        for _ in range(50):
            vao.render(moderngl.TRIANGLE_STRIP)
    ctx.finish()

    # Rotate the starting pointeach pass. Interleaving alone is not enough: the
    # first case measured in a pass catches the clock ramping up, so whichever
    # case sits at index 0 reads noisy every time. Measured as an 11.8% spread
    # on pixellate against 1.3-2.3% on everything else, purely from position.
    passes = [[] for _ in CASES]
    order = list(range(len(CASES)))
    for n in range(WARMUP_PASSES + PASSES):
        # Unmeasured burst first: the GPU drops its clocks between passes while
        # Python is doing bookkeeping, and whatever is measured first eats the
        # ramp. Without this the case in slot 0 reads a 40% spread against
        # 1-3% for everything else, purely from position.
        for _ in range(60):
            vaos[0].render(moderngl.TRIANGLE_STRIP)
        ctx.finish()
        rotated = order[n % len(order):] + order[:n % len(order)]
        for idx in rotated:
            vao = vaos[idx]
            s = []
            for _ in range(DRAWS):
                with q:
                    vao.render(moderngl.TRIANGLE_STRIP)
                s.append(q.elapsed)
            s.sort()
            if n >= WARMUP_PASSES:
                passes[idx].append(s[len(s) // 2] / 1e6)

    print(f"{OW}x{OH} output, {IW}x{IH} source")
    print(f"median of {DRAWS} timer-queried draws, {PASSES} interleaved passes"
          f" after {WARMUP_PASSES} discarded")
    print("(Apple GPU: read the ratios, and only where they clear the spread)\n")

    med = [float(np.median(p)) for p in passes]
    base = med[0]
    # Interquartile range, not min-to-max. The full range is decided by the
    # single worst pass, so one hiccup anywhere in a multi-minute run makes every
    # case look unmeasurable; the IQR describes where the measurements actually
    # sit. Both are computed and the tighter one is what gets quoted.
    def iqr(p):
        return (float(np.percentile(p, 75)) - float(np.percentile(p, 25)))
    noise = max(iqr(p) / np.median(p) for p in passes) * 100

    from spirv_cost import analyse
    static = {}
    for _, fn, _ in CASES:
        if fn not in static:
            a = analyse(fn)
            static[fn] = (a["ops"], a["slots"]) if a else (0, 0)

    print(f"  {'case':<26s} {'ops':>5s} {'SFU':>4s} {'ms':>9s} "
          f"{'vs pixellate':>13s} {'IQR':>6s}")
    for (label, fn, _), m, p in zip(CASES, med, passes):
        spread = iqr(p) / m * 100
        ops, sfu = static[fn]
        print(f"  {label:<26s} {ops:5d} {sfu:4d} {m:9.4f} "
              f"{m / base * 100:12.1f}% {spread:5.1f}%")

    print(f"\n  worst per-case IQR across passes: {noise:.1f}% - "
          f"differences smaller than that are noise, not shaders")
    print("\n  Note the ops and SFU columns against the times: pixellate has the\n"
          "  most SFU by far and is still the fastest thing here, so on this GPU\n"
          "  SFU is not the bottleneck and time tracks ops instead. The device may\n"
          "  well rank them the other way round - that is the open question these\n"
          "  numbers cannot answer.")


if __name__ == "__main__":
    main()
