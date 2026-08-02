#!/usr/bin/env python3
"""The gate. Run this before committing a change to a shader.

    python tools/test.py                  everything shipping
    python tools/test.py crt-perfect      one family
    python tools/test.py --all            golden the archive too
    python tools/test.py --record         re-record the golden hashes

Two tiers, because they answer different questions.

  gated      the released and current versions, held to today's standards:
             header format, moire limits, contracts, the family properties
  tracked    every shader including the archive, compiled so it cannot rot,
             and hashed so a frozen file stays frozen

Holding the archive to the gates would be meaningless. crt-perfect-v1 beats at
17.9 against a limit of 0.4 - that is WHY it was superseded, and it is never
going to be fixed. It still has to compile, and it still has to render exactly
what it rendered yesterday, because the family tests use those versions as
negative controls.

It runs, in order:

  check       compiles, and the header still describes the shader
  device      the C benchmark in tools/device renders the same picture
  contracts   parameter endpoints, no extinguished pixels, and the scaler anchor
  properties  the per-family claims in tools/tests/, each with its control
  measure     moire against the limits in baseline.toml
  goldens     a hash per shader per case, so nothing changes by accident

Perf is NOT here. GPU timing moves a few percent with laptop thermals, so it
would fail for reasons that have nothing to do with the shader. Run tools/perf.py
when you want to compare.

A golden mismatch is not a failure by itself - it is the tool saying the picture
changed and asking whether you meant it. Look at tools/preview.py, then --record.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import check
import measure

# Per-family property modules. A family with nothing worth asserting simply has
# no entry; the point is that each check here has a control that fails it.
FAMILY_TESTS = {
    "crt-perfect": "tests.crt_perfect",
    "lcd-perfect": "tests.lcd_perfect",
    "pixel-perfect": "tests.pixel_perfect",
    "dmg-perfect": "tests.dmg_perfect",
    # The *-turbo line draws the same pictures, so it answers to the same
    # claims. The modules take the family rather than naming a shader, and the
    # negative controls stay the *-perfect archives - a control only has to be
    # something the check can tell apart.
    "crt-turbo": "tests.crt_perfect",
    "lcd-turbo": "tests.lcd_perfect",
    "pixel-turbo": "tests.pixel_perfect",
    "dmg-turbo": "tests.dmg_perfect",
    # ... and the mini line, which draws the same patterns without the scaler.
    "crt-mini": "tests.crt_perfect",
    "lcd-mini": "tests.lcd_perfect",
    "colour-mini": "tests.pixel_perfect",
    "dmg-mini": "tests.dmg_perfect",
}


def goldens(names, ctx, progs, report, cases, record=False):
    """A hash of each shader's render at its shipped defaults, per case.

    This is what replaced the numpy twins. It proves nothing about correctness -
    only that nothing moved since somebody last looked. That is the regression
    half of what the twins were doing; the correctness half is the scaler anchor
    in tests/contracts.py.
    """
    table = {k: dict(v) for k, v in c.GOLDEN.items()}
    changed = []
    for name in names:
        for case in cases:
            sw, sh, ow, oh = case
            img = c.render(ctx, progs, name, c.scene(sw, sh), ow, oh)
            key, got = c.golden_key(case), c.golden_hash(img)
            want = c.GOLDEN.get(name, {}).get(key)
            if want is None or got != want:
                changed.append(f"{name} {key}")
            table.setdefault(name, {})[key] = got
    if record:
        c.write_goldens(table)
        report.note(f"recorded {sum(len(v) for v in table.values())} goldens")
        return report
    report.check(not changed, "goldens unchanged",
                 f"{len(changed)} moved: " + ", ".join(changed[:4])
                 + (" ..." if len(changed) > 4 else ""))
    return report


def main():
    argv = sys.argv[1:]
    flags = {a for a in argv if a.startswith("-")}
    args = [a for a in argv if not a.startswith("-")]

    gated = c.resolve(args)
    # Every archive version of a family under test, so it keeps compiling and
    # keeps rendering what the negative controls expect.
    fams = {c.family(n) for n in gated}
    tracked = gated + [n for n in c.by_role(c.ARCHIVE)
                       if c.family(n) in fams and n not in gated]

    report = c.Report("test")

    print("\ncheck")
    check.run(gated, report, also_compile=tracked)

    ctx = c.context()
    progs = c.Programs(ctx)
    cases = c.CASES

    # Every phase below shares this context. A phase that quietly makes its own
    # leaves this one unbound, and renders then keep succeeding while returning
    # a different picture - which is how a whole set of golden hashes was once
    # recorded from renders nobody could reproduce.
    #
    # So the reference is taken HERE, while the context is known good, and
    # re-checked after each phase. Taking it later cannot work: if an earlier
    # phase has already swapped the context, the before and after renders are
    # both corrupted and agree with each other. That is the flaw in the first
    # version of this guard, which sat inside goldens() and so only ever
    # watched the one phase that creates no contexts.
    psw, psh, pow_, poh = cases[0]
    _probe = lambda: c.golden_hash(
        c.render(ctx, progs, gated[0], c.scene(psw, psh), pow_, poh))
    reference = _probe()

    def phase(label, fn):
        print(f"\n{label}")
        fn()
        if _probe() != reference:
            report.fail(f"{label} left the GL context intact",
                        "the same render changed across this phase - it took "
                        "its own context, so everything after it is suspect")

    phase("self-test", lambda: measure.self_test(report))
    phase("device", lambda: importlib.import_module("tests.device").run(
        gated, ctx, progs, report, cases))
    phase("contracts",
          lambda: importlib.import_module("tests.contracts").run(
              gated, ctx, progs, report, cases))

    for fam in c.families():
        mod = FAMILY_TESTS.get(fam)
        if not mod or fam not in fams:
            continue
        phase(fam, lambda mod=mod, fam=fam: importlib.import_module(mod).run(
            gated, ctx, progs, report, cases, fam))

    phase("measure", lambda: measure.run(gated, report, ctx, progs, cases))

    print("\ngoldens")
    record = "--record" in flags
    goldens(tracked if ("--all" in flags or record) else gated,
            ctx, progs, report, cases, record=record)

    return report.done()


if __name__ == "__main__":
    sys.exit(main())
