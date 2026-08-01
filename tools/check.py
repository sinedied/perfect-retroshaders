#!/usr/bin/env python3
"""Static checks: does it compile, and does its header still describe it.

Neither needs a GPU, both are fast, and both catch things nothing else can. A
shader that fails to compile on the device just shows a black screen; a header
that has drifted from the #pragma lines underneath it lies to the person reading
the slider.

    python tools/check.py                  everything declared
    python tools/check.py crt-perfect      one family
    python tools/check.py crt-perfect-v5b.glsl one shader
"""

import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

WIDTH = 80
SEP = "// " + "-" * (WIDTH - 3)

# Lines a description may run to, excluding blanks and the Notes list. Enough
# for what it draws and what it looks like; not enough for how it works.
DESC_MAX = 6

# "  name  0.00 - 1.00  Description." or "  name  0 / 1  Description."
ENTRY = re.compile(r'^//   (\w+)\s\s+(-?[\d.]+(?:\s*[-/]\s*-?[\d.]+)+)\s\s+\S')
DEFINE = re.compile(r'^#define\s+(\w+)\s+(-?[\d.]+)\s*$')

# The frontend's own preamble, reproduced so a compile here means a compile
# there. It targets ESSL, not the desktop GL the render tools use.
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
DESKTOP_VERSIONS = [f"#version {v}" for v in
                    (110, 120, 130, 140, 150, 330, 400, 410, 420, 430, 440, 450)]


def _preprocess(source, stage):
    """Exactly what the host's loader does, including its version substitution."""
    cleaned = "".join(l + "\n" for l in source.split("\n")
                      if not l.startswith("#pragma parameter"))
    define = "#define VERTEX\n" if stage == "vert" else "#define FRAGMENT\n"
    precision = "" if stage == "vert" else PRECISION

    start = cleaned.find("#version")
    end = cleaned.find("\n", start) if start >= 0 else -1
    if start >= 0 and end >= 0:
        header, rest = cleaned[:end + 1], cleaned[end + 1:]
        if any(v in header for v in DESKTOP_VERSIONS):
            return "#version 300 es\n" + define + precision + rest
        return header + define + precision + rest
    return "#version 100\n" + define + precision + cleaned


def compiles(name):
    """Compile both stages with glslangValidator. Returns a list of errors."""
    source = c.read(name)
    errors = []
    for stage in ("vert", "frag"):
        with tempfile.NamedTemporaryFile("w", suffix="." + stage,
                                         delete=False) as f:
            f.write(_preprocess(source, stage))
            tmp = f.name
        r = subprocess.run(["glslangValidator", tmp], capture_output=True,
                           text=True)
        os.unlink(tmp)
        if r.returncode != 0:
            out = [l for l in (r.stdout + r.stderr).strip().split("\n")
                   if l.strip() and not l.startswith("/")]
            errors.append(f"{stage}: " + "; ".join(out[:6]))
    return errors


def _parse_range(text):
    """A dash range or slash-separated discrete values, both to (min, max)."""
    nums = [float(n) for n in re.findall(r'-?[\d.]+', text)]
    return min(nums), max(nums)


