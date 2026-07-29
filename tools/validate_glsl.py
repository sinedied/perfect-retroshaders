#!/usr/bin/env python3
"""Validate a .glsl the way the target frontend's loader does.

Replicates the host's shader loader: strips '#pragma parameter' lines, prepends
the version/define/precision preamble, then compiles both stages with
glslangValidator. Existing shipped shaders are used as a control.

Run:  python3 validate_glsl.py <file.glsl> [...]
"""

import os
import subprocess
import sys
import tempfile

PRECISION = (
    "#ifdef GL_ES\n"
    "#ifdef GL_OES_standard_derivatives\n"
    "#extension GL_OES_standard_derivatives : enable\n"
    "#endif\n"
    "#ifdef GL_FRAGMENT_PRECISION_HIGH\n"
    "precision highp float;\n"
    "#else\n"
    "precision mediump float;\n"
    "#endif\n"
    "#endif\n"
    "#define PARAMETER_UNIFORM\n"
)

REPLACE_VERSIONS = [f"#version {v}" for v in
                    (110, 120, 130, 140, 150, 330, 400, 410, 420, 430, 440, 450)]


def preprocess(source, stage):
    cleaned = "".join(l + "\n" for l in source.split("\n")
                      if not l.startswith("#pragma parameter"))

    define = "#define VERTEX\n" if stage == "vert" else "#define FRAGMENT\n"
    precision = "" if stage == "vert" else PRECISION

    vstart = cleaned.find("#version")
    vend = cleaned.find("\n", vstart) if vstart >= 0 else -1

    if vstart >= 0 and vend >= 0:
        header = cleaned[: vend + 1]
        rest = cleaned[vend + 1 :]
        if any(v in header for v in REPLACE_VERSIONS):
            return "#version 300 es\n" + define + precision + rest
        return header + define + precision + rest
    return "#version 100\n" + define + precision + cleaned


def check(path):
    source = open(path).read()
    ok = True
    for stage in ("vert", "frag"):
        text = preprocess(source, stage)
        with tempfile.NamedTemporaryFile("w", suffix="." + stage, delete=False) as f:
            f.write(text)
            tmp = f.name
        r = subprocess.run(["glslangValidator", tmp],
                           capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode != 0:
            ok = False
            out = (r.stdout + r.stderr).strip()
            print(f"  {stage}: FAIL")
            for line in out.split("\n")[:14]:
                if line.strip() and not line.startswith("/"):
                    print(f"      {line}")
        else:
            print(f"  {stage}: ok")
    return ok


if __name__ == "__main__":
    failed = []
    for p in sys.argv[1:]:
        print(os.path.basename(p))
        if not check(p):
            failed.append(p)
    print()
    print(f"{len(sys.argv)-1-len(failed)}/{len(sys.argv)-1} passed")
    sys.exit(1 if failed else 0)
