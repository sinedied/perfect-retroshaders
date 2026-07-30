#!/usr/bin/env python3
"""Static cost of a shader's fragment stage, from SPIR-V.

Counts scalar-expanded transcendentals (vector ops execute per component;
pow = log2+exp2 = 2 SFU slots). Handles helper functions: each function body is
costed separately, then main's cost is expanded by the call graph, so a helper
called twice is counted twice.

TWO THINGS ARE REPORTED, AND THE SECOND PAIR IS THE INTERESTING ONE

The static count walks every instruction in the body regardless of control flow,
so a block behind a uniform branch is counted even when nobody executes it. That
makes the static figure a worst case, and it makes a shader that ADDS a uniform
guard look more expensive than the one it replaces - exactly backwards.
pixel-perfect-v4 guards a 32-instruction block that v3 ran unconditionally, and
reads 13 higher than v3 on the static column.

So each shader is also compiled through spirv-opt twice: once with the
parameters live as uniforms, and once with PARAMETER_UNIFORM undefined so every
parameter resolves to its #define fallback. In the second build the compiler
folds the uniform guards and prunes the blocks a default configuration skips.
The pair is like-for-like, so live -> @def is what the defaults buy.

Three things to know before quoting the @def column:

  - IT UNDERSTATES AN EXPLICIT GUARD. With the parameters as literals the
    optimiser also folds arithmetic that is merely neutral - v3's col*1.0 + 0.0
    collapses even though it has no guard at all - and no runtime can do that
    with live uniforms. So it is a lower bound on what a guard actually saves,
    not an upper one.
  - it EXCLUDES nothing else: the guard tests are gone along with the uniforms,
    so the true default-path cost is this figure plus a few scalar compares.
  - it is only meaningful if each #define fallback matches that parameter's
    #pragma default. check_headers.py verifies exactly that, and three shaders
    currently disagree - see the note it prints.

The `ops` column is left unoptimised, because every cost figure recorded in
AGENTS.md is in those units and re-basing them would invalidate the lot.

Run:  PYTHONPATH=. python3 spirv_cost.py
"""
import collections
import os
import re
import subprocess
import tempfile

from gl_check import stage_source

from paths import shader_path, list_shaders
COST = {'Pow': 2, 'Exp': 1, 'Exp2': 1, 'Log': 1, 'Log2': 1, 'Sqrt': 1,
        'InverseSqrt': 1, 'Sin': 1, 'Cos': 1, 'Tan': 2, 'Atan': 2}


# Folding and dead-branch removal only. Enough to resolve a guard whose
# condition is a literal and drop what it skips; not a full -O, which would
# rewrite enough of the body that the figure stopped being comparable to the
# unoptimised column beside it.
OPT_PASSES = ['--ccp', '--eliminate-dead-branches', '--simplify-instructions',
              '--eliminate-dead-code-aggressive']


def disassemble(fn, at_defaults=False, optimise=False):
    src = open(shader_path(fn)).read()
    body = stage_source(src, 'frag')
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


def analyse(fn, at_defaults=False, optimise=False):
    dis = disassemble(fn, at_defaults, optimise)
    if dis is None:
        return None
    width = {}
    for m in re.finditer(r'(%\w+)\s*=\s*OpTypeVector\s+%\w+\s+(\d+)', dis):
        width[m.group(1)] = int(m.group(2))
    for m in re.finditer(r'(%\w+)\s*=\s*OpTypeFloat', dis):
        width[m.group(1)] = 1
    names = {}
    for m in re.finditer(r'OpName\s+(%\w+)\s+"([^"]+)"', dis):
        names[m.group(1)] = m.group(2)

    # split into function bodies, keyed by result id
    funcs = {}
    cur = None
    for line in dis.split('\n'):
        m = re.match(r'\s*(%\w+)\s*=\s*OpFunction\b', line)
        if m:
            cur = m.group(1)
            funcs[cur] = dict(ops=0, tex=0, sfu=collections.Counter(), calls=collections.Counter())
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
        c = re.search(r'OpFunctionCall\s+%\w+\s+(%\w+)', line)
        if c:
            f['calls'][c.group(1)] += 1
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
    slots = sum(COST[k] * v for k, v in sfu.items())
    return dict(ops=ops, tex=tex, sfu=sfu, slots=slots)


if __name__ == '__main__':
    print(f"{'':<28s} {'unoptimised':>16s} {'  folded: live -> defaults':>28s}")
    print(f"{'shader':<28s} {'ops':>5s} {'tex':>4s} {'SFU':>5s}   "
          f"{'live':>5s} {'@def':>5s} {'SFU@def':>8s}   breakdown (scalar lanes)")
    for fn in list_shaders(include_vendor=True, include_iterations=True):
        a = analyse(fn)
        if not a:
            print(f"{fn:<28s} skip")
            continue
        live = analyse(fn, optimise=True)
        d = analyse(fn, at_defaults=True, optimise=True)
        bd = ', '.join(f"{k}x{v}" for k, v in sorted(a['sfu'].items()))
        c = (f"{live['ops']:5d} {d['ops']:5d} {d['slots']:8d}"
             if live and d else f"{'?':>5s} {'?':>5s} {'?':>8s}")
        print(f"{fn:<28s} {a['ops']:5d} {a['tex']:4d} {a['slots']:5d}   "
              f"{c}   {bd}")
    print("\n'live' and '@def' are both folded by spirv-opt, so they compare"
          "\nlike for like; the drop between them is what leaving every slider"
          "\nalone buys. It UNDERSTATES an explicit guard, because with the"
          "\nparameters as literals the optimiser also folds arithmetic that is"
          "\nmerely neutral - which no runtime can do with live uniforms.")
