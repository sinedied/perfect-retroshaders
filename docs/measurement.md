# measurement

Design record. Why this shader is built the way it is, what was
measured, and what was tried and rejected. AGENTS.md carries only what an agent
needs before touching anything; this is the detail behind it.

> **Tool names in this record are historical.** These notes were written against
> a harness of nine separate scripts, since consolidated into five entry points.
> The measurements are unchanged; only where they live moved. See the table in
> `docs/measurement.md`.


## Where the tools went

Nine scripts became five entry points. Nothing about how a thing is measured
changed; a few things stopped being measured at all.

| was | now |
|---|---|
| `beat.py`, `grid.py`, `measure.py` | `tools/measure.py` |
| `equivalence.py` | one metric in `tools/measure.py`, `against_pixellate()` |
| `bench_glsl.py`, `spirv_cost.py` | `tools/perf.py` |
| `validate_glsl.py`, `check_headers.py` | `tools/check.py` |
| `verify.py`, `tools/tests/*_test.py` | `tools/test.py`, `tools/tests/<family>.py` |
| `core/{paths,gpu,shader_source}.py` | `tools/common.py` |
| `core/manifest.py`, `models/registry.py` tables, `KNOWN_BEAT`, `LINEAR_SAMPLED` | `tools/baseline.toml` |
| `models/*.py`, `gl_check.py` | **gone** — see AGENTS.md on numpy twins |
| `twopass.py` | **gone** — a third DMG implementation; its conclusion is in `docs/dmg-perfect.md` |

`gl_check`'s job — catching a shader that does not compute what you think — is
now done by the scaler anchor (`tools/tests/contracts.py`) plus golden hashes.

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

- **An affinity test must not clip its own reference.** Checking that a
  post-blend affine map equals the per-tap one, by pre-mapping the source and
  rendering it back, reads **18/255** on a real Game Boy frame and looks like a
  broken shader. It is the test: pre-mapping clips each texel *before* the
  blend, while the shader blends and clips after, and a clip is exactly the
  non-linearity that does not commute. Constrain the source so the map cannot
  leave `[0,1]` - and assert it rather than hoping, since a DMG frame's darkest
  texel is 0.063 and maps to -0.218 at a gain of 1.3. Then it reads 1/255.
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

### The checkerboard is a worst case, and it is not a picture

`moire()` renders a 1px checkerboard because that is maximum energy at the source
pixel grid — the hardest input that exists for a scaler. That makes it the right
gate and the wrong estimate of what a player sees.

Measured while deciding whether to accept a `pow()` after the blend at the
`*-turbo` line's default brightness of 1.25, isolating the artifact exactly
(curve-after-blend minus curve-before-blend) at 1024x768:

| source | figure |
|---|---:|
| the metric's 1px checkerboard, band-limited | 4.169 |
| 18 real screenshots, RMS in levels | **1.50** |
| the same, 99th percentile | 7 |
| the same, worst pixel | 21 |
| PICO-8 at 128 → 768, an integer scale | **0.000** |

Two things follow, and both generalise beyond that one decision:

- **A band-limited figure and a level count are different units.** They order
  shaders the same way and do not convert. Quote the metric for the gate and a
  level count for the decision.
- **Real content is not flat at the pixel grid.** The artifact is confined to
  transition pixels, so a metric that fills the frame with transitions reports
  something no game reaches. That is not a reason to soften the gate — it is a
  reason to measure real frames before *accepting* a gate failure.

The integer-scale zero is the useful control: it is the mechanism confirming
itself, since every output pixel then has full coverage and nothing can beat.
Any number that does not vanish there is measuring something else.

**Raw `beat()` on a real screenshot is useless** — the metric band is full of
legitimate picture, reading 10 to 78 before a shader touches it. The artifact
has to be isolated by differencing against the correct construction, never read
off the shaded frame.

### Two shaders that look different can differ only in phase

Reported from a device: this repository's LCD mesh looks offset against `lcd1x`
and does not read as an exact grid. Both are sinusoids of period one source
pixel, and the whole difference is where the trough lands.

| flat white, integer ×4, % of own peak | px 0 | px 1 | px 2 | px 3 |
|---|---:|---:|---:|---:|
| `lcd1x`, trough on the source-pixel boundary | **70** | 100 | 100 | **70** |
| `lcd-perfect`, trough half an output pixel in | **73** | 89 | 100 | 89 |

