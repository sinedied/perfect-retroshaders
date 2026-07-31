#!/usr/bin/env python3
"""What a shader costs: static instruction count, and time on this GPU.

NOT A GATE, deliberately. Timing moves a few percent with laptop thermals and
this is not the target chip, so nothing here fails a build. Run it when you want
to compare two shaders and read the ratios.

The two columns disagree and both matter. `ops` and `SFU` come from SPIR-V and
are deterministic; `ms` is wall clock on whatever GPU is in this machine. Among
the four-tap rows, pixellate has by far the most SFU and is still the fastest,
so on this GPU SFU is not the bottleneck and time tracks ops instead. The device
may rank it the other way round, and nothing here can say.

    python tools/perf.py                     working set against the references
    python tools/perf.py crt-perfect         one family
    python tools/perf.py --static            skip the timing, SPIR-V only
    python tools/perf.py --sweep cp_curvature=0,0.1 crt-perfect-v10.glsl
"""

import collections
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

OW, OH = 1024, 768
IW, IH = 320, 240
DRAWS = 200
PASSES = 15
# Whole passes thrown away before anything is recorded. The instability is
# temporal, not per-case: the opening passes of a run are erratic no matter what
# is in them, and with rotation that noise lands on whichever cases happen to be
# scheduled early. Discarding the run-in flattens the spread from 34-52% to a
# couple of percent across the board.
WARMUP = 8

# The references every measurement here is read against: pixellate is the budget
# yardstick, and the two one-tap shaders are the floor, computing the same area
# average by handing the blend to the texture unit.
REFERENCES = ["pixellate.glsl", "sharp-shimmerless.glsl",
              "sharp-shimmerless-grid.glsl"]


# --------------------------------------------------------------------------
# static cost
#
# Scalar-expanded transcendentals: vector ops execute per component, and
# pow = log2 + exp2 = two SFU slots. Helper functions are costed separately and
# main's cost expanded by the call graph, so a helper called twice counts twice.

COST = {'Pow': 2, 'Exp': 1, 'Exp2': 1, 'Log': 1, 'Log2': 1, 'Sqrt': 1,
        'InverseSqrt': 1, 'Sin': 1, 'Cos': 1, 'Tan': 2, 'Atan': 2}

# Folding and dead-branch removal only. Enough to resolve a guard whose
# condition is a literal and drop what it skips; not a full -O, which would
# rewrite enough of the body that the figure stopped being comparable.
OPT_PASSES = ['--ccp', '--eliminate-dead-branches', '--simplify-instructions',
              '--eliminate-dead-code-aggressive']


