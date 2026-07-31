#!/usr/bin/env python3
"""One command for checking a shader.

There used to be nine, each run by hand from tools/ with PYTHONPATH set, and no
way to say "check what I just changed". The ordering mattered and was not
written down anywhere, so it was easy to change a shader, run the two fast
checks, and miss that the model no longer agreed with it.

    python -m tools.verify                 fast, everything shipping
    python -m tools.verify crt-perfect     fast, one family
    python -m tools.verify --full          add the archive and the long sweeps
    python -m tools.verify --visual        render comparison sheets to look at
    python -m tools.verify --bench         GPU timings

The fast tier is the one that has to stay cheap enough to run every time. It
compiles, checks headers and contracts, and runs the property tests: a few
seconds. Everything that walks the archive, supersamples or renders a full
matrix is behind --full.

--visual is not optional for a change that moves geometry. crt-perfect-v7 passed
every number in this file while having cropped its border off-screen.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PY = os.path.join(REPO, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

# Run as `python -m tools.verify` from the repo root, but the harness modules
# import each other as top-level names (core.*, models.*), so tools/ has to be
# importable in its own right too.
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def run(label, args, cwd=HERE, env_extra=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([HERE, os.path.join(HERE, "tests")])
    env.update(env_extra or {})
    print(f"\n=== {label}", flush=True)
    r = subprocess.run([PY] + args, cwd=cwd, env=env)
    return r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tools.verify", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("family", nargs="?",
                    help="crt-perfect, lcd-perfect, pixel-perfect or dmg-perfect")
    ap.add_argument("--full", action="store_true",
                    help="archive versions and the long measurement sweeps")
    ap.add_argument("--visual", action="store_true",
                    help="render comparison sheets into tools/preview/")
    ap.add_argument("--bench", action="store_true", help="GPU timings")
    a = ap.parse_args(argv)

    from core import manifest

    if a.family and a.family not in manifest.families():
        ap.error(f"unknown family {a.family!r}; "
                 f"expected one of {', '.join(manifest.families())}")

    fail = 0
    scope = ([manifest.current(a.family), manifest.released(a.family)]
             if a.family else manifest.default_scope())
    scope = sorted(set(scope))

    fail |= run("compile", ["validate_glsl.py"]
                + [os.path.join(REPO, "shaders", n) for n in scope]) != 0
    fail |= run("headers", ["check_headers.py"] + scope) != 0

    k = ["-k", a.family.replace("-", "_")] if a.family else []
    marks = ["-m", ""] if a.full else []
    fail |= run("properties", ["-m", "pytest", "tests"] + k + marks) != 0

    if a.full:
        fail |= run("gpu vs model", ["gl_check.py"]) != 0
        fail |= run("moire", ["beat.py"]) != 0
        fail |= run("cost", ["spirv_cost.py"]) != 0
    if a.visual:
        fail |= run("preview", ["preview.py"]) != 0
    if a.bench:
        fail |= run("bench", ["bench_glsl.py"]) != 0

    print("\nFAILED" if fail else "\nok", flush=True)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
