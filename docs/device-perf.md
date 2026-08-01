# Measuring on the device

Every performance figure this repository has published was measured in a browser
on a desktop GPU. `tools/perf.py` says so in its own docstring — *"Not the target
GPU: read the ratios"* — and it cannot measure a multi-pass pipeline at all,
which half the published comparisons were. This is the record of building
something that runs on the handheld instead.

`tools/device` is a small C program, cross-built for `tg5040`, that loads the
same shaders through the same preprocessing the frontend uses, renders the same
pipelines, and times them.

## The hardware is not what this repo thought it was

`AGENTS.md` described the target as a **Mali G31 MP2**. It is not. The Trimui
Brick (platform `tg5040`, vendor codename TG3040) is an **Allwinner A133 Plus
with an Imagination PowerVR Rogue GE8300**.

The most direct evidence is in NextUI itself. `workspace/all/common/generic_video.c`
disables the swap-interval call entirely, and the comment explaining why names
the part:

```c
void PLAT_setVsync(int vsync) {
	// No effect on Ge8300
```

Corroborated by 68 driver dumps in the `opengles.gpuinfo.org` database reporting
`GL_RENDERER: PowerVR Rogue GE8300` at GLES 3.2 and 1024x768@60; by
`ArjunKdaf/kUI` and `josegonzalez/minui-n64-pak`, both of which branch on the
distinction between `tg5040` (PowerVR) and `tg5050` (Mali G57); and by the
retail specification.

This is not pedantry. Mali and PowerVR differ on the two things the measurement
depends on — whether GPU timer queries exist, and how overdraw is removed — and
they differ in opposite directions.

## Four things that do not work

**GPU timer queries.** `GL_EXT_disjoint_timer_query` appears in **0 of 631**
driver reports for `GL_VENDOR: Imagination Technologies`, and 0 of 68 for the
GE8300 specifically. Mali exposes it; this part does not. There is nothing to
ask the GPU how long it took, so everything here is wall clock around
`glFinish`, which the vendor documents as a full pipeline drain — the cost that
makes it useless in an application and correct in a benchmark.

**Timing a single draw.** Both tile-based architectures schedule per render
target: the whole geometry phase, then the whole fragment phase. A draw has no
boundary of its own to time. Batches only.

**Repeating a draw to build up measurable work.** This is the trap that would
have produced a confident, wrong table. Imagination's architecture guide:

> The efficiency of PowerVR Hidden Surface Removal is high enough to allow
> overdraw to be removed entirely for completely opaque renders.

and, elsewhere, that it does so *"regardless of draw call submission order"*. So
N identical opaque full-screen quads cost about one, and the shader reads as
free. Blending is the documented escape: blended fragments cannot be removed,
which is why the vendor's own worked example cannot reach one fragment per
pixel. Arm's Forward Pixel Kill has the same behaviour and the same escape, so
this is not a PowerVR-only precaution.

**Measuring by frame rate.** `PLAT_setVsync()` is a no-op on this platform, so
nothing can turn vsync off. The benchmark renders to an offscreen framebuffer
and never presents.

## What is measured, and how

Two numbers per pipeline, because they answer different questions.

**`ms` — one whole frame.** Every shader pass plus the final blit, which is
what the device actually pays per frame and therefore the only figure that can
be compared against a 16.67 ms budget.

**`frag_ms` — the fragment shaders alone.** N quads inside *one* render pass,
blended so nothing is removed, summed over the chain. This carries none of the
per-pass tile store or driver cost.

The second exists because of what the first does on a fast GPU. On an M4 Max,
every single-pass pipeline in the table lands within noise of every other —
not because the shaders cost the same, but because the render pass around them
costs an order of magnitude more than any of them. A table of frame times alone
would have said "these are all identical" and meant nothing by it.

Both are **slopes**, not times: each is measured at two batch sizes and the
difference divided by the difference in size. That subtracts the barrier, the
first-render run-up and every other fixed cost, so no absolute measurement has
to be trusted — only the difference between two of them.

