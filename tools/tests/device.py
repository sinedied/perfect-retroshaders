"""The device benchmark renders the same picture as the harness with goldens.

tools/device is a second, independent implementation of the frontend's shader
path, written in C so it can run on the handheld. Two implementations of the
same thing drift, and a timing harness cannot notice: it will happily report
what it costs to render the wrong image quickly. crt-perfect-v7 passed every
number in this repo while having cropped its entire border off-screen.

So the C pipeline is diffed against the Python one, which is the one carrying
the golden hashes. The demand is byte equality, not a tolerance: both compute
the same arithmetic on the same GPU from the same source, so anything above 0
needs a mechanism rather than a shrug.

Skipped, not failed, where the desktop build cannot be made - the gate must
still run on a machine with no compiler or no SDL2.
"""

import os
import shutil
import subprocess
import tempfile

import numpy as np

import common as c

DEVICE = os.path.join(c.TOOLS, "device")
BINARY = os.path.join(DEVICE, "build", "bench")

# The same LCG the benchmark fills its source with. Reproduced rather than
# shared, because a shared generator that drifted would move both sides
# together and the comparison would keep passing while measuring nothing.
def source(w, h):
    px = np.zeros((h, w, 3), np.uint8)
    state = 12345
    for i in range(w * h):
        for ch in range(3):
            state = (state * 1103515245 + 12345) & 0xFFFFFFFF
            px[i // w, i % w, ch] = (state >> 16) & 0xFF
    return px


def read_ppm(path):
    with open(path, "rb") as f:
        assert f.readline().strip() == b"P6"
        w, h = (int(v) for v in f.readline().split())
        assert f.readline().strip() == b"255"
        return np.frombuffer(f.read(w * h * 3), np.uint8).reshape(h, w, 3)


def dump_name(label):
    """The filename the benchmark writes for a pipeline label."""
    return "".join("_" if ch in " >" else ch for ch in label) + ".ppm"


def build():
    if not shutil.which("make") or not shutil.which("cc"):
        return "no compiler"
    r = subprocess.run(["make", "-s"], cwd=DEVICE, capture_output=True,
                       text=True)
    if r.returncode != 0:
        return (r.stderr or r.stdout).strip().split("\n")[-1]
    return None


def run(names, ctx, progs, report, cases=None):
    why = build()
    if why:
        report.note(f"device benchmark not built ({why}); render not compared")
        return report

    src_w, src_h = c.DEVICE["source"]
    out_w, out_h = c.DEVICE["output"]

    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([BINARY, "--dump", tmp], capture_output=True,
                           text=True)
        if r.returncode != 0:
            report.fail("device benchmark renders",
                        (r.stderr or r.stdout).strip().split("\n")[-1])
            return report

        pixels = source(src_w, src_h)
        for entry in c.PIPELINES:
            cfg = c.parse_cfg(c.pipeline_cfg(entry))
            path = os.path.join(tmp, dump_name(entry["label"]))
            if not os.path.exists(path):
                report.fail(f"{entry['label']} dumped", "no image written")
                continue
            got = read_ppm(path)

            if len(cfg["passes"]) != 1:
                # A later pass is handed the ORIGINAL source size in TextureSize
                # and InputSize, not the size of the texture it samples. That
                # quirk has no equivalent in the Python renderer, so a chain is
                # only checked for having drawn something.
                report.check(got.std() > 1.0, f"{entry['label']} renders",
                             f"{len(cfg['passes'])} passes, "
                             f"sd {got.std():.1f}")
                continue

            name = cfg["passes"][0]["shader"]
            want = c.render(ctx, progs, name, pixels, out_w, out_h,
                            **cfg["params"])
            delta = int(np.abs(got.astype(int) - want.astype(int)).max())
            report.check(delta == 0, f"{entry['label']} matches the harness",
                         f"{name}, max delta {delta}")
    return report
