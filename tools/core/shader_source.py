#!/usr/bin/env python3
"""Turning a shader file into something a GL context will accept, and reading
what it declares. Text in, text out - no GL and no numpy, so it can be used by
tools that never render.
"""

import re

from core.paths import shader_path

HEADER = "#version 410 core\n"

# rounding between float32 on the GPU and float64 in the model
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