Batch sizes are **calibrated per pipeline** from its own measured cost, aiming
at about 20 ms of work. Fixed batch counts do not survive the range of hardware
involved: the same 16 renders is a substantial workload on the handheld and
under a millisecond on a laptop, where it measured the `glFinish` round trip and
reported a linearity of r² 0.68 for a perfectly linear quantity.

## What went wrong while building it, and what fixed it

Every one of these produced a plausible number first.

**Series measured in ascending order bend.** The linearity check read r² 0.95
because the smallest batch is always measured first, while the GPU is still
coming up to clock, and the largest last. Measuring the sizes in **rotated
rounds** — a different one first each round, median per size — took the same
quantity to r² 0.9991. The curve was never non-linear; the order was.

**Two runs measured back to back do not measure repeatability.** Run in
sequence, the whole of any clock drift lands on the second one: the check
reported -21%. Interleaving the two runs, and taking the median of thirteen
rather than nine, took it to 0%. This is the same lesson `tools/perf.py` already
records about interleaving cases, arrived at again by ignoring it.

**A fixed overdraw count measures the barrier.** The HSR check first used 1 to
16 quads, which on a fast GPU is far less work than the fixed cost around it, so
both the blended and opaque curves read as flat and the check "passed" by
concluding everything was free. Scaling the counts with the calibrated batch
size fixed it.

## Verification

`bench --self-test` checks the instrument, not the shaders, and the pak refuses
to measure if any hard check fails.

| check | what it would catch |
|---|---|
| blended overdraw is not free | the whole method silently measuring nothing |
| opaque overdraw *(reported, not asserted)* | whether HSR removes repeats on this GPU |
| batch time is linear in batch size | the driver dropping whole repeats |
| final blit is not elided | the last pass being optimised away between repeats |
| two interleaved runs agree *(warning)* | thermal or clock drift big enough to invalidate the run |
| the one-tap shader is the cheaper | the harness being wired to the wrong thing |

Drift is a warning rather than a failure on purpose. It is a fact about the
machine, not a defect in the instrument, and refusing to produce numbers because
a laptop got busy would be the wrong response — the table's per-case IQR column
reports the same instability measured across the whole run instead of across one
pair. Everything else is a hard failure, because each one means the number would
be measuring something other than the shader.

Separately, and more strongly: `tools/tests/device.py` renders every pipeline
through the C program and diffs it against the Python harness that carries this
repo's golden hashes. The demand is **byte equality**, and it is met — max delta
0 on all six single-pass pipelines, including `sharp-shimmerless` through its
LINEAR sampler. Two independent implementations of the frontend's shader path
agreeing to the byte is what makes the timings worth reading; a timing harness
will otherwise happily report the cost of rendering the wrong image.

That test is in `tools/test.py`, and it skips rather than fails where there is
no compiler or no SDL2.

## What is still not covered

- **GPU clock.** DVFS is not exposed on this platform: `/sys/class/devfreq` is
  empty and the GPU sits at a fixed operating point with dynamic scaling off.
  That is good for reproducibility and impossible to verify from userspace, so
  the benchmark logs CPU clock and both thermal zones instead and reports the
  drift across a run.
- **The emulator underneath.** These figures are the shader's cost with nothing
  else running. A real frame also has a core in it.
- **A multi-pass chain against the Python harness.** A later pass is handed the
  *original* source size in `TextureSize` and `InputSize` rather than the size of
  the texture it samples. That frontend quirk has no equivalent in the Python
  renderer, so the two-pass pipeline is only checked for having drawn something.

## Running it

```sh
cd tools/device
make            # desktop smoke build - compiles and runs, not a source of numbers
make selftest   # the five checks, on this machine
make device     # cross-compile for the Brick (needs Docker running)
make pak        # ShaderBench.pak, laid out as it sits on the card
```

Copy `build/ShaderBench.pak` to `Tools/tg5040/` on the SD card and launch it
from the device's Tools menu — which matters, because the launcher holds the
display until then. It writes `results.tsv` next to itself.

```sh
python tools/report.py results.tsv --write   # into README.md, between its markers
```
