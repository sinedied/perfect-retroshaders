"""The released shaders, as RetroArch .slang files and .slangp presets.

GENERATED. Nothing under shaders/slang/ is edited by hand - check.py asserts
every file equals a fresh run of this script, so an edit there is reverted by
the next person who regenerates.

    python tools/toslang.py            write shaders/slang/
    python tools/toslang.py --check    exit 1 if anything on disk differs

THE BODY IS COPIED VERBATIM, and that is the whole design. An earlier version
rewrote the shader text - TextureSize became params.SourceSize.xy and so on -
which compiled and was wrong three ways: it rewrote comments, so dmg-mini
explained itself in terms of params.OriginalSize.xy past 80 columns; it produced
params.OutputSize.xy.y; and it emitted `#define Source Source`. Declaring the
old names as macros instead leaves main() character for character identical to
the release, which is both correct and reviewable.

The macros must come AFTER the push constant block, or they rewrite its members.

    released      slang               why
    TextureSize   SourceSize.xy       the porting guide: "IN.texture_size ->
                                      SourceSize.xy (no POT shenanigans, so
                                      they are the same)"
    InputSize     OriginalSize.xy     the *-mini shaders use InputSize to mean
                                      the ORIGINAL core resolution while
                                      sampling a texture already at output
                                      size, which is what OriginalSize is
    OutputSize    OutputSize.xy       same meaning

Push constant blocks are limited to 128 bytes. These run 56-80, so there is
room, but the check is in report() because exceeding it is an error rather than
a warning.
"""

import os
import re
import sys

import common as c

SLANG = os.path.join(c.SHADERS, "slang")
PRESETS = os.path.join(SLANG, "presets")

PARAM = re.compile(
    r'^#pragma parameter (\S+)\s+("[^"]*")\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$', re.M)


def shader(name):
    """One released .glsl as a .slang."""
    src = c.read(name)
    header = src[:src.index("#pragma parameter")].rstrip()
    params = PARAM.findall(src)

    frag = src[src.index("#elif defined(FRAGMENT)"):]
    frag = frag[frag.index("COMPAT_VARYING vec4 TEX0;") + len("COMPAT_VARYING vec4 TEX0;"):]
    frag = frag[:frag.rindex("#endif")]
    # the host supplies these two in slang, so the file's own aliases would be
    # self-referential once Texture is defined as Source
    frag = re.sub(r"#ifdef PARAMETER_UNIFORM.*?#endif\n", "", frag, flags=re.S)
    frag = re.sub(r"^#define (Source Texture|vTexCoord TEX0\.xy)\n", "", frag, flags=re.M)
    frag = frag.strip("\n")

    push = "\n".join(f"\tfloat {p[0]};" for p in params)
    pragmas = "\n".join(
        f"#pragma parameter {p[0]} {p[1]} {p[2]} {p[3]} {p[4]} {p[5]}" for p in params)
    defines = "\n".join(f"#define {p[0]} params.{p[0]}" for p in params)

    return f"""#version 450
{header}

layout(push_constant) uniform Push
{{
\tvec4 SourceSize;
\tvec4 OriginalSize;
\tvec4 OutputSize;
{push}
}} params;

layout(std140, set = 0, binding = 0) uniform UBO
{{
\tmat4 MVP;
}} global;

{pragmas}

// The names the shader body uses, mapped onto slang's. After the Push block, so
// they cannot rewrite its members. Everything below is the released shader.
#define TextureSize params.SourceSize.xy
#define InputSize params.OriginalSize.xy
#define OutputSize params.OutputSize.xy
#define Texture Source
#define COMPAT_TEXTURE texture
#define COMPAT_PRECISION
{defines}

#pragma stage vertex
layout(location = 0) in vec4 Position;
layout(location = 1) in vec2 TexCoord;
layout(location = 0) out vec2 vTexCoord;

void main()
{{
\tgl_Position = global.MVP * Position;
\tvTexCoord = TexCoord;
}}

#pragma stage fragment
layout(location = 0) in vec2 vTexCoord;
layout(location = 0) out vec4 FragColor;
layout(set = 0, binding = 2) uniform sampler2D Source;

#define TEX0 vec4(vTexCoord, 0.0, 0.0)
{frag}
"""


def preset(stem, linear):
    """The .slangp beside it. Without one, filter_linear is unspecified and
    RetroArch falls back to the global video smoothing setting."""
    return f"""# {stem}, one pass. shader0 is relative to this file.
shaders = 1

shader0 = ../{stem}.slang
filter_linear0 = {"true" if linear else "false"}
scale_type0 = viewport
scale0 = 1.0
"""


def build():
    """{relative path: contents} for everything this script owns."""
    out = {}
    for name in sorted(os.listdir(c.SHADERS)):
        if not name.endswith(".glsl"):
            continue
        stem = name[:-5]
        out[f"{stem}.slang"] = shader(name)
        out[os.path.join("presets", f"{stem}.slangp")] = preset(
            stem, c.sampler_is_linear(name))
    return out


def stages(text):
    """The two compilable halves. Lines before the first #pragma stage belong
    to both, which is what makes the Push block and the macros shared."""
    common = text[:text.index("#pragma stage vertex")]
    vert = text[text.index("#pragma stage vertex"):text.index("#pragma stage fragment")]
    frag = text[text.index("#pragma stage fragment"):]
    return (common + vert.replace("#pragma stage vertex", "", 1),
            common + frag.replace("#pragma stage fragment", "", 1))


def write():
    os.makedirs(PRESETS, exist_ok=True)
    for rel, text in build().items():
        with open(os.path.join(SLANG, rel), "w") as f:
            f.write(text)
    return len(build())


def differences():
    """Every file that is missing, stale or undeclared."""
    want = build()
    errors = []
    for rel, text in want.items():
        path = os.path.join(SLANG, rel)
        if not os.path.exists(path):
            errors.append(f"{rel}: not generated yet")
        elif open(path).read() != text:
            errors.append(f"{rel}: differs from a fresh generation")
    for folder, suffix in ((SLANG, ".slang"), (PRESETS, ".slangp")):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(suffix):
                continue
            rel = fn if suffix == ".slang" else os.path.join("presets", fn)
            if rel not in want:
                errors.append(f"{rel}: on disk but nothing generates it")
    return errors


if __name__ == "__main__":
    if "--check" in sys.argv:
        errs = differences()
        for e in errs:
            print(" ", e)
        print(f"slang: {'ok' if not errs else str(len(errs)) + ' stale'}")
        sys.exit(1 if errs else 0)
    n = write()
    print(f"slang: wrote {n} files to shaders/slang")
