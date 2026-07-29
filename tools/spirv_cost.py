#!/usr/bin/env python3
"""Static cost of a shader's fragment stage, from SPIR-V.

Counts scalar-expanded transcendentals (vector ops execute per component;
pow = log2+exp2 = 2 SFU slots). Handles helper functions: each function body is
costed separately, then main's cost is expanded by the call graph, so a helper
called twice is counted twice.

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


def disassemble(fn):
    src = open(shader_path(fn)).read()
    with tempfile.NamedTemporaryFile('w', suffix='.frag', delete=False) as f:
        f.write(stage_source(src, 'frag'))
        tmp = f.name
    spv = tmp + '.spv'
    r = subprocess.run(['glslangValidator', '-G', '--aml', '-o', spv, tmp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        os.unlink(tmp)
        return None
    dis = subprocess.run(['spirv-dis', '--no-color', spv],
                         capture_output=True, text=True).stdout
    os.unlink(tmp)
    os.unlink(spv)
    return dis


def analyse(fn):
    dis = disassemble(fn)
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
    print(f"{'shader':<28s} {'ops':>4s} {'tex':>4s} {'SFU slots':>10s}   breakdown (scalar lanes)")
    for fn in list_shaders(include_vendor=True, include_iterations=True):
        a = analyse(fn)
        if not a:
            print(f"{fn:<28s} skip")
            continue
        bd = ', '.join(f"{k}x{v}" for k, v in sorted(a['sfu'].items()))
        print(f"{fn:<28s} {a['ops']:4d} {a['tex']:4d} {a['slots']:10d}   {bd}")
