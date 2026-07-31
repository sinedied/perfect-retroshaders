# measurement

Design record. Why this shader is built the way it is, what was
measured, and what was tried and rejected. AGENTS.md carries only what an agent
needs before touching anything; this is the detail behind it.

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

The geometry is identical from v2 on - every version since shares the same scaler
and the same aperture - so the only columns that move are the beat, which is the
shadow, and the cost. **The beat column cannot separate v6 from v7 from v8 by
enough to matter, and it is not what distinguishes them**: v7's fault is a
discontinuity in one term, which this metric is not built to see and which
measured *better* than v6 on two other metrics as well. See the smoothness-metric
section above. The ops column for v8 is the shadow-off path, which is what a
default frame pays.

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
