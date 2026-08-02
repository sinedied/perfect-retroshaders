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
    python tools/perf.py --max               each shader at defaults and all on
    python tools/perf.py --cost lcd-perfect  what each effect costs, on its own
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


def _disassemble(name, at_defaults=False, optimise=False, values=None):
    body = c.stage_source(c.read(name), 'frag')
    if at_defaults:
        # drop the uniform declarations, so every parameter becomes its #define
        # fallback and the guards it feeds become compile-time constants
        body = body.replace("#define PARAMETER_UNIFORM\n", "")
        # and optionally rewrite those fallbacks, which is how a setting other
        # than the shipped default can be folded: the guards then resolve the
        # other way and the blocks they protect stay in the count
        for k, v in (values or {}).items():
            body = re.sub(rf"^#define {k} [-\d.]+$", f"#define {k} {v}",
                          body, flags=re.M)
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


def static(name, at_defaults=False, optimise=False, values=None):
    """Fragment-stage instruction and SFU counts.

    The unoptimised figure walks every instruction regardless of control flow,
    so a block behind a uniform guard is counted even when nobody executes it.
    That makes it a worst case, and makes a shader that ADDS a guard look more
    expensive than the one it replaces - exactly backwards. Hence the folded
    columns beside it.
    """
    dis = _disassemble(name, at_defaults, optimise, values)
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

# Parameters whose cost is a branch, not a value: the shader skips the block
# entirely at the neutral setting, so what a feature costs is only visible with
# it turned on. Everything else is arithmetic that runs regardless, so pushing
# it to the end of its range measures nothing.
MAXED = {
    "cp_scanlines": 1.0, "cp_rgb_mask": 1.0, "cp_curvature": 0.15,
    "cp_gamma": 1.40,
    "lp_grid": 1.0, "lp_subpixels": 1.0, "lp_gamma": 1.40,
    "dp_grid": 1.0, "dp_shadow": 1.0, "dp_temperature": 0.5, "dp_tint": 0.5,
    "pp_saturation": 1.5, "pp_gamma": 1.40, "pp_temperature": 0.5,
    "pp_tint": 0.5,
}

# Modes rather than intensities. A slot mask is not "more mask", so it does not
# belong in MAXED or in the README's "everything on" row - but it is a whole
# branch, and a breakdown that never prices it is not a breakdown. --cost reads
# these on top of MAXED and nothing else does.
COST_MODES = {"cp_mask_type": 2.0}


# --------------------------------------------------------------------------
# per-effect cost
#
# What a feature costs is the difference between everything being on and
# everything being on but that one thing, which is not the same as what it costs
# on its own: features share setup, and the sum of the marginals is reported
# next to the true total so the gap is visible rather than implied.

def _off_value(name, param):
    """The setting at which a parameter does nothing.

    baseline.toml's `neutral` block is the authority - it is the same block the
    scaler anchor uses, and tests/contracts.py proves it covers everything that
    acts. A parameter it omits does not act at all, so its own default is
    already neutral.
    """
    neutral = c.declared(name).get("neutral") or {}
    if param in neutral:
        return float(neutral[param])
    return c.parameters(name)[param][1]


def cost_cases(name):
    """[(label, name, params)]: the plain scaler, everything on, and each
    feature both alone on top of neutral and subtracted from everything on.

    Both, because either on its own lies. Alone misses what a feature adds to
    machinery something else has already paid for; marginal misses everything it
    shares - crt's scanlines read 2 ops marginally, because with a slot mask on,
    the pitch and lock terms they need are already there.
    """
    params = c.parameters(name)
    on = {k: v[1] for k, v in params.items()}
    on.update({k: v for k, v in MAXED.items() if k in params})
    on.update({k: v for k, v in COST_MODES.items() if k in params})
    neutral = {k: _off_value(name, k) for k in params}

    cases = [("neutral", name, neutral), ("all on", name, on)]
    for p in params:
        if abs(on[p] - neutral[p]) <= 1e-9:
            continue
        cases.append((f"+{p}", name, dict(neutral, **{p: on[p]})))
        cases.append((f"-{p}", name, dict(on, **{p: neutral[p]})))
    return cases


