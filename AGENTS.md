# AGENTS.md — perfect-retroshaders

GLSL retro shaders (CRT scanlines + RGB mask + pixel-perfect scaling) for cheap
handhelds. Target: **Trimui Brick, 1024x768, Mali G31 MP2, GLES 3.2, 60fps** — that is
47 Mfrag/s, and the shader also pays for a final 1:1 blit. Also expected to work down
to a 640x480 output. MIT.

No build, no test suite. Verification is the Python harness in `tools/`.

## Layout

| Path | What |
|---|---|
| `shaders/crt-perfect.glsl` | CRT: scanlines + RGB mask + pixel-perfect scaling. `cp_` params |
| `shaders/crt-perfect-v6.glsl` | in flight: curvature, patterns flat, black frame |
| `shaders/crt-perfect-v7.glsl` | in flight: curvature, zoomed to fill — **crops the border** |
| `shaders/crt-perfect-v8.glsl` | in flight: curvature, fills the screen and crops nothing |
| `shaders/crt-perfect-v9.glsl` | in flight: v8, but curvature costs nothing when off |
| `shaders/crt-perfect-v10.glsl` | in flight: v9, with the pattern still locked to the source |
| `shaders/lcd-perfect.glsl` | LCD: sinusoidal mesh on whole-cell periods, 120-degree stripes. `lp_` params |
| `shaders/pixel-perfect.glsl` | scaling only, no effect. `pp_` params |
| `shaders/pixel-perfect-v2.glsl` | in flight: adds a post-blend `pp_gamma` |
| `shaders/pixel-perfect-v3.glsl` | in flight: no `pp_sharpness`, adds a four-control grade |
| `shaders/pixel-perfect-v4.glsl` | in flight: v3, but the grade costs nothing when off |
| `shaders/dmg-perfect-v5.glsl` | Game Boy DMG: two-pass in one pass, soft shadow, colour trim. `dp_` params |
| `shaders/dmg-perfect-v4.glsl` | superseded: hard-edged shadow, offset exposed per axis |
| `shaders/dmg-perfect-v3.glsl` | superseded: shadow subtracted from the gap colour only |
| `shaders/dmg-perfect-v2.glsl` | superseded: same scaling, shadow measured opacity against white |
| `shaders/dmg-perfect-v1.glsl` | superseded: gap as a share of a cell, forced to 2px |
| `tools/` | the verification harness |
| `tools/vendor/` | **third-party shaders**, benchmark and comparison references only |
| `tools/iterations/` | superseded versions of our own shaders, kept for the record |

A `-vN` file in `shaders/` is an iteration still being compared against the canonical
one; it moves to `tools/iterations/` when it is superseded, or replaces the canonical
file when it wins. Both stay registered in `tools/shaders.py` either way.

`shaders/` holds only the shaders this repo ships. Anything third-party lives in
`tools/vendor/`: not part of the MIT grant, not edited, present purely to measure
against. `pixellate.glsl` (Fes) is the yardstick — **30 SFU slots**, ships on the
target device and holds 60fps there, so it is what every cost figure here is quoted
against. Note it is the yardstick on *two* axes that disagree: among the four-tap
shaders it has the most SFU and is also the fastest on desktop. See the benchmark
section, and `tools/vendor/README.md` for what else is in there and why.

**A vendored shader may need a sampler and parameters declaring**, and neither can be
inferred from the `.glsl`: `LINEAR_SAMPLED` in `tools/gl_check.py` for anything whose
preset asks for `filter_linear0 = true`, and `VENDOR_PARAMS` in `tools/preview.py`
only where a value should differ from the file's own `#pragma` default. Getting the
first wrong put a wrong number in a comparison table; see Measurement traps.

Tools resolve a bare shader filename against `shaders/`, then `tools/vendor/`, then
`tools/iterations/` via `tools/paths.py`, so a new benchmark shader only needs dropping
into `vendor/`. `list_shaders()` returns only `shaders/` unless asked for more, so the
archive does not pollute a compile report; `spirv_cost.py` asks for all three.

### The archive

`tools/iterations/crt-perfect-v{1..5}.glsl`. They stay **registered in
`tools/shaders.py` and verified on every `gl_check.py` run** — an archive that is not
executed rots, and their tolerances encode real findings.

- **v1–v4 predate the `cp_` prefix.** Their params are `Scanlines`, `Mask_Type` and so
  on. Setting `cp_*` on them silently does nothing.
- v1–v4 headers still document frontend-specific pass settings and their own version
  history. That is deliberate: they record how each step was reached.
- **v5 is not strictly superseded.** It applies `cp_gamma` to the four taps instead of
  to the scaled image, so it holds the moire fix at every gamma (0.13 flat) where the
  shipped shader does not (1.68 at gamma 1.4). It costs 32 SFU slots against 14. The
  shipped shader took the cheaper placement because the two are **bit-identical at the
  default `cp_gamma = 1.00`**, which is the only place the difference is free.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install glslang          # glslangValidator + spirv-dis, not a Python package