`lcd1x` puts two samples either side of the trough and never reaches deeper than
cos(45°) = 0.707 of the sinusoid; `lcd-perfect` lands one sample exactly on it.
So `lcd1x` is the *deeper* pattern of the two (60% against 71% of peak on real
geometry) and still reads as the cleaner grid, because two of its four samples
sit near the flat top.

Two things generalise:

- **"Looks weaker" is not "is weaker".** Peak-to-trough said the opposite of
  what the eye said. What the eye was reading was how many samples per cycle sit
  near the peak, which is a sampling property, not an amplitude one.
- **A sample-phase result at one scale is not a result.** At a non-integer scale
  the phase drifts cycle to cycle: the same shader reads `73 88 100 94` in one
  cycle and `78 77 97 99` three cycles later. Any claim about "how many pixels
  are dark" has to name the scale, and at a non-integer one there is no fixed
  answer.

The underlying limit is worth stating once: **a sinusoid is below its peak for
three quarters of its cycle at any phase**, so no phase makes one draw a thin
line. A defined line needs a different waveform - an aperture with a duty cycle.
See `docs/lcd-perfect.md`.

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
| `dmg-perfect-v5` | 0.13 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 291 | 6 |
| `dmg-perfect-v5` + shadow 0.45 | 0.29 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 489 | 6 |
| `dmg-perfect-v6` + shadow 0.45 | 0.20 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 574 | 6 |
| `dmg-perfect-v7` + shadow 0.45 | 0.16 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 549 | 6 |
| **`dmg-perfect-v8`** | **0.13** | **0.1% / 0.3%** | **0.0% / 0.7%** | **1.05** | **262** | 6 |
| **`dmg-perfect-v8`** + shadow 0.45 | 0.23 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 511 | 6 |
| **`dmg-perfect-v9`** | **0.13** | **0.1% / 0.3%** | **0.0% / 0.7%** | **1.05** | **259** | 6 |
| **`dmg-perfect-v9`** + shadow 0.45 | 0.23 | 0.1% / 0.3% | 0.0% / 0.7% | 1.05 | 498 | 6 |

The geometry is identical from v2 on - every version since shares the same scaler
and the same aperture - so the only columns that move are the beat, which is the
shadow, and the cost. **The beat column cannot separate v6 from v7 from v8 by
enough to matter, and it is not what distinguishes them**: v7's fault is a
discontinuity in one term, which this metric is not built to see and which
measured *better* than v6 on two other metrics as well. See the smoothness-metric
section above. The ops column for v8 is the shadow-off path, which is what a
default frame pays.

v9 drops v8's contrast wheel and swaps three per-channel gains for a
temperature/tint pair, and **no measured column moves except the cost**: both
removed controls were exact no-ops at their defaults, so v9 hashes identically to
v8 on all ten golden cases. The 3 ops between them on the default path are the
contrast wheel's unbranched multiply-add, which was the one control here that
charged whether or not it was used.

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

## Crawl: four metrics that confidently said nothing was wrong

A scrolling colour moiré was reported from a device and reproduced. Getting a
number that agreed with the eye took five attempts, and the four failures are
worth more than the one that worked.

**The two blind spots that let it ship.** Every metric in `measure.py` took one
frame, and every metric converted to luminance on its first line. The artifact is
temporal and chromatic, so it was invisible twice over — not missed by a narrow
margin, but structurally outside what the harness could express.

**1. Beat, on a scrolled scene.** The obvious first move: run the existing
`beat()` at a series of scroll offsets and watch it change. It does not change —
0.0% across ten offsets for every shader, because a scene's own low-frequency
content is 92 levels and swamps a 1-level artifact. A metric dominated by the
content measures the content.

**2. A scrolling line.** Track one bright column across the screen and measure
how its centroid, energy and width wobble. Clean, direct, and it ranks our
shaders *better* than lcd1x on every column — 1.28% energy variation against
23%. True, and irrelevant: the defect is a large-scale field, and a single
feature cannot show a field.

**3. Pattern over content.** Divide the shader's output by the plain scaler's, on
the grounds that the pattern must be a function of screen position alone, so the
ratio must not depend on content phase. Also ranked ours better than lcd1x.
Random noise excites the wrong thing: it has energy everywhere, including the
band the artifact lives in, so the ratio is dominated by content that is not
there in a game.

