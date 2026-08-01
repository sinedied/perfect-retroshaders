#!/usr/bin/env python3
"""The device benchmark's TSV as the table the README carries.

Mechanical on purpose. The eight comparison tables the README used to carry were
transcribed by hand from a browser, which is why nobody could say afterwards
what they had been measured on. Re-running the benchmark and re-running this
regenerates the table; nothing in between is a judgement call.

    python tools/report.py results.tsv          print the table
    python tools/report.py results.tsv --write  replace it in README.md

The markers in README.md are what --write edits between. Text outside them is
never touched.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

BEGIN = "<!-- device-perf:begin -->"
END = "<!-- device-perf:end -->"

README = os.path.join(c.REPO, "README.md")


def read_tsv(path):
    meta, rows = {}, []
    header = None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#"):
                bits = line[1:].strip().split("\t", 1)
                if len(bits) == 2:
                    meta[bits[0].strip()] = bits[1].strip()
                continue
            if not line.strip():
                continue
            fields = line.split("\t")
            if header is None:
                header = fields
                continue
            rows.append(dict(zip(header, fields)))
    return meta, rows


def table(meta, rows):
    """Relative %, absolute ms and the share of a 60fps frame, in that order.

    The percentage is against the first row, which baseline.toml makes
    pixellate: it ships on the target and holds 60fps, so a row above 100%
    costs less than something already known to fit.
    """
    out = []
    renderer = meta.get("renderer", "unknown GPU")
    out.append(f"| Pipeline | Perf. | GPU ms | Frame budget |")
    out.append(f"| --- | ---: | ---: | ---: |")
    for r in rows:
        passes = int(r["passes"])
        label = f"{passes} pass{'es' if passes != 1 else ''} · {r['pipeline']}"
        out.append(f"| {label} | {float(r['relative_pct']):.0f}% "
                   f"| {float(r['ms']):.2f} ms "
                   f"| {float(r['budget_pct']):.0f}% |")
    out.append("")
    out.append(f"_{renderer}, 320×240 into 1024×768. Frame budget is the share "
               f"of one 60fps frame (16.67 ms) the pipeline uses._")
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 2
    meta, rows = read_tsv(args[0])
    if not rows:
        print(f"{args[0]}: no rows", file=sys.stderr)
        return 1
    body = table(meta, rows)

    if "--write" not in sys.argv:
        print(body)
        return 0

    with open(README) as f:
        text = f.read()
    if BEGIN not in text or END not in text:
        print(f"README.md has no {BEGIN} / {END} markers", file=sys.stderr)
        return 1
    head, rest = text.split(BEGIN, 1)
    _old, tail = rest.split(END, 1)
    with open(README, "w") as f:
        f.write(f"{head}{BEGIN}\n\n{body}\n\n{END}{tail}")
    print(f"wrote {len(rows)} rows into README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
