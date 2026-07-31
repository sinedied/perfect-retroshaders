#!/usr/bin/env python3
"""Run the real shipped .glsl files on the GPU and diff them against their models.

The two implementations are written independently on purpose: an error has to be
made the same way twice to survive this. What it cannot catch is a shared
misunderstanding of the specification, which is what the property tests in
tools/tests are for.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python gl_check.py [-v] [name ...]
"""
import sys

import numpy as np

import moderngl

from core.gpu import gl_render, program
from core.paths import shader_path
from core.shader_source import pragma_defaults, stage_source
from models.registry import REGISTRY
from models.crt import SOURCES

TOLERANCE = 1

def check(ctx, name, model, verbose=False):
    try:
        prog = program(ctx, name)
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
