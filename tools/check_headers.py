#!/usr/bin/env python3
"""Check the shipped shaders against the header format AGENTS.md defines.

The format is a user-facing contract - the PARAMETERS block is what someone
reads before touching a slider - and until this existed nothing verified that
it still described the shader underneath it. A range edited in the #pragma and
forgotten in the block is silent, and so is a parameter added to one and not the
other.

Checks, per shipped shader:

  - line comments only, no block comment
  - no line over 80 columns, in the header or in the #pragma lines
  - the sections present and in order: title, licence, PARAMETERS, description
  - the PARAMETERS block and the #pragma lines list the same identifiers, in the
    same order, with the same ranges, and every default inside its own range

And one thing it warns about rather than failing on: a parameter whose #define
fallback disagrees with its #pragma default. See fallbacks() for why.

Run:  cd tools && PYTHONPATH=. python3 check_headers.py
Exits non-zero on the first shader that fails, so it can gate a commit.
"""

import os
import re
import sys

from core.paths import list_shaders, shader_path
from models.registry import REGISTRY

WIDTH = 80
SEP = "// " + "-" * (WIDTH - 3)

PRAGMA = re.compile(r'^#pragma parameter\s+(\w+)\s+"([^"]*)"\s+'
                    r'(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)')
# "  name  0.00 - 1.00  Description." or "  name  0 / 1  Description."
ENTRY = re.compile(r'^//   (\w+)\s\s+(-?[\d.]+(?:\s*[-/]\s*-?[\d.]+)+)\s\s+\S')


def parse_range(text):
    """Both spellings collapse to (min, max): a dash range, or slash-separated
    discrete values, which is how enum-like parameters are written."""
    nums = [float(n) for n in re.findall(r'-?[\d.]+', text)]
    return min(nums), max(nums)


def check(name):
    lines = open(shader_path(name)).read().split("\n")
    errors = []

    body = next((i for i, l in enumerate(lines) if not l.startswith("//")),
                len(lines))
    header, rest = lines[:body], lines[body:]

    if not header:
        return [f"{name}: header is not a // comment block"]

    for i, line in enumerate(header, 1):
        if len(line) > WIDTH:
            errors.append(f"line {i}: {len(line)} columns, over {WIDTH}")
    if any("/*" in l for l in header):
        errors.append("header uses a block comment; the format is line comments")

    if not re.match(r'^// [\w-]+ - \S.*\.$', header[0]):
        errors.append('first line should be "// <name> - <description ending in '
                      'a period.>"')

    seps = [i for i, l in enumerate(header) if l == SEP]
    if len(seps) != 3:
        errors.append(f"expected 3 separators of exactly {WIDTH} columns, "
                      f"found {len(seps)}")
    if not any(l.startswith("// Licence: MIT") for l in header):
        errors.append("no licence line")
    try:
        params_at = header.index("// PARAMETERS")
    except ValueError:
        return errors + [f"{name}: no PARAMETERS block"]
    if seps and params_at < seps[0]:
        errors.append("PARAMETERS block comes before the licence")

    documented = []
    for line in header[params_at:]:
        m = ENTRY.match(line)
        if m:
            documented.append((m.group(1), parse_range(m.group(2))))

    declared = []
    for i, line in enumerate(rest, body + 1):
        m = PRAGMA.match(line)
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

    # The numpy twin has to ship the same defaults as the shader. gl_check feeds
    # both sides the same parameters so it stays green either way, but beat.py
    # and preview.py both render `model.defaults` - so a drift here silently
    # reports and screenshots a configuration nobody actually ships. It has
    # happened once already, from a one-line tweak to a #pragma.
    model = REGISTRY.get(name if not os.path.isabs(name) else os.path.basename(name))
    if model is not None:
        for n, _, _, default in declared:
            if n in model.defaults and abs(model.defaults[n] - default) > 1e-9:
                errors.append(f"{n}: shader default {default:g} but the model in "
                              f"shaders.py uses {model.defaults[n]:g}")

    return [f"{name}: {e}" for e in errors]


def fallbacks(name):
    """Mismatches between a parameter's #pragma default and its #define fallback.

    Every shader declares each parameter twice - as a uniform when the host
    defines PARAMETER_UNIFORM, and as a literal #define when it does not. A host
    that does not parse #pragma parameter renders the #define values, so the two
    disagreeing means the shader ships one look and documents another.

    Reported rather than failed, because two shaders disagree today and neither
    is this check's business to change. Promote it into check() once they are
    fixed; a warning nobody promotes is a warning that rots.

    A default lives in three places - the #pragma line, this fallback, and the
    model's DEFAULTS_* dict - and nothing else ties them together. gl_check
    cannot see a stale fallback: it passes the registry's defaults explicitly
    and compiles with PARAMETER_UNIFORM defined, so it never reads one.
    lcd-perfect shipped with its pre-retune values here for exactly that reason.

    spirv_cost.py's 'at defaults' column also reads these fallbacks, so a
    mismatch quietly makes that column describe a configuration nobody runs.
    """
    lines = open(shader_path(name)).read().split("\n")
    prag, defs = {}, {}
    for line in lines:
        m = PRAGMA.match(line)
        if m:
            prag[m.group(1)] = float(m.group(3))
        d = re.match(r'^#define\s+(\w+)\s+(-?[\d.]+)\s*$', line)
        if d:
            defs[d.group(1)] = float(d.group(2))
    return [(k, prag[k], defs[k]) for k in prag
            if k in defs and abs(prag[k] - defs[k]) > 1e-9]


if __name__ == "__main__":
    names = sys.argv[1:] or list_shaders()
    failed = []
    mismatched = []
    for name in names:
        errors = check(name)
        n = sum(1 for l in open(shader_path(name))
                if l.startswith("#pragma parameter"))
        if errors:
            failed.append(name)
            print(f"{name:<22s} FAIL")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"{name:<22s} ok   ({n} parameters, header agrees)")
        fb = fallbacks(name)
        if fb:
            mismatched.append(name)
            for k, p, d in fb:
                print(f"  warning: {k} defaults to {p:g} but its #define "
                      f"fallback is {d:g}")

    print(f"\n{len(names) - len(failed)}/{len(names)} passed")
    if mismatched:
        print(f"\n{len(mismatched)} shader(s) have #define fallbacks that "
              f"disagree with their\n#pragma defaults: "
              f"{', '.join(mismatched)}."
              f"\nA host that does not parse #pragma parameter renders those "
              f"values, so\nthose shaders ship a different look from the one "
              f"they document. Not\ncounted as a failure yet; fix them and move "
              f"this into check().")
    sys.exit(1 if failed else 0)