**4. Per-pixel difference of compensated frames.** Shift each frame back by
exactly `scale x offset` — a Fourier shift, exact for a wrapped scroll — and
measure how much the picture still changes. This is the right idea and still
ranks lcd1x worst, because it counts every spatial frequency equally and lcd1x
point-samples its grid, so it shimmers at the pixel level. Nobody complains about
lcd1x. **What people see is a big slow band, and a metric that weights a 2-pixel
shimmer like a 60-pixel band is not measuring what anybody looks at.**

**What worked** is 4 with the same band the moire metric already uses — strictly
slower than both the content and the shader's own pattern — and with the plain
scaler's own figure subtracted in quadrature, because content moving a
non-integer number of output pixels cannot render identically twice and that
floor belongs to the scale, not the shader. It reads 0.00 at an integer scale,
0.00 for the plain scaler, and rises with the colour parameter.

**A fifth, rejected for a different reason.** Comparing the shader against its own
supersampled render is a sound *correctness* measure and a bad *crawl* measure:
it reads 3.05 at an integer 4x scale, where scrolling provably changes nothing at
all, because it also counts a static error that never moves. It is still the right
tool for asking whether a fix is possible — it is how the 0.319 ceiling in
`docs/lcd-perfect.md` was established — just not for gating.

**The vendor shaders are not a control here.** lcd1x scores high for a reason it
is entitled to: nearest-neighbour blocks are four pixels wide and then five, so
features genuinely change width as they scroll. That is the shimmer this repo's
scaler exists to remove, not the artifact under test. Wanting the number to rank
lcd1x last is what kept three of the four wrong metrics alive longer than they
deserved.

## Crawl, part two: the metric was right and its test source was wrong

The crawl metric found a real defect and then said the shipped shaders were
acceptable at the settings a user was actually running. They were not. Three
things were wrong with how it was applied, and none with the idea:

**The test source was too dark to clip.** The artifact turned out to be the
output clamp, which does not exist until the gain drives content past 1. On a
40–240 source the metric read 0.259 at the owner's settings and called them fine;
the same settings on a 150–255 source read 0.524 and reproduced the device report
exactly, including its brightness dependence and its absence at integer scales.
A metric whose test signal cannot reach the regime under test measures nothing
about it.

**It only scrolled horizontally.** A pattern modulated along one axis beats only
when the content moves along *that* axis — reported from the device before it was
measured here, and obvious in hindsight. A horizontal-only test cannot see a
scanline at all, which is exactly why `crt-perfect`'s version of the same bug was
missed.

**It ran at the shipped default.** The defect is a function of brightness, so it
has to be swept with the control turned up, the same reasoning that gives
`perf.py` its `MAXED` table. Measuring at the default called both shaders clean.

A fourth, subtler point: the sweep now measures **two regimes** rather than one
maximum, because two different defects live here and one parameter set cannot see
both. At the shipped pattern depth with brightness raised, the clamp dominates.
At full pattern depth with brightness neutral, what is left is the aperture
covariance error, whose fix was measured and rejected on cost. A single "turn
everything up" set reads the sum and cannot say which moved.

**And clipping suppresses the score.** Clipped pixels cannot vary, so a shader
that clips harder scores *better* on any frame-difference metric. That is why the
gate now measures at a fixed brightness rather than searching for a worst case:
the worst case by this metric is not the worst case by eye.


## A warp is not a pattern, and two gates cannot see it

`unflat-mini` bends the whole image and nothing else. It reads **33.892 of
moire against a limit of 0.40** at its shipped 0.07 curvature, and takes a lit
field to black in the corners - both while drawing precisely what it is meant
to draw.

Neither number is about the shader:

- **The moire band is derived from the source and output sizes**, which is the
  fix for the fixed-window bug recorded above. That derivation assumes the image
  is still on the pixel grid. A warp resamples it off the grid, so the band then
  measures the resampling - the very thing the shader exists to do.
- **The never-extinguishes contract** exists to catch a grid whose dark line
  lands exactly on a matrix line. The corner mask reaches black on purpose, and
  there is no grid.

So the declaration is `warps = true`, and it exempts the shader from both.
**Exempting the metric is the honest move; granting the shader a 33.892
allowance is not** - an allowance reads as a measured tolerance somebody
accepted, and nobody measured anything here. At `um_curvature = 0.00` the shader
is a pass-through, both gates apply normally, and the scaler anchor still holds
it to `pixel-perfect` within 1/255.