```

## Workflow

Run the tools from `tools/` with `PYTHONPATH=.` (they import each other):

```sh
.venv/bin/python tools/validate_glsl.py shaders/*.glsl        # 1. does it compile?
cd tools && PYTHONPATH=. ../.venv/bin/python spirv_cost.py    # 2. what does it cost?
cd tools && PYTHONPATH=. ../.venv/bin/python gl_check.py      # 3. does it do what you think?
cd tools && PYTHONPATH=. ../.venv/bin/python equivalence.py   # 4. pixel-perfect vs pixellate
cd tools && PYTHONPATH=. ../.venv/bin/python beat.py          # 5. does it paint moire?
cd tools && PYTHONPATH=. ../.venv/bin/python grid.py          # 6. is the grid even?
cd tools && PYTHONPATH=. ../.venv/bin/python twopass.py       # 7. does dmg match the 2-pass?
cd tools && PYTHONPATH=. ../.venv/bin/python check_headers.py # 8. does the header still match?
cd tools && PYTHONPATH=. ../.venv/bin/python preview.py       # 9. does it LOOK right?
```

**Step 9 is not optional for anything that changes geometry.** `crt-perfect-v7` passed
every one of steps 1–8 while having cropped the entire image border off-screen: 1/255
against an independent model, 0.039 beat, pitch invariant exactly 3.00, 0% black
pixels, and 10% of the picture silently gone. Numbers settle correctness and cost; they
do not settle framing, and these shaders exist to look right.
`preview.py --only border-grid` renders the pattern built for exactly this — a grid
with a differently coloured edge on each side, which is the only thing that shows what
happened to the edges. A screenshot, a plain grid and a checkerboard all show the
interior distortion and say nothing about the border.

**`preview.py --diff` is for the opposite question: whether two shaders agree.** A
side-by-side of two correct scalers is uninformative by construction — the eye sees one
picture N times and learns nothing, which is exactly what happened comparing
`sharp-shimmerless` against `pixellate`. `--diff` adds a row of differences against the
**first** shader named, amplified ×8 with the true max printed, so 1/255 rounding and a
67/255 disagreement cannot look alike. `--zoom N` magnifies (nearest, after `--crop`)
when the thing in question is a transition pixel. Reproduce that comparison with:

```sh
cd tools && PYTHONPATH=. ../.venv/bin/python preview.py \
  sharp-shimmerless.glsl pixellate.glsl pixel-perfect.glsl --crop 256 --diff
```

`gl_check.py` walks the registry in `tools/shaders.py`; add a shader there and it is
checked with no further wiring. A `Model` may raise its `tolerance` above 1 only with
a `reason` naming a mechanism that has been measured — the reason is printed next to
the result, so a tolerated divergence stays visible rather than silently accepted.

`grid.py` measures grid geometry rather than colour: spacing evenness, line width in
output pixels and as a share of a cell, and bit-identity against a reference shader at
whole scale factors. It self-tests twice on every run — once analytically, against
grids whose spacing is exact by construction, and once on the GPU against
`dmg_dot_matrix`, whose line is one output pixel wide by construction. Both halves are
needed: two earlier attempts at this measurement read a good grid as good and a bad
one as good too.

To iterate on a shader:

1. Edit the `.glsl`.
2. **Mirror the change in `tools/crt_preview.py` or `tools/lcd_preview.py`.** It is an independent numpy
   implementation of the same maths. `gl_check.py` runs the real shipped `.glsl` on a
   GPU and diffs it against that model; a mismatch means one of the two is wrong.
   Target is worst ≤ 1/255 (pure float32-vs-float64 rounding).
3. `spirv_cost.py` for cost. It is call-graph aware and counts scalar-expanded
   transcendentals (`pow` = log2+exp2 = 2 slots). **This is the cost metric to trust.**
4. `measure.py` for pattern geometry (period, contrast, mask swing) when matching a
   reference look.

`bench_glsl.py` gives repeatable GPU timings now — worst per-case IQR **1.4%**, where
it used to swing 25–50% and `pixellate` came out both fastest and slowest on different
runs. Five things were wrong and all five matter for any timing harness:

- **Uniforms not in the overrides were left at 0**, so "defaults" measured a shader
  with `cp_scanlines = cp_rgb_mask = 0` (both pattern branches skipped), `cp_gamma = 0`
  (forcing the `pow` branch that a default of 1.0 *skips*) and `cp_min_pitch = 0`
  (dividing by zero). Every number the tool ever produced was of a shader nobody runs.
  It now starts from `REGISTRY[fn].defaults` and applies overrides on top.
- **Cases were measured one at a time to completion**, so the GPU's clock drift landed
  entirely on whichever case was running. Interleave: one pass measures every case,
  and the set repeats.
- **The opening passes of a run are erratic** regardless of content, so the first
  `WARMUP_PASSES` are discarded outright. This is what took the spread from ~45% to
  ~1%; rotating the case order without discarding just spreads the damage around.
- **Min-to-max is the wrong spread statistic** — one hiccup in a multi-minute run makes
  everything look unmeasurable. Report the IQR.
- **The sampler was left at moderngl's default, which is LINEAR**, so every four-tap
  shader was timed with a bilinear fetch it never runs with. It happens not to have
  moved the ratios here — they reproduce to a tenth of a point under NEAREST — but that
  is luck, and a bilinear fetch is not free on every GPU. The filter now comes from
  `gl_check.LINEAR_SAMPLED`, i.e. from what each shader's own preset declares.

**The timings contradict the SFU budget, and that contradiction is unresolved.**
`pixellate` has **30 SFU against crt-perfect's 14** and is still the fastest of the
four-tap shaders; time tracks the op count instead:

| | ops | tex | SFU | vs `pixellate` |
|---|---|---|---|---|
| `sharp-shimmerless` (vendor, 1 tap) | **50** | **1** | **0** | **66%** |
| `pixel-perfect` | 112 | 4 | 0 | 75% |
| `sharp-shimmerless-grid` (vendor, 1 tap) | 161 | 1 | 0 | 83% |
| `pixellate` | 292 | 4 | **30** | 100% |
| `crt-perfect` (shipped) | 501 | 4 | 14 | 104% |
| `crt-perfect-v8`, curvature off | 628 | 4 | 14 | 123% |
| `crt-perfect-v8`, curvature on | 628 | 4 | 14 | 133% |

So on an Apple GPU, SFU is *not* the bottleneck. A Mali G31 has far less ALU per
transcendental and may rank them the other way round. **Use SFU as the device proxy
and these timings as the desktop one, and do not assume either predicts the other** —
only the Brick settles it.

**The tap count is a confound that this table cannot resolve.** The one-tap rows sit
below every four-tap row, but `sharp-shimmerless` has a fifth of `pixellate`'s ops
*and* a quarter of its taps, so nothing here separates the two savings. Four taps is a
fixed cost across everything this repo ships, which is why it was invisible until a
one-tap shader was vendored to compare against.

Measured cost of the two optional features, at 1024x768 from 320x240:

- **curvature costs ~8%** (v8 123.2 → 132.8 against `pixellate`). Clears the noise.
- **gamma is free** — `crt-perfect` 103.6 → 104.5 and v8 123.2 → 122.7, both at or
  inside the 0.9% noise floor, even though the `pow` is 6 of the 14 SFU slots. Another
  sign this GPU is not SFU-bound.
- **`crt-perfect` is at parity with `pixellate`** (103.6%) and v8 costs ~19% more than
  it. Worst case measured, v8 with curvature, is 133% of the yardstick.

Comparing two shaders at their own defaults is fair here even though they differ
(0.55/0.40 against 0.60/0.20): both are non-zero, so both take the same branches and
issue the same instructions. Amplitude is data, not work.

The two independent implementations are the whole point of this setup: an error has to
be made identically in GLSL and in numpy to slip through. It has happened once (see
`pow(0,k)` below), so also sanity-check on a real GPU rather than the model alone.

## Shader header format

Every shipped shader opens with this block. **Line comments, hard 80-column limit**
(the separator is `// ` + 77 dashes, exactly 80). Order is fixed: name, licence,
parameters, description, notes.

```glsl
// <name> - <one-line description, lowercase, ending in a period.>
// -----------------------------------------------------------------------------
// Author:  sinedied
// Licence: MIT - Copyright (c) 2026 sinedied
//
// <the MIT paragraph, wrapped to 80, identical in every file>
// -----------------------------------------------------------------------------
// PARAMETERS
//
//   <xx_name>  <range>  <Sentence. What 0 or 1.00 does.>
// -----------------------------------------------------------------------------
// <What it does, in one short paragraph. Five or six lines is plenty.>
//
// Notes:
// - <One or two phrases. Two or three notes. Omit the section if there is
//   nothing worth warning about.>
```

Then one blank line, then the `#pragma parameter` lines, column-aligned.

- **One paragraph, then `Notes:`.** Each note is one or two phrases, not a paragraph.
  The header is a user-facing reference; rationale, measurements and rejected
  approaches belong in this file or in a commit message. Both earlier drafts erred
  long and had to be cut twice.
- Ranges are written `0.00 - 1.00`, or `0 / 1 / 2` for enum-like parameters.
  Descriptions that do not fit wrap aligned under the description column.
- **Write the block out whole; never patch it incrementally.** Regex-editing these
  headers during the repo extraction produced stray `..` fragments and a duplicated
  copyright block, and took three attempts. Build the lines, assert none exceeds 80,
  splice on the first delimiter, then diff.
- Parameter identifiers are prefixed per shader (`cp_`, `lp_`, `pp_`, `dp_`) and
  lowercase. **Order them geometry first, colour last**, ending with `*_brightness`
  then `*_gamma` — every shader here follows that, so a user moving between them finds
  the same two controls in the same place.
- **The `#pragma parameter` label and the identifier are both user-visible, on
  different hosts.** RetroArch and RetroShader Lab render the quoted label; **minarch
  renders the identifier** (`ma_config.c` uses `params[j].name`). So the identifier
  has to read acceptably on its own *and* the label has to be worth reading. Do not
  flatten the label into a copy of the identifier — that happened between v4 and v5,
  and again in `pixel-perfect`, losing the descriptions on every host that shows them.
- The 80-column rule covers the header and the `#pragma` lines. The shader bodies
  predate it and are **not** being reflowed — that would churn the diff against
  upstream for no gain.

`tools/check_headers.py` enforces all of the above, including that the PARAMETERS
block and the `#pragma` lines agree on identifiers, order and ranges, and that every
default sits inside its own range. Run it after editing a header; it exits non-zero,
so it can gate a commit.

## Preconditions every shader here assumes

All three shipped shaders share the same four-tap scaler, so they share its
requirements. These are **correctness** conditions, not preferences — break one and
the output is wrong rather than merely different. They used to be stated in each
header; the headers were cut down to user-facing advice, so they live here now.

- **NEAREST sampling.** The shader computes its own area average from four taps. A
  LINEAR sampler filters underneath it and the result is filtered twice.
- **Render at the final output resolution, 1:1 with the display.** The mask, the
  scanlines and the LCD grid are all defined in output pixels. Anything that rescales
  the result aliases them and destroys the block structure.
- **Upscaling only.** Below 1:1 an output pixel's footprint spans more than two source
  texels per axis, and four taps can no longer average it. Downscaling is out of
  scope, not merely untested.

## The one design rule

**Nothing non-linear may be applied after the scaler's blend.**

The scaler area-averages four taps. At a non-integer scale a source pixel covers three
or four output pixels, so the count of partial-coverage pixels varies block to block.
Any non-linearity applied after the blend gives those pixels a coverage-dependent
shift, and that shift beats against the pixel grid as visible moire.

Three separate, individually reasonable ideas each broke this and each brought the
moire back. Measured as low-frequency energy on a checkerboard at 320x240 → 1024x768,
where anything above ~0.2 is visible:

| What | Beat | Note |
|---|---|---|
| baseline, nothing non-linear after the blend | **0.02** | |
| linearise taps → blend → re-encode (v1/v2) | 3.35 | the original bug |
| output gamma after the blend | 1.53 at γ=1.4, 3.06 at γ=2.0 | how `dmg_dot_matrix` does it |
| `clamp(x,0,1)` from `cp_brightness > 1` | 0.13 at 1.25, 4.84 at 4.0 | the clamp *is* a non-linearity |

The fixes: blend in the encoded domain and modulate with a single `sqrt` (gamma 2.0
makes `sqrt(linear*m) == encoded*sqrt(m)`); apply `cp_gamma` to the four taps *before*
the blend; and treat `cp_brightness` above ~1.5 as a look, not a correction —
`cp_gamma < 1` brightens more, with zero clipping and zero added beat.

A soft shoulder does **not** rescue a post-blend curve. Reinhard measured 2.48 where
the hard clamp measured 0.26, because it curves the whole range instead of just the
top. Do not re-try this.

**The rule has a second half, found while building `lcd-perfect`:** multiplying a
scaled image by a pattern is *itself* a violation whenever the pattern's dark part
lands where the scaler's soft transition pixel lands. That construction computes
`mean(source) * mean(pattern)` where it owes `mean(source * pattern)`; the two differ
by their covariance inside the pixel, and if pattern and transition are locked to the
same cell boundary that covariance is large and varies cell to cell. It measured 2.5,
twelve times the visible threshold, with no non-linearity anywhere. The fix is to
weight the blend by how much *aperture* falls each side of the boundary rather than
how much area — exact, and free when the aperture's integral is exactly `x` at an
integer boundary. crt-perfect gets away with the naive form only because its pattern
peaks at the cell *centre*.

**Normalise a modulation on its peak, not its mean.** Mean-normalising is tempting —
the pattern then costs no brightness at all — but it puts the pattern's top above 1,
so every bright pixel meets the output clamp, which is the post-blend non-linearity
the table above already convicts. Measured on `lcd-perfect`: mean-normalised, beat
0.60 and grid contrast 37; peak-normalised, beat **0.22** and contrast **58**. Better
on both axes at once.

**Do not turn this into "brighten with gamma, never with gain."** That advice was
given here and has been **rejected by the project owner**: gamma below 1 flattens
contrast and washes the colours out, and clipping is what old CRTs and LCDs actually
did — which is the thing being simulated. Peak normalisation is about where the
*pattern* sits, not about how the user is told to brighten. `lp_brightness` and
`cp_brightness` are legitimate controls; the headers state what they cost and stop
there.

## Barrel distortion (crt-perfect-v6, v7, v8)

Curvature is **pure ALU** — a radial polynomial warp is `dot(c,c)` and a few
multiply-adds, with no `tan`/`atan` anywhere. That is what makes it affordable here
where CRT-Geom-style curvature is not:

| | ops | tex | SFU | curvature off | curvature on |
|---|---|---|---|---|---|
| `pixellate` (yardstick) | 292 | 4 | **30** | 100.0% | |
| `crt-perfect` flat | 501 | 4 | **14** | 104.7% | |
| v6 — patterns flat, black on all four sides | 588 | 4 | **14** | | |
| v7 — patterns warped, border cropped away | 596 | 4 | **14** | | |
| v8 — patterns warped, nothing cropped | 628 | 4 | **14** | 124.3% | 134.4% |
| v9 — v8 with the band-limit made uniform | 626 | 4 | **14** | 108.3% | 117.3% |
| **v10 — v9 with the pitch computed as if flat** | **610** | 4 | **14** | **107.5%** | **117.2%** |

**SFU never moves**, and it never predicted the time either — see the benchmark
section. The figure that matters here is that **v8 cost 19.6 points over the flat
shader even with curvature switched off**, and v9 gets that down to 3.5.

### The pattern pitch is computed as though there were no curvature

Curvature must not change the pattern's *pitch*, only its *position*. v7 to v9 lifted
the pitch floor to `cp_min_pitch * jmax` so the most magnified corner would keep
`cp_min_pitch` output pixels per cycle — and since the floor applies frame-wide, that
quietly rescaled the pattern everywhere:

| `cp_curvature` | cycles per source line | scanlines drawn |
|---|---|---|
| 0.00 | **1.000** | 240 |
| 0.05 | 0.933 | 224 |
| 0.10 | 0.838 | **201** |
| 0.15 | 0.767 | 184 |

One cycle per source line is what makes scanlines read as scanlines. Losing it is worse
than anything the floor was protecting against, because **curvature is a distortion by
construction** — artifacts it creates inside the region it is distorting are the effect,
not a defect in the pattern. v10 drops `jmax` from both the floor and the band-limit, at
which point `jmax` is dead and comes out entirely (626 → 610 ops).

The corners then run finer than the band-limit assumes: 2.16 to 2.80 output pixels per
cycle across the parameter range, always above the 2.0 that would alias, so the pattern
is drawn a little stronger there than its true box average rather than breaking up.
Measured evenness is 1.11–1.15, the same band as every other version.

**Nothing in the harness could see this.** Every curvature test measures a flat grey
field, or a checkerboard through the scaler with the patterns switched off — none of
them has a source with rows in it, so none of them can watch the pattern drift off the
source. It was caught by looking at the screen. `beat.py:source_lock()` now checks it
directly, against the older behaviour as a control.

### Do not make a band-limit argument per-fragment

This is the single most expensive mistake made in this family, and the v7 notes
asserted the opposite with confidence, so it is worth stating flatly:

> `boxSinc` holds a `sin` and `nyquistFade` a `smoothstep`. While their argument
> depends only on uniforms, **the driver hoists them out of the fragment shader** and
> evaluates them once per draw. Multiply that argument by anything per-fragment and
> you buy two `sin` and two `smoothstep` per pixel.

v7 and v8 band-limited on `freq * jac`, where `jac` is the local magnification, and
paid that on every frame whether or not curvature was on. Bisected by removing one
piece of v8 at a time:

| | vs `pixellate` | recovered |
|---|---|---|
| v8, curvature off | 124.0% | |
| minus the per-fragment band-limiting | **107.5%** | **16.5 pts** |
| minus `jac` on the scaler footprint | 122.4% | 1.6 pts |
| minus `jmax` / `noWarp` on the pitch | 123.6% | 0.4 pts |
| minus the tube mask multiply | 128.0% | none |

v9 band-limits on `freq * jmax` instead. `jmax = (1+4k)/(1+k)` is the largest
magnification anywhere in the frame and depends only on `cp_curvature`, so the
expression stays uniform and stays hoisted **in both modes** — the curvature-on path
gets 16 points faster as well. It band-limits as though every pixel sat at the most
magnified corner, which can only understate the amplitude, and the pitch floor already
held every local frequency at or under `1/cp_min_pitch`, so no aliasing margin was
given away. The cost is about 6% flatter pattern contrast across the frame; measured,
v9 is *more* uniform than v8 (1.08 against 1.13), which is the same fact stated kindly.

**Branching is not the lever.** Three other shapes were measured and all were worse:
computing the uniform form and overwriting it inside the branch (116.8%), a strict
`if/else` (112.0% off but **136.2% on**, i.e. worse than v8 in the mode it was meant to
help), and adding further uniform guards on the footprint and tube multiplies on top of
the winner (109.7%, a 2.3-point regression). Removing the per-fragment dependency is
the lever.

At `cp_curvature = 0`, **v9 is bit-identical to the shipped flat shader** — 0/255 over
three sources, four scale factors and both mask types. v8 measures 1/255 on the same
sweep, so v9 is the stricter superset. The guard is a uniform branch either way.

### What the warp is divided by is the whole design

All three apply the same warp, `c * (1 + k*r2)`. They differ only in the constant it
is normalised by, and that one constant decides the entire look:

| normalised by | corners | edges | result |
|---|---|---|---|
| nothing (v6) | inside the screen | inside the screen | tube, **black on all four sides** |
| `(1 + 2k)` — the corner value (v7) | exactly 1:1 | pushed off-screen | **the whole border is cropped**; only 89.8% of the source survives |
| `(1 + k)` — the edge-midpoint value (v8) | past the image | exactly 1:1 | tube fills the screen, **black only in the corners, nothing cropped** |

`r2` is 1 at an edge midpoint and 2 at a corner, which is where those two constants
come from. Both axes normalise by the same value, so this is symmetric at any aspect
ratio, and there is no cubic to solve for a zoom factor.

**v7's failure is worth understanding rather than just avoiding.** The curved border
*is* the cue that reads as a tube. Crop it and all that is left is the interior
magnification, which looks like a lens bump in the middle of a flat image — which is
exactly how it was described on sight. The distortion was correct; the framing was
not.

| | screen black | source visible |
|---|---|---|
| v6 | 18.45% | **100%** |
| v7 | 0.00% | 89.8% |
| **v8** | 4.50% | **100%** |

v8 across its range, at 1024x768: black 2.7% / 4.5% / 5.8% at `k` = 0.05 / 0.10 / 0.15,
**100% of the source visible at every setting**, and every edge midpoint lit — the
black is corner-shaped, never a bar.

### A curved image needs a tube mask even when it fills the screen

v7 dropped the mask because nothing was ever outside the image. v8 cannot: the sampler
is `CLAMP_TO_EDGE`, so an unmasked corner **smears the border texel** across the whole
corner rather than showing nothing. The first v8 prototype did exactly that and it was
obvious in the render and invisible in every number.

### No number in this repo could catch v7

This is the process lesson, not a footnote. Every gate was green on v7: 1/255 against
an independent model, 0.039 beat, pitch invariant exactly 3.00, 0% black pixels. It
had silently thrown away 10% of the image, including the entire border.

`preview.py --only border-grid` renders a grid whose four edges are each a different
colour, which is the pattern that shows it. A screenshot, a plain grid or a
checkerboard all show the interior distortion and say nothing about what happened to
the edges. **Anything that changes geometry gets looked at, not just measured.**

### The footprint correction is anisotropic

The scaler derives `range` from a constant `InputSize/OutputSize`; under warp the local
magnification varies, so at the edges the footprint is too small and the blend is wrong
over about a third of the frame, by up to 94/255. The correction is *not* the scalar
radial factor: for `u' = u(1 + k(u^2+v^2))` the axis-aligned derivatives are
`1 + k(3u^2 + v^2)` and `1 + k(u^2 + 3v^2)`, which differ. Both fall out of `c*c`,
already computed for `r2`, so the exact per-axis Jacobian costs the same as the wrong
scalar one. Against a supersampled reference (RMS, 8-bit levels):

| `cp_curvature` | no correction | isotropic (wrong) | anisotropic (shipped) |
|---|---|---|---|
| 0.05 | 0.901 | 0.861 | **0.817** |
| 0.10 | 1.049 | 0.927 | **0.778** |
| 0.15 | 1.239 | 1.007 | **0.753** |

Note the direction: uncorrected error *rises* with curvature while corrected error
*falls*. That divergence, not the absolute values, is what says the correction is right
rather than merely different.

### Warped patterns: the invariant, and why no image metric can check it

A pattern locked to the source cannot also be locked to the output pixel grid, so under
warp its screen pitch varies and is finest at the corners. Two things keep it safe, and
both are needed:

- the pitch floor is lifted to `cp_min_pitch * jmax`, where `jmax = (1+4k)/(1+2k)` is
  the largest magnification in the frame, so **even the worst corner keeps
  `cp_min_pitch` output pixels per cycle**;
- `boxSinc` and `nyquistFade` are evaluated on the *local* frequency `freq * jac`.

**Check this on the geometry, not on the image.** `beat.py:min_local_pitch()` does. The
obvious empirical checks do not work, because aliasing does not remove pattern energy,
it relocates it — so a strength or uniformity metric reads an aliased pattern as
perfectly healthy. Measured: the naive implementation is *more* uniform (1.07–1.14)
than the correct one (1.10–1.21) at every curvature, and its corner strength is equal
or higher. Only the invariant separates them:

| smallest output px per cycle | v7 | naive |
|---|---|---|
| 320x240 -> 1024x768, k=0.10 | **3.00** | 2.74 |
| 480x272 -> 1024x768, k=0.10 | **3.00** | 2.57 |
| 480x272 -> 1024x768, k=0.20 | **3.00** | 2.33 |

v7 sits exactly on the floor everywhere; naive falls through it.

### Two traps hit while measuring curvature

- **A pattern-strength ratio is invalid on a shader with black corners.** Tiles at the
  tube edge are part black, or contain the mask's one-pixel fade, and either way carry
  a gradient that RMS-about-the-mean scores as pattern energy: 29 against a frame-wide
  14.4, which inverts the ratio and reports a flat shader as collapsing. v7 crops
  rather than leaving corners black, which is the only reason the check ever worked —
  so **v8 shipped with it silently not applying**. `beat.py` now excludes tiles that
  are not wholly inside the tube *and* clear of the fade.
- **A row-mean profile is invalid on a warped image.** Measuring pattern contrast as
  the peak-to-peak of a tile's row-mean reported the corner collapsing from 34.7 to
  3.2 — a 10x falloff that looks exactly like catastrophic aliasing. The scanlines are
  curved there, so averaging along tile rows smears them. RMS about the local mean has
  no preferred direction and reads 12.4 against 12.1 on the same image.
- **A curved render cannot be measured with the flat beat metric.** Barrel distortion
  varies the local magnification on purpose, so block sizes genuinely change across the
  frame and a band-limited FFT scores that intended variation as moire — 4 to 20 where
  the flat metric reads 0.26. Difference against a supersampled reference of the same
  warp instead, and read the reference-noise trap below before trusting the result.

### The slot mask has an irreducible knife edge under warp

The slot mask picks its row parity with `floor()`. Flat, that argument is constant
along a row, so the `+ 1e-3` epsilon nudges whole rows clear of the boundary. **Under
warp the argument varies smoothly across the frame, so it must cross an integer
somewhere** — that crossing is what makes the rows — and wherever it does, float32 and
float64 can land on opposite sides. No epsilon fixes this; an epsilon only moves where
the crossing happens.

Measured at curvature 0.10: **16 pixels of 786432**, every one within `1.9e-5` of an
integer against a median distance of 0.25 across the frame. Isolated single pixels,
never a region, and only ever on the slot mask.

This is what `Model(outliers=N)` is for. Raising `tolerance` to 45 would have covered
it and simultaneously blinded the check to a real systematic error of the same size;
the outlier budget keeps `tolerance` at 1, counts the offenders, and prints the count.
Negative-tested both ways: a +3/255 bias everywhere fails on 921600 outliers, and
shrinking the budget to 4 fails on 16.

## LCD apertures, and why they are not sinusoids

An LCD cell is a rectangle in a black matrix, and the mean of a rectangular pulse
train over an output pixel has a closed form. So `lcd-perfect` differences an
antiderivative instead of band-limiting a sinusoid: `floor`, `clamp`, one divide,
**zero transcendentals**, and it is the true box filter rather than an approximation
of one. libretro's `coverage.inc` (`intersect_rect_area`, used by `authentic_gbc`) is
the same idea in 2D; the separable 1D form is cheaper.

Three things that took measuring:

- **Put the aperture at the leading edge of the cell, not centred.** Centring splits
  the matrix line across a cell boundary, so at *every* integer scale factor it lands
  half in one output pixel and half in the next and contrast halves — at exactly 2.0
  output pixels per cell the halves are symmetric and the grid vanishes entirely.
  Edge-alignment fixes all of them and needs no phase-shift term. Dense sweep 2.0–8.0:
  centred min 0.000 / median 1.21, edge min 0.500 / median 1.25.
- **A hard-edged aperture aliases.** A rectangle carries every harmonic of the cell
  frequency; those above Nyquist fold back, and at 3.2 output pixels per cell the
  third harmonic lands on a 16-pixel period, squarely visible. A one-pixel box
  prefilter only attenuates it ~15×, nowhere near enough. Widening the edge into a
  ramp of **twice the matrix width** took the worst measured beat from 2.52 to 0.23.
  Note this is invisible unless you compare **at matched contrast** — softening also
  raises contrast, so at fixed visibility it looks useless or worse. It was nearly
  discarded for exactly that reason.
- **Subpixel stripes do not band-limit themselves.** Their pattern repeats once per
  cell however thin the stripes are, so unlike the cell grid they never flatten; below
  ~3 output pixels per cell they become colour speckle at full strength. They need an
  explicit fade. They also cost beat far faster than the grid (0.24 at 0.20, 0.56 at
  0.35, 1.18 at 0.50) and, unlike the grid, want **mean** normalisation — a stripe
  concentrates one channel's light into a third of the cell, so its mean is what must
  stay at 1 for white to stay white, which inherently puts its peak near 3. Faking
  subpixels either darkens or clips; there is no third option.

### Aperture shape decides how strong a grid you can afford

Matching `lcd1x`'s look means a **column-dominant** grid at a 4:1 column-to-row swing
ratio. Measured, at 320x240 -> 1024x768 on white:

| | mean | row | col | col/row | beat |
|---|---|---|---|---|---|
| `lcd1x`, the target | 75.3% | 24.0 | 96.0 | 4.00 | 1.865 |
| `lcd-perfect` v1 | 85.0% | 57.6 | 25.4 | 0.44 | 0.244 |
| v2b, hard matrix + balance | 80.7% | 15.2 | 71.0 | 4.65 | 0.385 |
| v2a, sinusoid + balance | 72.6% | 24.4 | 96.2 | 3.94 | **0.144** |

**The sinusoid reaches it and the hard matrix cannot.** Every v2b configuration at a
4:1 ratio with a column swing near 96 measures past 0.4; its best inside the budget is
71, a quarter short. A hard-edged aperture is mostly harmonics, they fold back, and
the stronger you make it the worse that gets — which is the same thing v1's ramp was
compensating for, arriving structurally instead of empirically. **Want a strong grid,
use a smooth profile.**

The sinusoid is also *cheaper*, 515 ops against 646, because it needs no `floor`, no
`clamp` and no ramp integral. It costs 6 more SFU lanes, which is a good trade.

Two things it does not get for free:

- **Even-integer scales lose all contrast.** The edge-aligned trapezoid fixed those by
  construction; a sinusoid puts both samples of a cell on symmetric points of the
  cosine and reads the same value from each, so at 2.0 output pixels per cell the grid
  vanishes. An **unconditional** half-output-pixel shift removes every dropout over a
  dense 2.0-8.0 sweep and is never worse than not shifting (min contrast 0 -> 60,
  median unchanged). Do not ramp it in; there is nothing to trade.
- **But the shift is worth more than it costs.** At 320x240 -> 640x480, exactly 2.0
  output pixels per cell, v2a keeps a column swing of 71.5 against its own 96.2 at
  1024x768 - 74% retained. `lcd1x`, an unshifted sinusoid, keeps 19.1 of 96.0, so 20%.
  The minimum supported resolution is where this decision is worth the most.
- **The blend identity needs re-checking, not assuming.** The aperture-weighted blend
  is free only because `A(n) == n` at integers. For `A(x) = x - m*sin(TAU*x)/TAU` it
  holds exactly, and once phase-shifted `A(n) - n` is a constant across the draw, so
  it stays free. Verified numerically to 6e-14 before any shader was written.

### Do not hardcode a geometry ratio

v1 hardcoded `GAP_ASPECT = 0.4` from the Game Boy Color panel measurement, which is
physically right - real panels are row-dominant. It also made the `lcd1x` look
*unreachable*: the constant caps the column gap at 40% of the row gap, so the ratio
tops out at 0.61 no matter how far `lp_gap` is pushed. Authenticity and the look
people actually want are different targets; the ratio is a parameter (`lp_balance`),
not a constant.

Same shape of mistake in the stripe fade: `smoothstep(3, 6, px_per_cell)` leaves the
stripes at 1.3% strength at 3.2 px/cell, which is 320x240 into 1024x768 - the most
common scale there is. A threshold chosen against one failure mode was silently
disabling the feature everywhere else. Measure a fade window across the scales that
actually occur.

`simpletex_lcd`'s luma-biased grid (`lineWeight *= luma + (1-luma)*(1-BIAS)`, "hide
the grid on dark pixels") is **not** safe here: it computes the gain from the blended
colour and multiplies it back, which is a non-linearity after the blend. Measure
before adopting.

**Out of scope for `lcd-perfect`, decided deliberately** (this used to live in the
shader header; it is here so it is not re-litigated):

- **Response-time ghosting.** Needs the previous frame, so it needs a feedback pass,
  and the intended hosts run single-pass GLSL only.
- **Backlit versus reflective response, and panel colour casts.** Those belong to a
  colour pass, not to a geometry one.
- **Non-square pixels.** Every panel in scope is square-pixel.

One measured wrinkle to know about: the stripes leave a tint of about one 8-bit level
on a white field, because the `sqrt` is applied per channel and the three stripes do
not sample the same phases.

## The DMG is a negative display, and it changes the sign of everything

A Game Boy DMG is a **reflective, normally-white STN panel with no backlight**.
Undriven crystal passes light, so an unpowered pixel shows the pale green substrate
and driving a pixel makes it **dark**. The gaps between pixels have no electrode at
all, so they can never be driven and sit permanently at the lightest state.

So its matrix is **lighter than a lit pixel** — the opposite of every backlit panel
`lcd-perfect` models. That is why `dmg_dot_matrix` defaults its grid colour to white
and mixes *toward* it, and why the grid is invisible on a white field and strongest on
dark content, which is how a real DMG reads. A web search asserted the opposite and
was discounted: the same answer claimed a DMG's "on" pixels look "almost white", which
is backwards for this panel, and it cited no measurement.

Three consequences that are not obvious until the sign is right:

- **A brightness default above 1 has no job here.** Across this family the gain exists
  to restore the level the pattern removes — `lcd-perfect` and `crt-perfect` sit at
  82% and 83% of white *with* their 1.20 and 1.25 lifts. A DMG grid adds light, so
  dmg-perfect sits at **100%** of white and a lift only meets the clamp. Measured 2.06
  beat on a full-range checkerboard, against 0.12 at unity. Check the mean level on
  white before copying a brightness default across.
- **A mean-normalised aperture cannot be reused as a coverage mask.** `lcd-perfect`
  normalises its aperture to a *mean* of 1, which for these parameters peaks near 2.9;
  as a mask that drives the mix past white and blows the frame out. A mask has to be
  **peak**-normalised, 0 in the gap and 1 in the dot.
- **No ramp.** A plain rectangular pulse box-filtered over the output pixel *is* the
  reference at a whole scale factor, so the trapezoid `lcd-perfect` v1 used would be
  visibly softer than the thing it is copying — and it costs 334 instructions against
  262. Cheaper and more faithful at once; the box filter is already the correct
  anti-aliasing width. The band-limiting the ramp was there to provide comes instead
  from the gap floor below, which is exact at a whole scale where the ramp was only
  close.

### State a minimum feature size in output pixels, not as a share of a cell

`dmg_dot_matrix` draws a line of exactly **one output pixel**. That is right at a
whole scale factor and wrong everywhere else: a 1px line cannot be placed 6.4 apart,
so its cells alternate 6, 7, 6, 7; and one pixel is 16% of a cell at 1024x768 and 50%
at 320x288, so it is not the same shader at two resolutions.

Making the gap a *share* of a cell fixes both — and introduces a third fault, because
a share lands on an arbitrary number of output pixels. **Below about two pixels a line
has no guaranteed fully-covered pixel at its core**, whatever its phase, so how its ink
spreads shifts cell to cell. Measured on an exactly-even synthetic grid at a 6.4px
period: a 1.28px line reads 1.7% spacing variation, a 1.99px line reads 0.04%. That is
a 40x difference with the geometry held exactly constant, and it matches which one
reads as steady by eye.

So the rule is a floor in output pixels, applied per axis:

```glsl
vec2 sc    = OutputSize / max(InputSize, 1.0);
vec2 offs  = abs(sc - floor(sc + 0.5));      // smooth, never an equality
vec2 room  = clamp(sc - 4.0, 0.0, 1.0);
vec2 minpx = 1.0 + clamp(offs / 0.25, 0.0, 1.0) * room;
vec2 gapEff = max(vec2(dp_gap), minpx / sc);
```

Three things in there took measuring:

- **`room` is not optional.** The second pixel costs `1/sc` of a cell, which is
  already 40% at five output pixels per cell and **60%** at the 3.33 a Game Boy gets
  down the screen at 640x480 — where it stops edging the dot and starts swallowing it.
  Without the limit, 640x480 measured a 1.35px *dot* rather than a line. The metric
  caught it; the eye would have too, eventually.
- **The whole-scale test is a distance, never an equality.** A mathematically whole
  scale can land a few ULP off, which is already a recorded trap here.
- **The floor has to fade out with the parameter.** At `dp_gap` 0 the floor would
  otherwise hold a 1px line open under a slider the user has closed, so it is gated by
  `smoothstep(0.0, 0.01, dp_gap)`.

### The two-pass pipeline everyone reaches for collapses into one pass

Frontends get a good DMG by drawing `dmg_dot_matrix` at a whole scale factor and
letting a `pixellate` pass do the rest. That is not a workaround for a missing
feature — it is a **different and better computation**, and it is worth knowing why,
because v1 did the naive thing and broke up at a fractional scale.

Drawing the matrix at a whole scale then resampling gives `mean(source × grid)` over
each output pixel. Multiplying a scaled image by a grid gives `mean(source) ×
mean(grid)`. The two differ by their covariance inside the pixel, and a dot-matrix
line sits exactly on the cell boundary — which is exactly where the scaler's soft
transition pixel is — so that covariance is large and varies cell to cell. Measured
against the two-pass as ground truth, v1 was **67/255** out at 1024x768.

Both passes are linear, so the composite has a closed form. Writing `a` for
`dp_grid`:

    O = (1 - a) * A  +  a * [ L * dot + level * (1 - dot) ]

`A` is the ordinary **area**-weighted four-tap blend; `L` is the same four taps
weighted by how much **aperture** falls each side of the texel boundary; `dot` is the
mean lit coverage. Both means are needed, and that is the part that is easy to get
wrong:

| | max difference from the two-pass |
|---|---|
| area mean only — what v1 did | 10.1 at 1024x768, 45.3 at 640x480 |
| aperture mean only — what `lcd-perfect` does | **98.0** |
| **both** | **0.075**, and exactly 0.000 at whole scales |

**The aperture-weighted blend alone is right in `lcd-perfect` and wrong here**, because
its pattern peaks at the cell *centre* while a dot matrix's gap sits on the cell
*edge*. Porting the technique across by analogy makes things nine times worse than
doing nothing. It cost 25 instructions to measure that and it would have cost a
release to assume it.

`tools/twopass.py` builds the pipeline literally — nearest at a whole scale, hard
grid, then an exact box resample written from scratch — and gates the match. It
self-tests by checking that at a whole scale its own pass two is an identity.

Two details the closed form needs:

- **Where a pixel lands wholly in a gap the aperture weight is 0/0.** The value is
  arbitrary and float32 need not pick what float64 picks. It is harmless while it is
  multiplied by a coverage of zero — and it is *not* harmless the moment something
  else reads it, which is what a shadow term does. Fall back to the area weight.
- **State the line width in output pixels via the whole scale that fits**, not as a
  share of a cell: `N = max(floor(min(sc.x, sc.y) + 1e-3), 1.0)`, gap = `dp_gap / N`.
  That is what the two-pass does, it holds the line near one pixel at every scale, and
  at a whole scale it is exactly one pixel so the reference identity survives. Below
  N = 2 the picture disappears into the substrate entirely — 60% flat grey, a
  black-frame-class failure — so the grid still needs its fade.

### A metric that scores smoothness will ask for the wrong shader

v1 forced every line to at least two output pixels. That came from `grid.py`'s
spacing CV, which reads a 1.28px line as 1.7% and a 1.99px line as 0.04% — so the
metric asked for the widest line available, and the first thing anyone said about v1
was that its lines were far too fat.

The CV was not lying, it was answering a different question. A narrow line really
does spread its ink differently from cell to cell; that is edge softness, and it is
much less visible than a line twice the width it should be. `grid.py` now reports
the CV **and** the part of it that is not edge softness, by measuring a synthetic
grid of the same spacing and width whose lattice is exact by construction:

| | total CV | of which lattice |
|---|---|---|
| `dmg_dot_matrix` at 1024x768 | 7.7% / 8.9% | **6.7 / 7.6** |
| dmg-perfect-v2 at 1024x768 | 1.8% / 0.6% | **0.1 / 0.3** |

The bracketed figure is the one that means something is wrong. Judged on the total,
v2 looks four times worse than it is.

**A metric is a proxy, and a proxy that has never been checked against a preference
will eventually be optimised against that preference.** This one shipped a shader
nobody wanted, and it was only caught because the shader was looked at.

### A shadow measures opacity, and opacity is relative to the paper

A pixel casts a shadow because it blocks light, so its shadow strength is its
**opacity**, and on a reflective panel that is `1 - luma / luma(paper)` — the
level of undriven panel is the divisor, not an absolute. dmg-perfect-v2 used
`clamp(1 - luma, 0, 1)`, which is the same expression with the paper hardcoded
to **white**.

Nothing in a Game Boy palette is anywhere near white, so every shade was judged
most of the way opaque and the shadow became a flat dimming of the whole
picture. Measured on real frames: the undriven shade is luma 0.455 and covers
**67–75% of the screen**, and it was casting **55% of a full shadow**. Paper
dimmed 2.87/255 against ink's 3.88 — a ratio of **1.4x**, which is why it read
as a veil rather than as depth. With the divisor restored the same frame gives
0.02 against 1.45, a ratio of **65x**.

The tell that this was the cause rather than merely a plausible fix: on **GBC**
content, where the paper really is near-white, the old expression measures
*correctly* (paper opacity 0.027). It was never wrong in general — only whenever
paper is not white, which is every DMG palette in existence.

**The divisor cannot be a constant.** Lightest shade, by core:

| palette | paper luma |
|---|---|
| Gambatte GB-DMG — its default | **0.401** |
| mGBA DMG Green | 0.560 |
| Gambatte GB-Light | 0.568 |
| Gambatte GB-Pocket / SameBoy olive | 0.664 – 0.767 |
| SameBoy lime | 0.806 |
| SameBoy / mGBA greyscale | 0.973 – 1.000 |

So it is taken as **the brightest of the four taps the scaler already has**,
floored at 0.35. The taps are free and cannot be wrong on the high side, since
undriven panel is by definition the brightest thing near a dot; the floor stops
the estimate collapsing in the middle of a large dark region, where all four
taps are ink and the shadow would otherwise switch off exactly where the picture
is darkest. **The floor must sit below the darkest paper anyone ships** — 0.45
was proposed and would have dimmed Gambatte's *default* palette by 10.8%,
reintroducing the same bug on the most likely core, and the sample screenshots
at 0.455 would have hidden it.

Cost: the shadow-off path is **295 ops, unchanged from v2** - the branch is
uniform, so the fix is free unless the shadow is asked for. With it on the
static count is 459 against v2's 400, and it is still **6 SFU**, still four
taps, and still free of transcendentals.

**Do not copy libretro's caster.** Its Game Boy shaders compute alpha from
`1 - source.rgb` exactly as v2 did, and get away with it because those presets
*replace* the palette — they reduce the frame to a brightness and re-colour it
from their own `COLOR_PALETTE`, so the input they are handed genuinely does have
white paper. They also add a `baseline_alpha` of 0.05 to 0.10 so that even fully
undriven dots cast a shadow, which is a deliberate look and the exact opposite
of what is wanted here. No libretro Game Boy shader reconstructs a drive level
from an already-palettised frame; there is no prior art for this.

### A cast shadow goes under the panel, not into the gaps

v3 subtracted the shadow from the gap colour and only from there, on the
reasoning that the gap is the substrate and the substrate is what a shadow falls
on. That is geometrically true and visually useless: the gap is **one output
pixel wide**, so the shadow could only ever darken the grid lines. It read as a
mesh drawn on top of the picture rather than as anything lying underneath, and
at a whole scale factor it was very nearly invisible — 0.7 opacity on a 20x
render shows almost nothing.

The optics say otherwise. On a reflective panel the light crosses the liquid
crystal, reflects off the substrate and crosses back, so a neighbour that shades
the substrate scales **whatever that cell finally shows**. So the shadow is one
multiply on the finished colour:

    col *= 1.0 - dp_shadow * opacity(casting cell) * displacedAperture;

and the "under" behaviour falls out for free — an undriven cell is transparent
so the shadow reads through it clearly, a driven cell is already dark so it
hides it. That is what makes the dots look raised instead of outlined.

Three consequences worth keeping:

- **It is cheaper in beat, not dearer.** Confining a pattern to the one-pixel
  grid lines is the worst thing you can do to it: that is the highest frequency
  in the frame. Measured on a DMG palette, v3's shadow costs 0.32 at 0.35 and
  0.56 at 0.75, where v4 costs **0.19 and 0.29** — and at 0.15 to 0.30 v4
  measures *below* its own shadow-off baseline. A shadow that lies under
  everything is a low-frequency multiply; one that lives in the gaps is not.
- **Offsets belong in source pixels.** v3 measured its offset in output pixels,
  so "1.5" was three tenths of a cell at 5x and half a cell at 3x — the same
  parameter meaning a different look at each resolution, which is the fault
  `dp_gap` was fixed for two versions earlier. A shadow is thrown by a dot, so
  it belongs a fraction of a *cell* away. Verified scale-invariant: a dot in
  cell 16 throws a shadow spanning exactly +0.5 to +1.5 source pixels at 5x, 8x,
  13x and 20x alike.
- **The casting cell needs its own tap.** At a cell or more of offset it is
  outside the four the scaler holds. One nearest sample is right rather than
  merely cheap: opacity is a per-cell quantity, and the displaced aperture
  already supplies the edges. It costs a fifth texture fetch, inside the uniform
  branch, so nothing pays for it with the shadow off — the off path is 291 ops
  and four taps, bit-identical to v3.

And the same `floor()` trap once more, in a new place: the casting cell index is
`floor(p - offset)`, which lands exactly on a boundary for a great many pixels
at once whenever the offset is a whole number of source pixels away from the
half-texel sample position. A few ULP then pick a different cell across what may
be a hard edge in the content, which measured **102/255**. `floor(q + 1e-3)`
resolves it toward the cell whose dot actually starts there; where the bias
picks the far side instead, the displaced aperture is in its gap and the shadow
is zero anyway.

### A box filter you already have is a blur you can widen for free

The shadow's coverage is the exact mean of the displaced aperture over the
output pixel's footprint - that is what `dotInt(q + h) - dotInt(q - h)` divided
by `2h` computes. Widening `h` past the footprint therefore convolves the
aperture with a wider box, which is a real blur, and it costs **nothing**: the
same two antiderivative evaluations, a larger constant. Measured, the
everything-off path is 291 instructions with the blur and 291 without.

Checked against an explicit convolution of the hard pulse train rather than
assumed - the residual is discretisation only and falls as the window grows.

Two things to know before reaching for it elsewhere:

- **It fills in as it widens.** A box wider than the aperture's gap raises the
  minimum off zero: at a 0.80 duty cycle the trough goes 0.00, 0.50, 0.71 as the
  half-width goes 0.10, 0.20, 0.35 of a cell. For a shadow that is right - a
  blurred shadow should lose its internal structure - but a pattern that needs
  to keep its contrast cannot be softened this way.
- **It only blurs what the aperture controls.** The shadow's strength also comes
  from a per-cell opacity that is sampled nearest, and widening the aperture
  window does not touch that. It works here because the aperture's gaps sit
  exactly where the opacity steps, so the hard part of the step lands where the
  coverage is already near zero.

### An affine trim is free after the blend, and free again when it is neutral

`dp_red`, `dp_green` and `dp_blue` are plain per-channel gains. A gain is affine
and the blend weights sum to one, so applying it to the finished colour is
*identical* to applying it to the four taps at a quarter of the cost - the same
argument that lets `pixel-perfect-v3` grade after the blend, and not an
exception to the design rule but its converse.

It goes on the finished colour rather than on the taps for a second reason: the
substrate is part of the panel, so it should take the same tint as the picture.

Behind a uniform branch it costs nothing at all when neutral, which is what
makes it worth having on a shader with a tight budget: **291 ops with the trim
present and neutral, the same as the version that had no trim.** Measured on a
DMG palette it adds no beat at any setting tested, including gains above 1,
because a Game Boy palette peaks at 0.455 and a 1.4x gain still does not reach
the clamp - which is the thing that would have cost beat.

### A weighted blend is stable where a max over the same taps is not

The paper estimate reads the four taps and takes their maximum. That is not
safe as written, and the reason is a variant of the `floor()` knife edge already
recorded here.

`B = floor(p + 0.5)` selects the tap *pair*. At an exact boundary — which at a
whole scale factor is not an edge case but every other pixel — it can land on
either side, giving `{n-1, n}` or `{n, n+1}`. **The blend does not care**,
because whichever way it goes the weight lands entirely on the same texel; that
is why the scaler has always been stable there. A maximum over the pair very
much does care: it swaps in a different neighbour, and on a real frame that
moved the shadow by **29/255** between the GPU and the model.

The fix is to weight before reducing — gate each tap by its own blend weight,
`k = wA.x * wA.y` and so on, through a narrow `smoothstep`. At the knife edge
both candidate pairings collapse onto the same contributing tap, so the estimate
is identical either way.

**The general lesson: a reduction over the taps is not automatically as stable
as the blend over them.** Any new term that reads the taps directly rather than
through the blend has to be checked against the boundary case separately, and a
whole scale factor is where to look, not a fractional one.

### Bit-identity with a reference is reachable, and worth gating on

At a whole scale factor a four-tap area average returns the source texel exactly, so a
scaler-based shader can be **bit-identical** to a point-sampling one. dmg-perfect
measures 0/255 against `dmg_dot_matrix` at 3x, 4x and 5x on both a flat field and a
game frame, wherever the two are set the same. That is a far stronger statement than
"looks the same", and `tools/grid.py` gates it.

The two 1/255 rows it reports are float32 and both were traced rather than shrugged
at: at a gamma of exactly 1 this shader skips the `pow` and the reference still
evaluates `pow(x, 1.0)`, which is `exp2(log2(x))` on a GPU and rounds; and at gamma
0.8 over a black gap `pow` has unbounded slope at 0, which moved 2 pixels out of 1.7
million. Wherever both take the same `pow`, the match is exact.

**That identity is what pins the gamma placement.** Putting the curve on the taps
instead would be design-rule-clean, but the reference gammas *after* its grid mix, and
`mix(pow(level,g), pow(c,g), m)` is not `pow(mix(level,c,m), g)` — on a dark pixel
under a light gap the two differ by **21 levels**, which is exactly where a DMG's grid
is most visible. So the cheap placement is kept and the cost is documented instead:
gamma 1.40 measures 0.86 beat against 0.12 at 1.00.

## GLSL traps that actually bit

- **`pow(0.0, k)` is undefined** and returned NaN on a real driver, rendering whole
  scanline rows black. Black texels are everywhere. Always clamp the base:
  `pow(max(x, 1e-8), g)`. Use 1e-8, not 1e-5 — the latter lifts pure black to 1/255 at
  γ=0.5.
- **Never branch on an exact comparison of a division result.** GPUs evaluate `a/b` as
  `a*rcp(b)`, so `720.0/240.0` can land a few ULP off 3.0 while the numpy model gets
  exactly 3.0. A `step()` on that flipped a whole rendering regime and ~30% of
  contrast. Use a narrow, biased `smoothstep` instead.
- **`floor()` used for row parity** has its argument cross whole numbers once per line;
  a few ULP flips an entire row's mask stagger. Add an epsilon: `floor(x + 1e-3)`.
  **Under a warp no epsilon helps** — see the knife-edge section above.
- **`cast` is a reserved word**, which is not obvious and cost a compile while
  prototyping a shadow term. `validate_glsl.py` catches it.
- **`flat` is a reserved word** in GLSL ES (an interpolation qualifier), and so are
  `smooth`, `noperspective`, `sample`, `input`, `output`, `filter`. `validate_glsl.py`
  catches these; a desktop-only compile may not.
- **`sqrt()` of an analytically-non-negative value** can still see a small negative in
  float. Clamp with `max(..., 0.0)`.
- `#pragma parameter` menus display the **identifier**, not the quoted label. Name
  parameters so they read correctly on their own.
- **A uniform the host never sets is 0.** If a parameter appears in a divisor, an
  unset uniform makes every pixel NaN — a black screen, not a subtle error. Guard it:
  `max(0.4995 * pp_sharpness * InputSize / OutputSize, 1e-6)`. This matters whenever a
  host does not parse `#pragma parameter`.
- **`mix(x, y, w)` returns `y` at `w == 1`.** When `w` means "weight on the low side",
  the low-side value must be the *second* argument. Getting it wrong on one axis only
  is invisible by eye and obvious against a reference model.

## pixel-perfect vs pixellate

`pixel-perfect.glsl` reproduces the widely used `pixellate.glsl` exactly, at a
fraction of the cost. Two things in the original are redundant:

- The four corner-area products and the divide by `totalArea` factor into one
  horizontal and one vertical weight. Verified over 200k random configurations: max
  difference **2.5e-15**.
- The 15 `pow()` calls implement `INTERPOLATE_IN_LINEAR_GAMMA`, which linearises each
  tap, blends, then re-encodes — the same gamma round-trip that breaks the design rule
  above. It is `pixellate`'s **default**, and it measures 3.5–5.7 beat where the
  encoded-domain path measures 0.000.

| | ops | tex | SFU |
|---|---|---|---|
| `pixellate.glsl` | 292 | 4 | 30 |
| `pixel-perfect.glsl` | 112 | 4 | **0** |
| `pixel-perfect-v2.glsl` | 131 | 4 | 6 |
| `pixel-perfect-v3.glsl` | 161 | 4 | 6 |
| `pixel-perfect-v4.glsl` | 174 | 4 | 6 |

Four taps stay: an output footprint spans up to two texels per axis, so four is the
minimum without delegating the blend to the texture unit. A one-tap LINEAR variant was
prototyped and is exactly equivalent (1/255, identical block widths and shimmer), but
was rejected — it makes correctness depend on the GPU's subtexel bilinear precision and
needs the opposite sampler setting to everything else here.

`tools/equivalence.py` proves the match: output diff, block-width distribution,
transition-pixel counts, moire, the `pp_sharpness` response, and v3's bit-identity
against the canonical shader at its defaults.

### The one-tap scaler is not hypothetical — it ships, and it is vendored

`sharp-shimmerless.glsl` (zadpos, public domain) **is** that rejected variant, shipped
by someone else and running on NextUI, spruceOS, MustardOS and CrossMix today. It is
now in `tools/vendor/`, so the trade is measured rather than remembered. It computes
the same box footprint, then instead of weighting four NEAREST taps it solves for the
one texcoord whose bilinear fetch already **is** that weighted sum.

| | ops | tex | SFU | sampler | vs `pixellate` |
|---|---|---|---|---|---|
| `pixellate` | 292 | 4 | 30 | NEAREST | 100.0% |
| **`sharp-shimmerless`** | **50** | **1** | **0** | **LINEAR** | **65.9%** |
| `sharp-shimmerless-grid` | 161 | 1 | 0 | LINEAR | 83.0% |
| `pixel-perfect` | 112 | 4 | 0 | NEAREST | 74.8% |

1024x768 from 320x240, worst per-case IQR 0.5%. It is the cheapest thing in the repo
on every axis at once, and **the output is the same picture**: 1/255 against both
`pixellate` (g=0) and `pixel-perfect` over twelve scales and four sources, byte-equal
block-width histograms (`{2: 95, 3: 63, 4: 159}` at 3.2x), the same 256 transition
pixels per row, and the same beat.

So the rejection stands on two things, and neither is speed:

- **It leans on the texture unit's subtexel precision, which is a fixed-point ladder
  with no GL query.** `equivalence.py:subtexel_bits()` measures it directly — sweep one
  texel spacing of a two-texel LINEAR texture holding 0 and 1, into a **float32**
  target, and count distinct values. This Apple GPU: **257 = exactly 8 bits**, which an
  8-bit output cannot distinguish from exact. A coarser interpolator bands every soft
  transition pixel and nothing here would see it; only the Mali settles it. Render the
  probe to 8-bit and it reports every GPU as perfect, which is why it does not.
- **It fails silently under the wrong sampler.** A four-tap shader under LINEAR is
  merely filtered twice; a one-tap shader under NEAREST snaps its carefully placed tap
  back to a texel centre and becomes **nearest-neighbour** — 256 transition pixels per
  row to **0**, 102/255 against the correct output, with nothing in the frame to say
  so. Beat goes 0.05 → 3.56 at 3.2x and 0.35 → 17.7 at 480x272 → 640x480.

One thing the comparison settles that the SFU/ops argument does not: **taps and
transcendentals do not decide moire, the gamma round-trip does.** One tap and four tap
measure identically; `pixellate`'s own default mode is 3.5–5.7 against their 0.000.
`sharp-shimmerless` has no knob to get that wrong because it has **no parameters at
all** — which is also why it cannot be the shader this repo ships.

## An affine grade is free after the blend; only the clamp and the gamma cost

`pixel-perfect-v3` drops `pp_sharpness` and spends the space on a colour grade. Both
halves of that took measuring.

**`pp_sharpness` only ever undoes the shader.** It scales the half-footprint, so below
1.00 the footprint stops covering the output pixel and the area average degrades toward
nearest-neighbour — which is the uneven, crawling blocks the shader exists to remove.
`equivalence.py` shows it directly: transition pixels per row at 320x240 → 1024x768 go
256, 256, 128, 128, 0 as it drops 1.00 → 0.20. A knob whose entire range is a slide back
into the fault is not a tuning control, so v3 pins it at 1.00 and removes it.

**Brightness, contrast and saturation may sit after the blend, and this is not an
exception to the design rule — it is the rule's converse.** What the rule forbids is a
*non-linearity* after the blend, because that gives partial-coverage pixels a
coverage-dependent shift. An affine map has no such shift: the scaler's weights sum to
1, so

    A·(Σ wᵢ xᵢ) + B  ==  Σ wᵢ (A·xᵢ + B)

and post-blend is *identical* to per-tap, at a quarter of the cost. Gain is affine,
contrast about mid grey is affine, and saturation is a linear operator (`mix` toward a
luma dot product). Measured on 1px checkerboards, worst over five scales, with the share
of the frame that meets the clamp alongside:

| | mono | chroma | clips |
|---|---|---|---|
| neutral (the defaults) | 0.349 | 0.116 | 0.0% |
| `pp_saturation` 0.00 | 0.349 | 0.244 | 0.0% |
| `pp_contrast` 0.40 | 0.178 | 0.134 | 0.0% |
| `pp_brightness` 0.60 | 0.209 | 0.070 | 0.0% |
| `pp_saturation` 1.80 | 0.349 | 1.042 | 100% |
| `pp_contrast` 1.60 | 3.916 | 1.305 | 100% |
| `pp_brightness` 2.00 | 32.67 | 32.67 | 50% |
| `pp_gamma` 0.70 | 8.031 | 8.009 | 0.0% |
| `pp_gamma` 1.40 | 8.705 | 8.681 | 0.0% |

**Beat tracks the clip column and nothing else.** Every 0% row sits at or *below* the
neutral floor however far from 1 the control is pushed — which is the falsifiable form
of the claim, and the reason `report_grade()` prints the clip share next to the beat
rather than the beat alone. The 0.349 floor is the scaler's own at its worst scale
(480x272 → 640x480); at 320x240 → 1024x768 it is 0.031, the figure recorded for
`pixel-perfect` elsewhere in this file.

Two traps in measuring it:

- **A black-and-white checkerboard cannot exercise a saturation control.** On grey,
  luma equals every channel and the mix is a no-op, so a completely broken saturation
  measures perfect. The chroma row is a red/cyan 1px checker — the same worst case one
  axis over — and it is the only column in which the saturation rows say anything.
- **`pp_gamma` is not a v3 regression.** Its figures are *bit-identical* to
  `pixel-perfect-v2`'s at every scale, because it is the same post-blend placement.
  What is new is measuring it on the same yardstick as everything else, where it turns
  out to be far the most expensive control in the shader — around 20× the visible
  threshold on dense content, against 0.03 with it off. The cheap placement was kept
  deliberately (one `pow`, 6 SFU, against 24 for the four taps); putting it on the taps
  the way `crt-perfect-v5` does would fit the budget and is the obvious next iteration
  if the cost is judged too high.

**Fold the three affine controls into one map; do not write them as three steps.**
The composition is `col*(ga*s) + dot(col, LUMA)*(ga*(1-s)) + gb`, where `ga =
brightness*contrast` and `gb = 0.5*(1-contrast)`, using the fact that the luma weights
sum to 1. It is one dot and one fma — but the reason it matters is exactness, not cost:
at the defaults it is `col*1.0 + 0.0`, which is bit-exact, where the literal chain is
not. `(x - 0.5)` rounds for small x so the contrast round trip does not return x, and
`mix(l, col, 1.0)` is only exactly `col` if the driver spells `mix` as `x*(1-a) + y*a`
rather than as `x + a*(y-x)`. GLSL guarantees the former; drivers ship the latter.

That exactness is worth having because it makes "off" checkable: **v3 at its defaults is
bit-identical (0/255) to `pixel-perfect.glsl` at every scale in `equivalence.py`'s
matrix**, on noise, checkerboard, grid and ramp sources. A grade that claims to be
neutral at unity should be provably neutral, not nearly.

Note the declaration order (`pp_saturation`, `pp_contrast`, `pp_brightness`, `pp_gamma`,
per the "brightness then gamma last" rule) deliberately differs from the evaluation
order (brightness → contrast → saturation → gamma). The fold makes the evaluation order
invisible in the code, so it is stated in the comment there.

### Making it free when it is off, and what that cost to measure

`pixel-perfect-v4` is v3 with the affine block and its clamp behind one uniform guard,
the way `pp_gamma` already was. Measured by removing each block and recompiling: the
affine block is **32 instructions**, the gamma block 16 plus 6 SFU lanes.

**Compare the three controls separately and exactly.** Two forms were rejected:

- `abs(b + k + s - 3.0) > eps` is **wrong**, not merely worse — brightness 1.1 with
  contrast 0.9 sums to exactly 3.0, so a real grade is dropped without a trace.
- summing the absolute deviations is correct but costs 17 instructions against 13 for
  three exact comparisons, *and* it opens a dead band in which v4 and v3 disagree.

**An epsilon here would have been cargo-culted from the gamma guard.** That one needs a
dead band for an accuracy reason: `pow(x, 1.0)` is `exp2(log2(x))` on a GPU and rounds,
so a gamma of 1.0 is not otherwise a no-op. The affine block at 1.00 is `col*1.0 + 0.0`,
which is exact — nothing to protect against, so exact comparison is both cheaper and
strictly equivalent. Check which of those two situations applies before copying a guard.

### `spirv_cost.py` counts both arms of a branch, so it reported v4 as a regression

The static count walks every instruction regardless of control flow. v4 reads **174**
against v3's 161 while executing far less, which is exactly backwards, and quoting it
would have buried the change. The tool now also compiles each shader through
`spirv-opt` twice — once with the parameters live, once with `PARAMETER_UNIFORM`
undefined so each resolves to its `#define` fallback and the guards fold away:

| | ops | live | at defaults | SFU at defaults |
|---|---|---|---|---|
| `pixel-perfect.glsl` | 112 | 106 | 104 | 0 |
| `pixel-perfect-v2.glsl` | 131 | 124 | 109 | 0 |
| `pixel-perfect-v3.glsl` | 161 | 152 | 123 | 0 |
| **`pixel-perfect-v4.glsl`** | 174 | 165 | **111** | 0 |
| `crt-perfect.glsl` | 501 | 459 | 403 | **8**, from 14 |
| `lcd-perfect.glsl` | 434 | 397 | 343 | **15**, from 39 |
| `dmg-perfect-v3.glsl` | 459 | 445 | **265** | 0 |
| `pixellate.glsl` | 292 | 254 | 240 | 30 |

**The `at defaults` column understates an explicit guard, and that is the trap in it.**
With the parameters as literals the optimiser also folds arithmetic that is merely
neutral — v3's `col*1.0 + 0.0` collapses although v3 has no guard at all — and no
runtime can do that with live uniforms. So it is a *lower* bound on what a guard buys:
v4 reads 12 ops better than v3 there, where the runtime gap is nearer 19. Safe direction
to be wrong in, but do not quote it as the saving.

The unoptimised `ops` column is deliberately left alone: every cost figure recorded in
this file is in those units, and re-basing them would invalidate the lot.

### A branch after the blend perturbs the blend, and it is not a bug

v4 is **1/255 from v3 on 0.02% of pixels**, not bit-identical, and the reason is worth
knowing because any future guard added after the scaler will do the same.

The cause is not the grade. `equivalence.py` compiles a control: the same shader with
its condition replaced by `OutputSize.x < 0.0`, which can never be true and which the
driver cannot fold away. That control **reproduces v4's divergence exactly**, and every
differing pixel is a transition pixel — one whose blend weights are strictly between 0
and 1, which is the only place the blend does arithmetic at all. Putting any branch
after the blend changes which floating-point contractions the driver picks for the
blend itself.

So v3 and v4 are the same computation rounded two ways, and `gl_check` scores both at
1/255 against the float64 model — neither is the more correct one. The gate is
`<= 1` **plus** the control agreeing and the divergence staying on transition pixels;
a bare tolerance of 1 would have hidden a real logic error of the same size.

**Three claims, three different bars, and they are not interchangeable:**

| | bar | why |
|---|---|---|
| `pixel-perfect` vs `pixellate` | 1/255 | a different formulation of the same maths |
| v3 at defaults vs `pixel-perfect` | **0/255** | the same code path; the grade folds exactly |
| v4 vs v3 | 1/255 + control | same computation, different contraction |

The middle one was asserted at `== 0` for `pixellate` too when the gate was first
written, which is simply not true of it, and `equivalence.py` shipped exiting 1 for a
commit before anyone noticed — because the exit code was being read through a pipe, so
`$?` was `tail`'s status and not the tool's. **Read `PIPESTATUS`, or do not pipe.**

### `#define` fallbacks can disagree with `#pragma` defaults

The `at defaults` column trusts each parameter's `#define` fallback, so `check_headers.py`
now verifies it matches that parameter's `#pragma` default. Three shaders failed when
the check was added, and the first was shipped:

| shader | parameter | `#pragma` | stale `#define` |
|---|---|---|---|
| `lcd-perfect.glsl` — **fixed** | `lp_grid` | 0.30 | 0.34 |
| `lcd-perfect.glsl` — **fixed** | `lp_balance` | 0.50 | 0.79 |
| `lcd-perfect.glsl` — **fixed** | `lp_brightness` | 1.20 | 1.00 |
| `crt-perfect-v8/v9.glsl` | `cp_scanlines` | 0.60 | 0.55 |
| `crt-perfect-v8/v9.glsl` | `cp_rgb_mask` | 0.20 | 0.40 |

`lcd-perfect`'s were the **pre-retune values**, left behind when the defaults were tuned
in the `#pragma` block and nowhere else — 0.79 is exactly the balance that matched
lcd1x's white-field figures before the render showed 0.50 read better. A host that does
not parse `#pragma parameter` renders the `#define` values, so the shader shipped one
look and documented another, and that class of host is already on the record elsewhere
in this file.

**A default lives in three places here and nothing used to tie them together**: the
`#pragma` line, the `#define` fallback, and the model's `DEFAULTS_*` dict. The model
had been retuned along with the `#pragma`, which is why `gl_check` stayed green
throughout — it passes the registry's defaults explicitly and compiles with
`PARAMETER_UNIFORM` defined, so it never reads the fallback at all. **No existing gate
could see this.** That is the argument for the check, not the two levels of grid it cost.

It is a **warning, not a failure**, because two shaders still fail and both are
in-flight. Fix `crt-perfect-v8/v9`, then move it into `check()` — a warning nobody
promotes is a warning that rots.

## Measurement traps

Three tooling bugs produced confident, wrong numbers before being caught. Sanity-check
a metric before trusting it — verify it returns ~0 for a known-good case and that its
numbers scale sensibly.

- **Benchmark loop**: timing N draws with one `glFinish` at the end lets the driver
  coalesce them; cost per draw fell 8.6 → 4.8 µs as N grew from 100 to 1600. Per-draw
  GPU timer queries are required.
- **SPIR-V parser**: splitting on the *last* `OpFunction` reported "7 ops, 0 SFU" for a
  shader with helper functions. It must walk the call graph and expand helpers by call
  count.
- **Beat metric**: a fixed "periods 6–64px = moire" band counts the *pattern itself* as
  moire once its pitch or repeat length enters that band. Measure above each pattern's
  own repeat length (a pitch of k/4 repeats every k pixels).
- **Beat metric, second attempt**: low-passing with a box exactly one pattern repeat
  wide removes the beat *along with* the pattern — at a rational scale factor the whole
  image is periodic at that length, so nothing survives and everything reads 0.00,
  known-bad constructions included. `tools/beat.py` now bands explicitly: keep only
  what is slower than **half a cycle per source pixel**, which is below both the 1px
  checkerboard's own impulse and the pattern's fundamental, so whatever is left was
  manufactured by the shader.
- **Beat metric, band edge, twice**: the band has to duck under the *shader's*
  pattern, not just the content's, and the shader has to say where that is.
  v3 grows its period to a whole number of cells, which on a dense source puts
  it *below* the content - 0.28 against 0.375 at 480x272 into 640x480 - so a
  band that only cleared the content scored a correct mesh at 15.4, every
  dominant component sitting at exactly its own pitch with no structure in the
  other axis. `beat.py` now takes a `pattern` argument and `pattern_freq()`
  states the rule per shader, because the three rules in this repo disagree.
  A guard of 0.85 below it is needed on top: the pattern is not commensurate
  with the frame, so a rectangular window smears it with only 1/offset decay.
  A Hann window was tried and **wrecked the self-test** (ordering failed, ratio
  spread 172x); cropping to a whole number of periods just moves the leakage
  onto the content and lifts the clean floor sevenfold.
- **Beat metric, colour space**: measuring in linear light instead of code values
  *inverts* the ranking — 4.74 for the known-good baseline against 1.07 for the known-
  bad one. Measure encoded. This was checked rather than assumed, and the assumption
  would have been wrong.

`beat.py` self-tests against the table in *The one design rule* on every run. It
reproduces the ordering exactly at a consistent ~1.9× scale (spread 1.33×), so its
threshold is 0.4 rather than 0.2; the original tool was not in the repo and had to be
rebuilt from its description. A metric whose ratio to the record *drifts* per
construction is measuring something else and must not be trusted.

- **Beat metric, test source**: a full-range black-and-white checkerboard cannot
  see any fault that depends on the difference between white and *the panel's
  own undriven level*. dmg-perfect-v2's shadow dimmed three quarters of a real
  Game Boy frame and measured perfectly clean on this metric, because on a
  source whose light square is white the broken expression and the correct one
  are the same expression. Every beat figure taken before `dmg_checkerboard()`
  existed was correct and none of them could have caught it. **A test pattern
  chosen for maximum contrast is not neutral — it silently asserts that the
  content reaches white.**

- **Sampler state, not shader code**: every tool here rendered through
  `gl_render()`, which hardcoded NEAREST, because everything this repo *ships*
  needs NEAREST. A vendored one-tap shader does not — `sharp-shimmerless` and
  `sharp-shimmerless-grid` declare `filter_linear0 = true` in their own
  `.glslp`, and under NEAREST they degrade to nearest-neighbour rather than
  erroring. The `sharp-shimmerless-grid` row in the lcd comparison table was
  measured that way: **3.14 beat through the wrong sampler, 0.72 through the
  right one.** The number was not noise and not a bad metric, it was a correct
  measurement of a shader nobody runs. The sampler is now declared once, in
  `gl_check.LINEAR_SAMPLED`, and read by `preview.py`, `bench_glsl.py` and
  `equivalence.py`. **A comparison is only fair if each shader gets the pass
  state its own preset asks for; that state is part of the shader.**
- **An empty parameter dict is not "the defaults"**: `PARAMETER_UNIFORM` is
  defined, so a uniform nothing sets is 0. AGENTS.md already records this for
  `beat.py`, and `preview.py` was still doing it for vendored shaders —
  `VENDOR_PARAMS["pixellate.glsl"] = {}` silently selected
  `INTERPOLATE_IN_LINEAR_GAMMA = 0`, the mode `pixellate` does **not** ship in
  and the one without its gamma round-trip. Every preview was flattering the
  baseline by removing the single thing wrong with it. `gl_check.pragma_defaults()`
  now reads a shader's own declared defaults out of the file and `VENDOR_PARAMS`
  layers on top. **The same bug will keep recurring per tool; fix it where the
  file is read, not where the dict is written.**

Also: **a flip that preserves the picture still reverses a handed effect.**
`preview.py` fed the source flipped and flipped the result back. That pair is an
identity for *content*, so every screenshot came out the right way up and it
went unnoticed for the whole life of the tool — but the shader ran on a flipped
image, so anything with a direction came out mirrored in y. A grid, a scanline
and an RGB mask are all symmetric and cannot show it; the first handed effect in
the repo, dmg-perfect's cast shadow, rendered up-and-right through `preview.py`
and down-and-right through `gl_check.py` from the same shader and the same
parameters. `gl_render()` already returns rows in the source's order, so the
flips were never needed. **Verify an orientation convention against the harness
that indexes the model, not against whether the picture looks upright.**

Also: a shared constant between a model and several shaders is a trap. Widening
`STRIPE_FADE` in `lcd_preview.py` silently changed v1's model while v1's `.glsl` kept
the old window - `gl_check.py` catches it, but only if it is run over *every* shader
rather than the ones just edited. Per-variant constants, or run the whole gate.

Also: the desktop GL context is 4.1 Core, so ESSL-1.00 shaders do not run there. The
harness compiles them as `#version 410 core` via the compat macros; the device is the
only true target.

### A supersampled reference is itself a measurement, and it lies convincingly

`beat.py`'s `_supersampled()` builds ground truth by shooting `ss * ss` rays per output
pixel and taking the nearest texel for each. Each ray is a point sample, so a reference
built from `n` samples quantises to `1/n`, and on a 1px checkerboard — maximum contrast
between neighbours — that quantisation is enormous:

| rays per pixel | measured "shader error" |
|---|---|
| 2x2 | 16.18 |
| 4x4 | 8.00 |
| 8x8 | 3.82 |
| 16x16 | 1.88 |
| 32x32 | 0.91 |

**Halving on every doubling is the signature of a `1/ss` error in the reference**, and
none of it is the shader. Any single row of that table reads as a damning result — 8.00
against a visible threshold of 0.4 — and the curvature work briefly "found" exactly
that artifact before the convergence was checked.

The fix is to extrapolate the error away rather than sample it away: with `e = C/ss`,
two references at `ss` and `2*ss` give `2*r(2ss) - r(ss)` with the `C` term cancelled.
That reads **-0.06** where `ss=8` alone reads 3.82, and it is stable across which pair
is used — which is the check that the error model is right, not just convenient.

**Rule: never quote a number from a sampled reference without showing it converged.**

## LCD meshes: what v3 had to fix

- **A sinusoid does not band-limit itself.** The trapezoid aperture v1 used did -
  its coverage flattens on its own as cells shrink - so v2a dropped the Nyquist
  fade and the minimum pitch along with the trapezoid and nobody re-checked. A
  480x272 source then folded: 1.33 output pixels per cell at 640x480, below the
  two per cycle a pattern needs, measuring 5.9 against a threshold of 0.4. When
  the shape of a pattern changes, re-derive what band-limits it.
- **Grow the period, do not pin it.** crt-perfect pins its pattern to a fixed
  output-space pitch below `cp_min_pitch`. Copying that into a mesh made things
  worse, not better: a pattern that has stopped tracking the source interferes
  with the pixel blocks in *both* axes, and a 3px mesh over 2px blocks measured a
  real 12px beat. crt-perfect gets away with it because its horizontal pattern is
  a colour mask carrying no luminance, so its luminance pattern is
  one-dimensional and has nothing to interfere with in the other axis. Growing
  the period to a whole number of *cells* keeps the pattern exactly periodic on
  the source grid, so it cannot beat against it at all, and it kept the
  aperture-weighted blend working unchanged.
- **A column mesh and a stripe mask at the same pitch make a colour cast.**
  Whichever stripe lands on the mesh's dark line is dimmed, and swapping the
  stripe order swaps which one, so RGB and BGR cast in opposite directions -
  measured at 3.5 to 4.2 levels with a 3.5 to 5.3 flip between the two. It is
  divisible out in closed form, and two things have to be right or it overshoots
  to the opposite sign: the phase **cancels** between mesh and stripe and must
  not be subtracted a second time, and the correction must be **square-rooted**,
  because the `sqrt` that encodes the output halves any relative deviation on the
  way there. Applying it whole took green from 3 levels bright to 3.4 dark.
  crt-perfect never had this because a CRT mask has no column mesh to correlate
  with.
- **Aggregate swing figures and the look can disagree.** `lp_balance` 0.79 matches
  lcd1x on every white-field figure - column swing 90.2 against 90.0, ratio 4.00
  against 3.89 - while about 0.65 looks closer to its weave on a real frame,
  because lcd1x point-samples and its horizontal lines are sharper than a
  box-filtered one of the same measured swing. Render the frame before calling a
  look matched.

## Assumptions this session got wrong

Do not re-derive these.

- *"An RGB triad needs ≥3 output pixels."* False. 2.67px works because `8/3` is exactly
  periodic — 3 cycles span 8 pixels. The criterion is **exact periodicity on the pixel
  grid**, not absolute pitch. Any pitch of k/4 repeats every k pixels.
- *"A 2.0px pitch is unusable."* Only because of sample phase: centres land at 0.25 and
  0.75, symmetric about the beam peak, returning identical values. A half-pixel shift
  gives full contrast, and fixes every even-integer pitch.
- *"Only even-integer pitches lose contrast to sample phase."* False, and it cost a
  detour. **Every** integer pitch does, for a pattern whose dark part straddles the
  cell boundary — 3.0 measured 0.375 against a possible 0.75, 4.0 measured 0.500
  against 1.000. Moving the dark part wholly inside the cell fixes all of them and is
  cheaper than the shift.
- *"An exact box filter means nothing can alias."* False. A box filter is exact for the
  pixel it covers, but it is a weak *prefilter*: its response only falls as 1/f, so a
  hard-edged pattern's harmonics survive it and fold back. Exactness per pixel and
  band-limiting are different properties.
- *"The float32-vs-float64 gap between GPU and model can be engineered away."*
  Reducing coordinates to their cell before differencing, so rounding cancels, changed
  **not one pixel** — the error arrives in the interpolated texcoord, it is not created
  by the arithmetic. Two `floor`s for nothing; measure before optimising.
- *"`pow(cos, k)` is a single frequency."* Only when `k == 1`. Other exponents add
  harmonics, and harmonics alias before the fundamental does.
- *"Fading a pattern out near Nyquist is enough."* The fade must reach zero **at** 2
  output pixels per cycle, not at 1. Between 1 and 2 the pattern folds to a wrong,
  coarser pitch at near-full amplitude.
- *"The reference CRT overlays lock their pattern to the source pixels."* They do not.
  They use a fixed output-space pitch regardless of content resolution.
- *"A column of a comparison table reading 0.000 means that shader is clean."* It
  can equally mean the render was black. `PARAMETER_UNIFORM` uniforms default to
  0 when nothing sets them, so a shader fed no parameters renders at brightness
  0, and a black frame has no beat and no colour cast. Three columns of a
  comparison were flattering nonsense before that was noticed. Pass
  `REGISTRY[name].defaults`, and distrust an exactly-zero column.
- *"A test matrix covering the target resolutions covers the targets."* PSP
  480x272 was a stated target and was in neither `beat.py` nor `shaders.py`,
  which is why a visible pattern reached a device with every measurement here
  green. It is the hardest case in the set and it was the missing one.

## Reference measurements

The overlays these shaders were matched against are not redistributed here. Their
measured properties, on a white field:

| Overlay | Native | Pitch | Mean level | Scanline swing | Mask swing |
|---|---|---|---|---|---|
| "crt" | 640x480 | 3.00px → 160 lines, 213 triads | 88.8% | 66.5 | 13.3 |
| "240p" | 640x480 | 2.67px → 180 lines, 240 triads | 80.4% | 65.0 | 38.8 |
| crt-perfect defaults | — | — | 83.9% | 63.8 | 40.9 |

Both masks are luminance-neutral, which three primaries 120° apart reproduce exactly.

### LCD panels

Measured off a Game Boy Color, by `authentic_gbc/shared.inc` (pixel-counted from a
macro photograph) and independently by [gbcc.dev](https://gbcc.dev/technology/) under a
microscope. This is the only handheld panel either libretro repo has real numbers for
— GBA, DS and PSP geometry is assumed, not measured.

| | |
|---|---|
| subpixel width | 0.296 of the cell → **~3.7% column matrix** |
| subpixel height | 0.910 of the cell → **~9% row matrix** |
| net fill factor | ~75% |
| stripe order | RGB, left → right |
| pixel aspect | square — GBC, GBA, DS and PSP all are |

So the row matrix is ~2.4× the column matrix, which is why `lp_gap` drives the row gap
and scales the column gap by 0.4 rather than exposing two knobs. Cross-shader consensus
for defaults is 8–12% row matrix, 0–5% column, 25–35% edge darkening.

Note the GBC's primaries are nowhere near pure — pure red reads about `#FF7145` on
sRGB. A white-subpixel shader stacked on already colour-corrected output will look
wrong; that belongs in a colour pass, not here.

### What the LCD shaders being replaced measure

On a 1px checkerboard, 320x240 → 1024x768, white field for the swings:

| Shader | Beat | Mean level | Row swing | Col swing |
|---|---|---|---|---|
| `lcd1x` defaults | 1.87 | 75.3% | 24.0 | 96.0 |
| `lcd3x` | 2.93 | 82.3% | 68.6 | 5.8 |
| `sharp-shimmerless-grid` | 0.72 | 82.8% | 66.6 | 66.6 |
| `lcd-perfect` defaults | **0.24** | 82.5% | 57.6 | 36.2 |
| `crt-perfect` defaults | 0.26 | 83.9% | 63.8 | 40.9 |
| `pixel-perfect` | 0.03 | 100% | 0 | 0 |

The `sharp-shimmerless-grid` beat **was 3.14 here** and that figure was wrong: it was
rendered through NEAREST, which turns a one-tap scaler into nearest-neighbour. Its
three white-field columns are unaffected — a flat field blends to itself either way,
which is precisely why the error survived. Corrected it is still three times
`lcd-perfect`'s, on a grid that is column-and-row symmetric rather than shaped.

`lcd-perfect` sits below crt-perfect's own beat. `lcd-grid-v2` was researched and not
vendored: ~48 SFU slots against `pixellate`'s 30, so it is out of budget before any
discussion of how it looks.

`dmg-perfect` is not in that table because its swings are not comparable — its grid is
*lighter* than a lit pixel, so on a white field there is nothing to measure. Against
its own reference instead, at 160x144, on a flat field for the grid and a 1px
checkerboard for the beat. The CV column is the **lattice** part, with edge softness
already taken out, for the reason the metric section above gives:

| | Beat, GB → 1024x768 | Lattice CV, 1024x768 | Lattice CV, 640x480 | line px | ops | SFU |
|---|---|---|---|---|---|---|
| `dmg_dot_matrix` | 1.23 | 6.7% / 7.6% | 0.0% / 12.2% | 1.00 | 80 | 6 |
| `dmg-perfect-v1` | 0.12 | **0.0% / 0.0%** | **0.0% / 0.0%** | **1.98** | 265 | 6 |
| `dmg-perfect-v2` | 0.13 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 295 | 6 |
| `dmg-perfect-v3` | 0.13 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 295 | 6 |
| `dmg-perfect-v4` | 0.13 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 291 | 6 |
| **`dmg-perfect-v5`** | **0.13** | **0.1% / 0.3%** | **0.0% / 0.7%** | **1.05** | 291 | 6 |
| `dmg-perfect-v5` + shadow 0.45 | 0.29 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 489 | 6 |

v2 and v3 differ only in the shadow, so their geometry rows are the same figures
and the beat column, taken on a full-range checkerboard, cannot tell them apart
at all - see the test-source trap above. On a **DMG-palette** checkerboard with
the shadow at 0.35 the two separate cleanly, 0.69 against 0.32.

v1's zeroes are real and were bought at a price the numbers here do not show: it
forced every line to two output pixels, which is what made its grid read as heavy and
is why it was replaced. v2 is a tenth of a percent off an exact lattice and draws the
line the reference draws. **That is the whole lesson of the metric section — a column
of zeroes was the worse shader.**

Costs are the shadow-off path except where the row says otherwise; the shadow sits
behind a uniform branch, so the 463 is a static count and includes a fifth texture
fetch that no fragment pays for with the shadow off. SFU never moves off 6, a fifth
of `pixellate`'s 30, which is the number to trust on the Mali.

Set `dp_brightness` 1.20 and `dp_gamma` 1.40 and v2 is bit-identical to the reference
at every whole scale. Beat rises to 0.84 there, because most of what either shader
paints at those settings comes from that post-blend contrast curve — and turning it
off is free.

**The shadow is the expensive thing here, and not in instructions.** It is a one-sided
pattern locked to the cell boundary, which is the design rule's worst case, and it
costs beat roughly linearly in its opacity. Measured across 1024x768, 853x768, 640x480
and 533x480, worst of the four:

| `dp_shadow` | offset 0.5px | 1.0px | 1.5px | 2.5px |
|---|---|---|---|---|
| 0.15 | 0.23 | 0.38 | **0.21** | 0.31 |
| 0.25 | 0.33 | 0.61 | **0.34** | 0.51 |
| 0.35 | 0.44 | 0.82 | 0.47 | 0.73 |
| 0.50 | 0.60 | 1.18 | 0.68 | 1.05 |

So it is usable to about 0.20 and not beyond, which is why it defaults to off. Note
the **1.0px column is the worst at every opacity** — a one pixel lobe has no
guaranteed solid core, exactly as a one pixel line does not, so it wobbles cell to
cell. The default offset was 1.00 until this table was measured; it is 1.50 now.

## Deployment gotchas (NextUI / minarch targets)

- The host caches compiled programs at `SDCARD_PATH/.shadercache/<filename>.bin`, keyed
  on **filename only, no content hash**. A stale binary keeps running silently after an
  edit. Delete it on every copy.
- A preset resolves its shader by filename and **returns index 0 on no match** rather
  than erroring — so a preset naming a missing shader silently loads whichever shader
  sorts first. Copy the `.glsl` before selecting a preset that references it.
- Presets are not kept in this repo; each shader header documents the pass settings a
  host must provide.

## Related

- [RetroShader Lab](https://github.com/sinedied/retroshader-lab) — browser bench that
  ports the NextUI pipeline exactly (same pass sizing, uniforms, GLSL preprocessing).
  Much faster than a device for visual iteration.
  **Note:** its `AGENTS.md` still documents syncing shaders from `~/projects/NextUI`.
  Since crt-perfect now lives here, that path needs repointing to this repo.
- [NextUI](https://github.com/LoveRetro/NextUI) — the firmware these target. Pipeline
  semantics live in `workspace/all/common/generic_video.c` and
  `workspace/all/minarch/ma_config.c`.

## Commits

Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `perf:`. 
