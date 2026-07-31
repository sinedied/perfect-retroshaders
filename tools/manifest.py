#!/usr/bin/env python3
"""Which shaders exist, what each one is *for*, and how it must be sampled.

Every tool here needs to answer "what is the current version of this family?" and
"which shaders should a default run cover?". Until this file existed each tool
answered separately, by pattern-matching filenames, and they disagreed:

  - beat.py gated `max(names)`. That returns dmg-perfect-v8 today and keeps
    returning it after v10 lands, because "v8" sorts above "v10". The gate would
    have gone on passing while testing a version two releases old.
  - twopass.py defaulted to dmg-perfect-v2 long after v8 became current.
  - preview.py turned curvature on for v6, v7 and v8, so v9 and v10 were
    previewed flat and showed nothing.

None of those failed. They quietly measured the wrong shader, which is the
failure mode this whole repo is built to avoid. So the lifecycle is declared,
once, as data:

  released   what the README ships and a user installs
  current    the newest version of a family, and what a default run gates on
  archive    superseded, kept because its numbers are the record of why
  vendor     third-party, for comparison only, not ours and not edited

A shader can hold two roles: where a family has no newer candidate, its released
version is also its current one.

Role is deliberately independent of directory. Superseded versions live in both
`shaders/` and `tools/iterations/` for historical reasons, and moving them would
break paths that presets point at. What a file *is* should not depend on where it
happens to sit.
"""

from paths import shader_path

RELEASED = "released"
CURRENT = "current"
ARCHIVE = "archive"
VENDOR = "vendor"

# Sampler the shader is designed to be run through. Almost everything here takes
# four NEAREST taps and computes its own area average; the one-tap references
# delegate that to the texture unit and are wrong through NEAREST. This was
# already costing a wrong row in a comparison table before it was written down.
NEAREST = "nearest"
LINEAR = "linear"

# name -> (family, roles, sampler)
_M = {}


def _add(name, family, roles, sampler=NEAREST):
    _M[name] = (family, frozenset(roles), sampler)


_add("crt-perfect.glsl", "crt-perfect", [RELEASED])
_add("crt-perfect-v10.glsl", "crt-perfect", [CURRENT])
for _v in (1, 2, 3, 4, 5, 6, 7, 8, 9):
    _add(f"crt-perfect-v{_v}.glsl", "crt-perfect", [ARCHIVE])

_add("lcd-perfect.glsl", "lcd-perfect", [RELEASED, CURRENT])
for _v in ("1", "2a", "2b"):
    _add(f"lcd-perfect-v{_v}.glsl", "lcd-perfect", [ARCHIVE])

_add("pixel-perfect.glsl", "pixel-perfect", [RELEASED])
_add("pixel-perfect-v6.glsl", "pixel-perfect", [CURRENT])
for _v in (2, 3, 4, 5):
    _add(f"pixel-perfect-v{_v}.glsl", "pixel-perfect", [ARCHIVE])

# The DMG family has no un-suffixed file; v8 is what the README links, so it is
# both what ships and what a default run gates on.
_add("dmg-perfect-v8.glsl", "dmg-perfect", [RELEASED, CURRENT])
for _v in (1, 2, 3, 4, 5, 6, 7):
    _add(f"dmg-perfect-v{_v}.glsl", "dmg-perfect", [ARCHIVE])

_add("pixellate.glsl", "vendor", [VENDOR])
_add("lcd1x.glsl", "vendor", [VENDOR])
_add("lcd3x.glsl", "vendor", [VENDOR])
_add("dmg_dot_matrix.glsl", "vendor", [VENDOR])
_add("sharp-shimmerless.glsl", "vendor", [VENDOR], LINEAR)
_add("sharp-shimmerless-grid.glsl", "vendor", [VENDOR], LINEAR)


def known(name):
    return name in _M


def family(name):
    return _M[name][0]


def roles(name):
    return _M[name][1]


def sampler(name):
    """nearest or linear. Read this rather than assuming; see NEAREST above."""
    return _M[name][2] if name in _M else NEAREST


def by_role(*want):
    """Every shader holding any of the given roles, in declaration order."""
    want = set(want)
    return [n for n, (_, r, _s) in _M.items() if r & want]


def families():
    seen = []
    for _n, (f, _r, _s) in _M.items():
        if f != "vendor" and f not in seen:
            seen.append(f)
    return seen


def current(fam):
    """The version of a family a default run gates on.

    Never derive this by sorting names: "v8" sorts above "v10", so the newest
    version silently stops being tested the moment a family reaches double
    digits.
    """
    for name, (f, r, _s) in _M.items():
        if f == fam and CURRENT in r:
            return name
    raise KeyError(f"no current version declared for {fam}")


def released(fam):
    for name, (f, r, _s) in _M.items():
        if f == fam and RELEASED in r:
            return name
    raise KeyError(f"no released version declared for {fam}")


def default_scope():
    """What a fast run covers: everything a user could actually be running."""
    return by_role(RELEASED, CURRENT)


def check():
    """Every declared shader resolves, every file on disk is declared, and every
    family has both roles filled.

    The disk-to-manifest direction matters as much as the other one: a new
    version that nobody declares would simply not be tested, and silently
    dropping out of the matrix is exactly the failure this file exists to stop.
    """
    from paths import list_shaders

    errors = []
    for name in _M:
        try:
            shader_path(name)
        except FileNotFoundError:
            errors.append(f"{name}: declared but not on disk")
    for name in list_shaders(include_vendor=True, include_iterations=True):
        if name not in _M:
            errors.append(f"{name}: on disk but not declared in the manifest")
    for fam in families():
        for role, fn in ((CURRENT, current), (RELEASED, released)):
            try:
                fn(fam)
            except KeyError:
                errors.append(f"{fam}: no {role} version declared")
    return errors


if __name__ == "__main__":
    import sys

    bad = check()
    for fam in families():
        print(f"{fam:<16s} released {released(fam):<24s} current {current(fam)}")
    print(f"\n{len(_M)} shaders declared, "
          f"{len(default_scope())} in the default scope")
    for e in bad:
        print(f"  ERROR {e}")
    sys.exit(1 if bad else 0)