def header(name):
    """The header format, and whether it still agrees with the shader.

    The PARAMETERS block is what someone reads before touching a slider, so a
    range edited in the #pragma and forgotten in the block is a lie with no
    other symptom.
    """
    lines = c.read(name).split("\n")
    errors = []

    body = next((i for i, l in enumerate(lines) if not l.startswith("//")),
                len(lines))
    head, rest = lines[:body], lines[body:]
    if not head:
        return ["header is not a // comment block"]

    for i, line in enumerate(head, 1):
        if len(line) > WIDTH:
            errors.append(f"line {i}: {len(line)} columns, over {WIDTH}")
    if any("/*" in l for l in head):
        errors.append("header uses a block comment; the format is line comments")

    # "// dmg-perfect v9 - a Game Boy dot matrix over a pixel-perfect scale."
    # The version lives here, not in the filename: a release copy is
    # <family>.glsl with no suffix and still has to say which iteration it is.
    m = re.match(r'^// ([a-z][a-z-]*) v([0-9]+[a-z]?) - \S.*\.$', head[0])
    if not m:
        errors.append('first line should be "// <family> v<N> - <description '
                      'ending in a period.>"')
    else:
        fam, ver = m.group(1), m.group(2)
        if fam != c.family(name):
            errors.append(f"header says {fam} but it is declared as "
                          f"{c.family(name)}")
        # The check that would have caught pixel-perfect-v6 shipping a header
        # reading v5: a copy nobody remembered to renumber.
        on_disk = c.filename_version(name)
        if on_disk is not None and on_disk != ver:
            errors.append(f"header says v{ver} but the filename says v{on_disk}")

    seps = [i for i, l in enumerate(head) if l == SEP]
    if len(seps) != 3:
        errors.append(f"expected 3 separators of exactly {WIDTH} columns, "
                      f"found {len(seps)}")
    if not any(l.startswith("// Licence: MIT") for l in head):
        errors.append("no licence line")

    try:
        params_at = head.index("// PARAMETERS")
    except ValueError:
        return errors + ["no PARAMETERS block"]
    if seps and params_at < seps[0]:
        errors.append("PARAMETERS block comes before the licence")

    documented = [(m.group(1), _parse_range(m.group(2)))
                  for m in (ENTRY.match(l) for l in head[params_at:]) if m]

    declared = []
    for i, line in enumerate(rest, body + 1):
        m = c.PRAGMA.match(line)
        if m:
            declared.append((m.group(1), float(m.group(4)), float(m.group(5)),
                             float(m.group(3))))
        elif line.startswith("#pragma parameter"):
            errors.append(f"line {i}: unparseable #pragma parameter")
        if line.startswith("#pragma") and len(line) > WIDTH:
            errors.append(f"line {i}: #pragma is {len(line)} columns")

    doc_names = [n for n, _ in documented]
    dec_names = [d[0] for d in declared]
    if doc_names != dec_names:
        errors.append(f"PARAMETERS lists {doc_names or '[]'} but the #pragma "
                      f"lines declare {dec_names or '[]'}")
    else:
        for (n, (lo, hi)), (_, pmin, pmax, default) in zip(documented, declared):
            if (lo, hi) != (pmin, pmax):
                errors.append(f"{n}: documented {lo:g} to {hi:g}, "
                              f"declared {pmin:g} to {pmax:g}")
            if not pmin <= default <= pmax:
                errors.append(f"{n}: default {default:g} outside "
                              f"{pmin:g} to {pmax:g}")

    # "0 disables it" has to name a value the slider can actually reach. It said
    # 0 for a gain whose range starts at 0.25, which is not a setting anyone can
    # choose. The neutral value and the shipped default are different things -
    # a visibility control is off at 0 and ships at 0.30 - so only the range can
    # be checked mechanically.
    for line in head[params_at:]:
        m = ENTRY.match(line)
        n_off = re.search(r'(-?[\d.]+)\s+(?:disables it|is off)', line)
        if m and n_off:
            lo, hi = _parse_range(m.group(2))
            v = float(n_off.group(1))
            if not lo <= v <= hi:
                errors.append(f"{m.group(1)}: says {v:g} disables it, outside "
                              f"{lo:g} to {hi:g}")

    # The description says what the shader draws and what it looks like. It is
    # read by someone deciding whether they want it, not by someone maintaining
    # it, and it grew to 22 lines once. Mechanism belongs in docs/<family>.md.
    end = next((i for i, l in enumerate(head[params_at:], params_at)
                if l == SEP), None)
    if end is not None:
        desc = head[end + 1:]
        stop = next((i for i, l in enumerate(desc) if l.startswith("// Notes:")),
                    len(desc))
        n_lines = len([l for l in desc[:stop] if l.strip() != "//"])
        if n_lines > DESC_MAX:
            errors.append(f"description is {n_lines} lines, over {DESC_MAX} - "
                          f"move the mechanism to docs/")
    return errors


def fallbacks(name):
    """Parameters whose #define fallback disagrees with their #pragma default.

    Every shader declares each parameter twice: as a uniform when the host
    defines PARAMETER_UNIFORM, and as a literal #define when it does not. A host
    that does not parse #pragma parameter renders the #define values, so a
    mismatch means the shader ships one look and documents another. Nothing that
    renders here can see it - every render tool passes parameters explicitly and
    compiles with PARAMETER_UNIFORM defined - which is why it needs its own
    check.
    """
    prag, defs = {}, {}
    for line in c.read(name).split("\n"):
        m = c.PRAGMA.match(line)
        if m:
            prag[m.group(1)] = float(m.group(3))
        d = DEFINE.match(line)
        if d:
            defs[d.group(1)] = float(d.group(2))
    out = [(k, prag[k], defs[k]) for k in prag
           if k in defs and abs(prag[k] - defs[k]) > 1e-9]
    # A parameter with no fallback at all is worse than one that disagrees: on
    # a host that does not parse pragmas it is simply undefined. Comparing only
    # the overlap could never see that, so the two sets have to match.
    out += [(k, prag[k], None) for k in prag if k not in defs]
    return out


def run(names, report, also_compile=None):
    """Header format applies to `names`; compilation applies to everything.

    The format postdates the archive, so holding a superseded version to it
    would report a defect nobody is going to fix. Compiling it is different:
    a version that stops building has silently stopped being a control.
    """
    for name in (also_compile or names):
        errors = compiles(name)
        report.check(not errors, f"{name} compiles",
                     "" if not errors else errors[0])

    for name in names:
        errors = header(name) + [
            f"{k}: no #define fallback" if d is None else
            f"{k}: #pragma {p:g} but #define fallback {d:g}"
            for k, p, d in fallbacks(name)]
        n = len(c.parameters(name))
        report.check(not errors, f"{name} header",
                     f"{n} parameters" if not errors else "; ".join(errors))

    errors = c.check_baseline()
    report.check(not errors, "baseline.toml matches the tree",
                 "" if not errors else "; ".join(errors))

    errors = c.check_pipelines()
    report.check(not errors, "device pipelines resolve",
                 f"{len(c.PIPELINES)} pipelines" if not errors
                 else "; ".join(errors))
    return report


if __name__ == "__main__":
    r = c.Report("check")
    run(c.resolve(sys.argv[1:]), r)
    sys.exit(r.done())