def _disassemble(name, at_defaults=False, optimise=False):
    body = c.stage_source(c.read(name), 'frag')
    if at_defaults:
        # drop the uniform declarations, so every parameter becomes its #define
        # fallback and the guards it feeds become compile-time constants
        body = body.replace("#define PARAMETER_UNIFORM\n", "")
    with tempfile.NamedTemporaryFile('w', suffix='.frag', delete=False) as f:
        f.write(body)
        tmp = f.name
    spv = tmp + '.spv'
    r = subprocess.run(['glslangValidator', '-G', '--aml', '-o', spv, tmp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        os.unlink(tmp)
        return None
    if optimise:
        subprocess.run(['spirv-opt', *OPT_PASSES, spv, '-o', spv],
                       capture_output=True, text=True)
    dis = subprocess.run(['spirv-dis', '--no-color', spv],
                         capture_output=True, text=True).stdout
    os.unlink(tmp)
    os.unlink(spv)
    return dis


def static(name, at_defaults=False, optimise=False):
    """Fragment-stage instruction and SFU counts.

    The unoptimised figure walks every instruction regardless of control flow,
    so a block behind a uniform guard is counted even when nobody executes it.
    That makes it a worst case, and makes a shader that ADDS a guard look more
    expensive than the one it replaces - exactly backwards. Hence the folded
    columns beside it.
    """
    dis = _disassemble(name, at_defaults, optimise)
    if dis is None:
        return None
    width = {}
    for m in re.finditer(r'(%\w+)\s*=\s*OpTypeVector\s+%\w+\s+(\d+)', dis):
        width[m.group(1)] = int(m.group(2))
    for m in re.finditer(r'(%\w+)\s*=\s*OpTypeFloat', dis):
        width[m.group(1)] = 1
    names = {m.group(1): m.group(2)
             for m in re.finditer(r'OpName\s+(%\w+)\s+"([^"]+)"', dis)}

    funcs, cur = {}, None
    for line in dis.split('\n'):
        m = re.match(r'\s*(%\w+)\s*=\s*OpFunction\b', line)
        if m:
            cur = m.group(1)
            funcs[cur] = dict(ops=0, tex=0, sfu=collections.Counter(),
                              calls=collections.Counter())
            continue
        if cur is None:
            continue
        if 'OpFunctionEnd' in line:
            cur = None
            continue
        f = funcs[cur]
        if re.search(r'\bOp[A-Z]', line):
            f['ops'] += 1
        if 'OpImageSample' in line:
            f['tex'] += 1
        call = re.search(r'OpFunctionCall\s+%\w+\s+(%\w+)', line)
        if call:
            f['calls'][call.group(1)] += 1
        e = re.search(r'=\s*OpExtInst\s+(%\w+)\s+%\w+\s+(\w+)', line)
        if e and e.group(2) in COST:
            f['sfu'][e.group(2)] += width.get(e.group(1), 1)

    main_id = next((i for i, n in names.items() if n == 'main'), None)
    if main_id is None or main_id not in funcs:
        main_id = max(funcs, key=lambda k: funcs[k]['ops'])

    def expand(fid, seen=()):
        f = funcs[fid]
        ops, tex = f['ops'], f['tex']
        sfu = collections.Counter(f['sfu'])
        for callee, n in f['calls'].items():
            if callee in funcs and callee not in seen:
                o, t, s = expand(callee, seen + (fid,))
                ops += o * n
                tex += t * n
                for k, v in s.items():
                    sfu[k] += v * n
        return ops, tex, sfu

    ops, tex, sfu = expand(main_id)
    return dict(ops=ops, tex=tex, sfu=sfu, slots=sum(COST[k] * v
                                                     for k, v in sfu.items()))


# --------------------------------------------------------------------------
# timing
#
# Two things about method, both learned the hard way.
#
# Timing a loop of identical draws with one glFinish at the end does not work:
# the driver coalesces them and the cost per draw falls as the loop grows, 8.6
# to 4.8 us going from 100 to 1600 draws, which is not real work. Use per-draw
# timer queries and take the median.
#
# Measuring each shader to completion before starting the next does not work
# either. The GPU clocks around during a run, so a case measured late reads slow
# for reasons that have nothing to do with it - which is how pixellate once came
# out both the fastest and the slowest row on different runs. Interleave, rotate
# the starting point each pass, and discard a run-in.

def _bind(ctx, name, params):
    import moderngl
    prog = c.program(ctx, name)
    full = c.defaults(name)
    full.update(params)
    for k, v in full.items():
        if k in prog:
            prog[k].value = float(v)
    for n, v in (("OutputSize", (float(OW), float(OH))),
                 ("TextureSize", (float(IW), float(IH))),
                 ("InputSize", (float(IW), float(IH))),
                 ("OrigTextureSize", (float(IW), float(IH))),
                 ("OrigInputSize", (float(IW), float(IH)))):
        if n in prog:
            prog[n].value = v
    if "MVPMatrix" in prog:
        prog["MVPMatrix"].write(np.identity(4, "f4").tobytes())
    if "Texture" in prog:
        prog["Texture"].value = 0
    return prog


def time_cases(cases):
    """cases is [(label, shader name, params)]. Returns median ms and IQR %."""
    import moderngl
    ctx = c.context()
    q = ctx.query(time=True)
    rng = np.random.default_rng(1)
    pixels = rng.integers(0, 255, (IH, IW, 3), dtype=np.uint8).tobytes()

    texes = {}
    for linear, f in ((False, moderngl.NEAREST), (True, moderngl.LINEAR)):
        t = ctx.texture((IW, IH), 3, pixels)
        t.filter = (f, f)
        t.repeat_x = t.repeat_y = False
        texes[linear] = t

    verts = np.array([-1, 1, 0, 1, 0, 1, 0, 0, -1, -1, 0, 1, 0, 0, 0, 0,
                      1, 1, 0, 1, 1, 1, 0, 0, 1, -1, 0, 1, 1, 0, 0, 0], "f4")
    vbo = ctx.buffer(verts.tobytes())
    fbo = ctx.framebuffer(color_attachments=[ctx.texture((OW, OH), 3)])
    fbo.use()
    ctx.viewport = (0, 0, OW, OH)

    vaos, filts = [], []
    for _label, name, params in cases:
        prog = _bind(ctx, name, params)
        attrs = [n for n in ("VertexCoord", "TexCoord") if n in prog]
        vaos.append(ctx.vertex_array(
            prog, [(vbo, " ".join(["4f4"] * len(attrs)), *attrs)]))
        filts.append(c.sampler_is_linear(name))

    for vao, filt in zip(vaos, filts):  # warm every program before timing any
        texes[filt].use(0)
        for _ in range(50):
            vao.render(moderngl.TRIANGLE_STRIP)
    ctx.finish()

    passes = [[] for _ in cases]
    order = list(range(len(cases)))
    for n in range(WARMUP + PASSES):
        # Unmeasured burst first: the GPU drops its clocks between passes while
        # Python does bookkeeping, and whatever is measured first eats the ramp.
        # Without this the case in slot 0 reads a 40% spread against 1-3% for
        # everything else, purely from position.
        for _ in range(60):
            texes[filts[0]].use(0)
            vaos[0].render(moderngl.TRIANGLE_STRIP)
        ctx.finish()
        for idx in order[n % len(order):] + order[:n % len(order)]:
            texes[filts[idx]].use(0)
            s = []
            for _ in range(DRAWS):
                with q:
                    vaos[idx].render(moderngl.TRIANGLE_STRIP)
                s.append(q.elapsed)
            s.sort()
            if n >= WARMUP:
                passes[idx].append(s[len(s) // 2] / 1e6)

    # Interquartile range, not min to max. The full range is decided by the
    # single worst pass, so one hiccup anywhere in a multi-minute run makes
    # every case look unmeasurable.
    med = [float(np.median(p)) for p in passes]
    iqr = [float(np.percentile(p, 75) - np.percentile(p, 25)) for p in passes]
    return med, iqr


# --------------------------------------------------------------------------

def build_cases(names, sweep):
    """One row per shader, plus one per swept value where the shader has it."""
    cases = []
    for name in names:
        if not sweep:
            cases.append((name, name, {}))
            continue
        param, values = sweep
        if param not in c.parameters(name):
            cases.append((name, name, {}))
            continue
        for v in values:
            cases.append((f"{name}  {param}={v:g}", name, {param: v}))
    return cases


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    sweep = None
    for a in sys.argv[1:]:
        if a.startswith("--sweep"):
            spec = a.split("=", 1)[1] if "=" in a else args.pop(0)
            param, vals = spec.split("=", 1)
            sweep = (param, [float(v) for v in vals.split(",")])

    names = c.resolve(args)
    for r in REFERENCES:
        if r not in names:
            names = [r] + names if r == REFERENCES[0] else names + [r]

    cases = build_cases(names, sweep)
    stats = {}
    for _l, name, _p in cases:
        if name not in stats:
            a = static(name)
            folded = static(name, optimise=True)
            at_def = static(name, at_defaults=True, optimise=True)
            stats[name] = (a, folded, at_def)

    if "--static" in sys.argv:
        print(f"{'shader':<30s} {'ops':>5s} {'tex':>4s} {'SFU':>5s}   "
              f"{'live':>5s} {'@def':>5s} {'SFU@def':>8s}   breakdown")
        for name in stats:
            a, live, d = stats[name]
            if not a:
                print(f"{name:<30s} skip")
                continue
            bd = ', '.join(f"{k}x{v}" for k, v in sorted(a['sfu'].items()))
            tail = (f"{live['ops']:5d} {d['ops']:5d} {d['slots']:8d}"
                    if live and d else f"{'?':>5s} {'?':>5s} {'?':>8s}")
            print(f"{name:<30s} {a['ops']:5d} {a['tex']:4d} {a['slots']:5d}   "
                  f"{tail}   {bd}")
        print("\n'live' and '@def' are both folded by spirv-opt so they compare"
              "\nlike for like; the drop between them is what leaving every"
              "\nslider alone buys. It UNDERSTATES an explicit guard: with the"
              "\nparameters as literals the optimiser also folds arithmetic"
              "\nthat is merely neutral, which no runtime can do with live"
              "\nuniforms.")
        return 0

    med, iqr = time_cases(cases)
    base = med[0]
    print(f"\n{OW}x{OH} output, {IW}x{IH} source. Median of {DRAWS} timer-"
          f"queried draws,\n{PASSES} interleaved passes after {WARMUP} "
          f"discarded. Not the target GPU: read\nthe ratios, and only where "
          f"they clear the spread.\n")
    print(f"  {'case':<34s} {'ops':>5s} {'tex':>4s} {'SFU':>4s} {'ms':>9s} "
          f"{'vs ' + cases[0][0][:12]:>15s} {'IQR':>6s}")
    for (label, name, _p), m, q in zip(cases, med, iqr):
        a = stats[name][0] or dict(ops=0, tex=0, slots=0)
        s = "L" if c.sampler_is_linear(name) else "N"
        print(f"  {label:<34s} {a['ops']:5d} {a['tex']:3d}{s} {a['slots']:4d} "
              f"{m:9.4f} {m / base * 100:14.1f}% {q / m * 100:5.1f}%")
    worst = max(q / m * 100 for m, q in zip(med, iqr))
    print(f"\n  worst per-case IQR: {worst:.1f}% - differences smaller than "
          f"that are\n  noise, not shaders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