def cost_report(name, timed):
    """One shader's breakdown. `timed` maps a case label to milliseconds."""
    cases = cost_cases(name)
    counts = {label: static(name, at_defaults=True, optimise=True, values=p)
              for label, _n, p in cases}
    full, floor = counts["all on"], counts["neutral"]
    span = max(full['ops'] - floor['ops'], 1)
    feats = [lab[1:] for lab, _n, _p in cases if lab.startswith("+")]

    def ms(label):
        return timed.get(label, 0.0)

    print(f"\n{name}")
    print(f"  plain scaler {floor['ops']:>4d} ops, {floor['tex']} tex, "
          f"{floor['slots']} SFU" + (f", {ms('neutral'):.4f} ms" if timed else "")
          + f"   |   everything on {full['ops']:>4d} ops, {full['tex']} tex, "
          f"{full['slots']} SFU" + (f", {ms('all on'):.4f} ms" if timed else ""))
    head = (f"  {'feature':<16s} {'alone':>6s} {'%eff':>6s} {'marg':>6s} "
            f"{'%eff':>6s} {'SFU':>4s} {'tex':>4s}")
    if timed:
        head += f" {'ms':>8s} {'%all':>6s}"
    print(head)

    alone_sum = marg_sum = 0
    for p in feats:
        alone = counts[f"+{p}"]['ops'] - floor['ops']
        marg = full['ops'] - counts[f"-{p}"]['ops']
        alone_sum += alone
        marg_sum += marg
        line = (f"  {p:<16s} {alone:6d} {alone / span * 100:5.1f}% "
                f"{marg:6d} {marg / span * 100:5.1f}% "
                f"{counts[f'+{p}']['slots'] - floor['slots']:4d} "
                f"{counts[f'+{p}']['tex'] - floor['tex']:4d}")
        if timed:
            d = ms(f"+{p}") - ms("neutral")
            line += f" {d:8.4f} {d / max(ms('all on'), 1e-9) * 100:5.1f}%"
        print(line)

    # Neither column has to add up to the span, and that is the useful part:
    # alone over it is shared setup paid twice, marginal under it is shared
    # setup nobody is charged for.
    print(f"  {'sum':<16s} {alone_sum:6d} {alone_sum / span * 100:5.1f}% "
          f"{marg_sum:6d} {marg_sum / span * 100:5.1f}%   "
          f"(effects span {span} ops over the plain scaler)")


def run_cost(names, static_only):
    cases = []
    for name in names:
        cases += [(f"{name}::{lab}", n, p) for lab, n, p in cost_cases(name)]
    timed = {}
    if not static_only:
        med, _iqr = time_cases(cases)
        timed = {lab: m for (lab, _n, _p), m in zip(cases, med)}
    for name in names:
        cost_report(name, {k.split("::", 1)[1]: v for k, v in timed.items()
                           if k.startswith(name + "::")})
    print("\n  alone: that feature on top of the plain scaler. marginal:"
          "\n  everything on, minus that one. %eff is against what the effects"
          "\n  add over the plain scaler; ms is the alone figure, against the"
          "\n  whole shader with everything on.")
    return 0


def build_cases(names, sweep, maxed=False):
    """One row per shader, plus one per swept value where the shader has it."""
    cases = []
    for name in names:
        if maxed:
            over = {k: v for k, v in MAXED.items() if k in c.parameters(name)}
            cases.append((f"{name}  defaults", name, {}))
            if over:
                cases.append((f"{name}  everything on", name, over))
            continue
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
    if "--cost" in sys.argv:
        return run_cost(names, "--static" in sys.argv)

    for r in REFERENCES:
        if r not in names:
            names = [r] + names if r == REFERENCES[0] else names + [r]

    cases = build_cases(names, sweep, "--max" in sys.argv)
    stats = {}
    for _l, name, _p in cases:
        if name not in stats:
            a = static(name)
            folded = static(name, optimise=True)
            at_def = static(name, at_defaults=True, optimise=True)
            stats[name] = (a, folded, at_def)

    if "--static" in sys.argv and "--max" in sys.argv:
        # Active instructions: what survives folding once the parameters are
        # literals. The unoptimised column cannot show what a setting costs,
        # since it counts both arms of every guard - which is the whole point
        # of guarding them.
        print(f"{'shader':<24s} {'all paths':>9s} {'defaults':>9s} "
              f"{'all on':>7s} {'tex':>4s} {'SFU@def':>8s}")
        for name in dict.fromkeys(n for _l, n, _p in cases):
            a = static(name)
            d = static(name, at_defaults=True, optimise=True)
            over = {k: v for k, v in MAXED.items() if k in c.parameters(name)}
            m = static(name, at_defaults=True, optimise=True, values=over) if over else d
            print(f"{name:<24s} {a['ops']:9d} {d['ops']:9d} {m['ops']:7d} "
                  f"{a['tex']:4d} {d['slots']:8d}")
        return 0

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
    # Reported as throughput against the baseline, not as frame time: bigger is
    # better, and a budget is easier to reason about that way round. 127% means
    # the same GPU time buys 27% more frames than the baseline shader.
    print(f"  {'case':<34s} {'ops':>5s} {'tex':>4s} {'SFU':>4s} {'ms':>9s} "
          f"{'vs ' + cases[0][0][:12]:>15s} {'IQR':>6s}")
    for (label, name, _p), m, q in zip(cases, med, iqr):
        a = stats[name][0] or dict(ops=0, tex=0, slots=0)
        s = "L" if c.sampler_is_linear(name) else "N"
        print(f"  {label:<34s} {a['ops']:5d} {a['tex']:3d}{s} {a['slots']:4d} "
              f"{m:9.4f} {base / m * 100:14.1f}% {q / m * 100:5.1f}%")
    worst = max(q / m * 100 for m, q in zip(med, iqr))
    print(f"\n  worst per-case IQR: {worst:.1f}% - differences smaller than "
          f"that are\n  noise, not shaders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
