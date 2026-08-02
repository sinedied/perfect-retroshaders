# The `*-turbo` and `*-mini` lines

The shipped shaders do not fit the device. Measured on the Brick at 320x240 →
1024x768, `crt-perfect` uses 96% of a 60fps frame on its own, `lcd-perfect` 90%
and `dmg-perfect` 88% — with no emulator underneath. Two new lines answer that,
and **the released shaders are not touched.**

| line | what it is | when to use it |
|---|---|---|
| `*-turbo` | the same four shaders, one pass, rebuilt around a single texture tap | you want one shader and the best picture per millisecond |
| `*-mini` | the pattern only, no scaler, composable behind anything | you want to pick your own scaler, or chain a source-resolution colour pass |

Target: **≤ 75% of a frame (12.5 ms) with every feature on.** Every shader in
both lines meets it; the one row that does not is `crt-turbo` with curvature at
its maximum, which is opt-in and off by default.

**Every device figure on this page is predicted, not measured.** See
[the device run](#the-device-run-when-you-want-it).

## What v3 changed

**Brightness is a plain gain again, and v2's "midtone push" was a mistake.**
`pow(colour, gamma / brightness)` divides the same exponent a gamma control
divides. It *is* gamma, under a second name, and shipping it as brightness was
wrong. v3 puts back what the released line has:

```glsl
if (brightness != 1.0)                       // crt, lcd
    color = min(color * brightness, 1.0);    // on the tap, before the pattern

float ga = pp_brightness * pp_contrast;      // pixel, colour: the folded affine
grade = (balance) * dp_brightness;           // dmg: into the balance factor
```

It is a gain on the **content only** — the pattern's depth is untouched — and
the clamp is the design rule's one prohibition, a non-linearity after the blend.
[What that costs is measured below](#the-brightness-exception), along with the
two-pass assembly that removes it entirely for 1% of a frame.

**`pixel-turbo` and `colour-mini` now need no exception at all.** With
brightness back in the folded affine they are `pixel-perfect`'s grading exactly,
on one tap instead of four: moiré 0.044 against a limit of 0.40.

**The two `*-perfect` iterations went back too.** `crt-perfect-v12` and
`lcd-perfect-v8` clamped brightness *per tap*, which is flat on every metric and
is genuinely the best formulation available — but the clamp lands on the content
before the pattern, so every highlight above `1/brightness` flattens to white
and the mask can no longer shape it. That reads as the slider bleaching the
picture rather than brightening it. `crt-perfect-v13` and `lcd-perfect-v9a` put
the released form back and take the crawl with it.

## What v2 changed, kept

**Curvature and the slot mask are back, because cutting them bought nothing.**
Measured on `crt-perfect-v12`: **449 ops with curvature present at 0**, and 449
without the code at all. **449 with the slot mask available but not selected**,
471 when it is. Both sit behind a uniform guard, so a driver takes the branch
once per draw rather than once per fragment. v1 removed them for no gain.

**The `*-mini` line splits the pattern from the scaler**, so a user can put a
different scaler in front, no scaler at all, or a colour pass at source
resolution. It is not primarily a speed change — see
[table 3](#3-what-a-chain-costs).

**`pixel-turbo` is `sharp-shimmerless`.** Not "close to": the two agree to
within 1/255 on every case in the matrix, and are byte-identical on most of
them. They are the same function written twice — a one-tap box filter — and
`pixel-turbo` adds brightness, contrast, saturation, gamma, temperature and tint
for **4 ops**. That also makes the reference-stack comparison exact: every
`shimmerless → X` row below can be read as `pixel-turbo → X`.

## 1. Process flow, and what each stage costs

Each stage is measured on its own, over the same shader with every effect
neutral, and quoted as a share of that shader's op count **with everything on**.
Stages that share a guarded block overlap, so a flow can sum past 100.

| Shader | Flow |
|---|---|
| `pixel-turbo` | one LINEAR tap **(65%)** → white balance **(20%)** → brightness · contrast · saturation, folded affine **(27%)** → gamma **(7%)** |
| `colour-mini` | one tap at 1:1 **(41%)** → white balance **(33%)** → brightness · contrast · saturation **(45%)** → gamma **(12%)** |
| `dmg-turbo` | one LINEAR tap **(51%)** → balance → dot aperture over substrate **(8%)** → cast shadow, +1 tap **(39%)** → brightness · gamma **(2%)** |
| `dmg-mini` | one tap at 1:1 **(47%)** → dot aperture **(8%)** → cast shadow, +1 tap **(42%)** → brightness · gamma **(2%)** |
| `lcd-turbo` | one LINEAR tap, aperture-weighted **(66%)** → mesh **(2%)** → RGB stripes + cast correction **(28%)** → brightness · gamma **(3%)** |
| `lcd-mini` | one tap at 1:1 **(54%)** → mesh **(3%)** → RGB stripes + cast correction **(38%)** → brightness · gamma **(3%)** |
| `crt-turbo` | curvature **(18%)** → one LINEAR tap + pitch and band-limit setup **(72%)** → brightness · gamma **(2%)** → scanlines **(0.5%)** → RGB mask **(0.5%)**, slot variant **(+5%)** |
| `crt-mini` | curvature **(17%)** → one tap at 1:1 + band-limit setup **(72%)** → brightness · gamma **(2%)** → scanlines **(0.6%)** → RGB mask **(0.6%)**, slot variant **(+6%)** |

The grade block is one guard, so `pixel-turbo`'s and `colour-mini`'s three
colour rows are 29 ops between them, not 44.

Four things worth reading off it:

- **The patterns are nearly free; the scale and the band-limiting are the cost.**
  `crt-turbo`'s scanlines and mask are 2 ops each. Its 291-op floor is the pitch,
  lock and Nyquist machinery, which sits outside the guards and runs whether the
  patterns are on or off. That is the next lever, not the patterns.
- **Curvature is 73 ops when selected and 0 when not.** It is the largest single
  effect in either line and costs nothing at the shipped default.
- **`dmg`'s shadow is the one expensive effect in the set** at 106 ops, and the
  only one still needing a second tap. It is off by default.
- **`lcd`'s stripe block is 82 ops**, most of it the cast correction, which is
  not optional — without it the stripes tint the picture.

## 2. Performance

`ops`, `SFU` and `tex` are deterministic, from SPIR-V with the parameters
folded. Desktop is an M4 Max and is compressed to near-noise — the render pass
around these shaders costs more than the shaders — so read the device column.

**Device figures for every `*-turbo` and `*-mini` row are PREDICTED**, from a
model fitted to the six measured rows in `device-results.tsv`:

```
frag_ms = -0.003 + 0.03056 * ops + 0.6712 * taps      r2 = 0.974, rms 0.755 ms
frame   = frag_ms + 1.329                             (measured, and flat in pass count)
```

| Shader | ops | SFU | tex | desktop ms | device ms | vs `pixellate` | frame |
|---|---:|---:|---:|---:|---:|---:|---:|
| `pixel-turbo`, defaults | 53 | 0 | 1 | 0.0493 | *3.6* | *340%* | ***22%*** |
| `pixel-turbo`, all on | 82 | 6 | 1 | — | *4.5* | *273%* | ***27%*** |
| `colour-mini`, defaults | 20 | 0 | 1 | 0.0493 | *2.6* | *472%* | ***16%*** |
| `colour-mini`, all on | 49 | 6 | 1 | — | *3.5* | *352%* | ***21%*** |
| `dmg-turbo`, defaults | 168 | 6 | 2 | 0.0538 | *7.8* | *158%* | ***47%*** |
| `dmg-turbo`, all on | 273 | 6 | 2 | — | *11.0* | *112%* | ***66%*** |
| `dmg-mini`, defaults | 148 | 6 | 2 | 0.0522 | *7.2* | *171%* | ***43%*** |
| `dmg-mini`, all on | 253 | 6 | 2 | — | *10.4* | *118%* | ***62%*** |
| `lcd-turbo`, defaults | 286 | 17 | 1 | 0.0585 | *10.7* | *115%* | ***64%*** |
| `lcd-turbo`, all on | 291 | 23 | 1 | — | *10.9* | *113%* | ***65%*** |
| `lcd-mini`, defaults | 220 | 13 | 1 | 0.0566 | *8.7* | *141%* | ***52%*** |
| `lcd-mini`, all on | 225 | 19 | 1 | — | *8.9* | *139%* | ***53%*** |
| `crt-turbo`, defaults | 303 | 8 | 1 | 0.0585 | *11.3* | *109%* | ***68%*** |
| `crt-turbo`, all on | 402 | 14 | 1 | — | *14.3* | *86%* | ***86%*** |
| `crt-mini`, defaults | 266 | 8 | 1 | 0.0588 | *10.1* | *121%* | ***61%*** |
| `crt-mini`, all on | 353 | 14 | 1 | — | *12.8* | *96%* | ***77%*** |
| `pixel-perfect`, defaults | 112 | 0 | 4 | 0.0538 | **6.7** | **183%** | **40%** |
| `dmg-perfect`, defaults | 267 | 6 | 8 | 0.0591 | **14.6** | **84%** | **88%** |
| `lcd-perfect`, defaults | 334 | 17 | 4 | 0.0631 | **15.0** | **82%** | **90%** |
| `crt-perfect`, defaults | 428 | 8 | 4 | 0.0663 | **15.9** | **77%** | **96%** |

Bold device figures are measured; *italic* ones are predicted. Worst desktop
per-case IQR was 33.9%, so the desktop column separates almost nothing here and
is included only to show that it does not contradict the ordering.

- **Every shader is under the 75% target at its shipped defaults.**
- **The brightness change cost 2 ops** on `crt` and `lcd` and none anywhere
  else, and it *saved* 6 SFU at the defaults: the guarded `pow` is gone at
  gamma 1.00, where v2's fused exponent kept it alive whenever brightness
  moved.
- **`crt-turbo` with everything on is 86%, over target.** That row is curvature
  at 0.15 — the one setting that provably breaks the budget, which is why it
  ships at 0. Everything else maxed is 68%.

### The unreleased `*-perfect` iterations

| Shader | ops | SFU | tex | device ms | frame |
|---|---:|---:|---:|---:|---:|
| `crt-perfect` v10, released | 428 | 8 | 4 | **15.9** | **96%** |
| `crt-perfect` v12, per-tap clamp | 449 | 8 | 4 | *16.6* | *100%* |
| **`crt-perfect` v13, head** | **428** | **8** | **4** | **15.9** | **96%** |
| `lcd-perfect` v6, released | 334 | 17 | 4 | **15.0** | **90%** |
| `lcd-perfect` v8, per-tap clamp | 351 | 17 | 4 | *15.5* | *93%* |
| **`lcd-perfect` v9a, head** | **338** | 17 | 4 | *15.1* | *91%* |
| `lcd-perfect` v9b, lcd1x phase | 336 | 17 | 4 | *15.1* | *91%* |
| `lcd-perfect` v9c, gap aperture | **432** | 12 | 4 | *18.0* | *108%* |

`crt-perfect-v13` is the released op count exactly — the per-tap clamp was
costing 21 ops as well as bleaching highlights. `lcd-perfect-v9a` is 4 over the
release, which is v8's stripe normalisation.

**`v9c` is 94 ops over `v9a`** and is the only shader in the repo over a whole
frame. Three `gapInt` evaluations replace the closed-form sinusoid integral, and
the stripes lose the sin/cos pair the mesh used to share with them. If that arm
wins, making it cheap is the follow-up — and it must be, before the waveform
could go anywhere near `lcd-turbo`.


## 3. What a chain costs

The mini line is meant to be assembled. A pass rendered at **source** resolution
(`upscale = 1`) covers 1/10 of the pixels at 320x240 → 1024x768, so its
per-fragment cost is scaled by that in the model.

| Stack | passes | ops | tex | device ms | frame | vs `pixellate` |
|---|---:|---:|---:|---:|---:|---:|
| `colour-mini` | 1 | 20 | 1 | *2.6* | *16%* | *472%* |
| `colour-mini @src → pixel-turbo` | 2 | 73 | 2 | *3.7* | *22%* | *329%* |
| `pixel-turbo → colour-mini` | 2 | 73 | 2 | *4.9* | *29%* | *251%* |
| `dmg-mini` | 1 | 148 | 2 | *7.2* | *43%* | *171%* |
| `pixel-turbo → dmg-mini` | 2 | 201 | 3 | *9.5* | *57%* | *130%* |
| `colour-mini @src → pixel-turbo → dmg-mini` | 3 | 221 | 4 | *9.6* | *58%* | *128%* |
| `lcd-mini` | 1 | 218 | 1 | *8.7* | *52%* | *142%* |
| `shimmerless → lcd-mini` | 2 | 267 | 2 | *10.8* | *65%* | *114%* |
| `pixel-turbo → lcd-mini` | 2 | 271 | 2 | *10.9* | *66%* | *112%* |
| `colour-mini @src → pixel-turbo → lcd-mini` | 3 | 291 | 3 | *11.1* | *66%* | *111%* |
| `crt-mini` | 1 | 264 | 1 | *10.1* | *60%* | *122%* |
| `pixel-turbo → crt-mini` | 2 | 317 | 2 | *12.4* | *74%* | *100%* |
| `colour-mini @src → pixel-turbo → crt-mini` | 3 | 337 | 3 | *12.5* | *75%* | *99%* |

**A source-resolution colour pass costs 0.2 ms — 1 point of frame time.** That
is the whole reason the `@src` rows exist, and it is what buys off the moiré
exception below.

**A chain is not cheaper than the single shader that does the same thing.**
`pixel-turbo → lcd-mini` is 66% against `lcd-turbo`'s 64%; `pixel-turbo →
crt-mini` is 74% against `crt-turbo`'s 67%. The mini line wins on *choice*, not
on the clock: a cheaper scaler, no scaler, or a colour pass in the right place.

### The reference stacks — what already works

What a user can assemble today from `tools/vendor/`, measured the same way.

| Stack | passes | ops | tex | device ms | frame | vs `pixellate` |
|---|---:|---:|---:|---:|---:|---:|
| `sharp-shimmerless` | 1 | 49 | 1 | *3.5* | *21%* | *353%* |
| `dmg_dot_matrix` | 1 | 78 | 1 | *4.4* | *26%* | *281%* |
| `shimmerless → lcd1x` | 2 | 96 | 2 | *5.6* | *34%* | *220%* |
| `shimmerless → scanlines` | 2 | 101 | 2 | *5.8* | *35%* | *214%* |
| `shimmerless → lcd3x` | 2 | 117 | 2 | *6.2* | *37%* | *197%* |
| `pixellate` | 1 | 240 | 4 | **12.3** | **74%** | **100%** |
| `pixellate → lcd3x` | 2 | 308 | 5 | **15.2** | **91%** | **81%** |
| `shimmerless → adjust` | 2 | 394 | 3 | *15.4* | *92%* | *80%* |
| `dmg_dot_matrix → adjust` | 2 | 423 | 3 | *16.3* | *98%* | *76%* |
| `shimmerless → lcd1x → adjust` | 3 | 441 | 4 | *17.5* | *105%* | *70%* |

**`image-adjustment` costs more than any shader in this repo.** At 345 ops and
2 taps it is ~11.9 ms on its own — 71% of a frame — which is what turns every
otherwise-cheap stack into one that does not fit. `colour-mini` does the same
job in 20 ops, and at source resolution in 0.2 ms.

The bare vendor stacks are cheaper than either of our lines. The moment grading
is added, they are not:

| golden path | frame | ours | frame |
|---|---:|---|---:|
| `shimmerless → lcd1x → adjust` | *105%* | `lcd-turbo` | ***64%*** |
| `dmg_dot_matrix → adjust` | *98%* | `dmg-turbo` | ***47%*** |
| `shimmerless → scanlines` + grading | *~92%+* | `crt-turbo` | ***67%*** |

And they do more: a real box-filtered scale, band-limited patterns that do not
beat at any scale, curvature, and grading, in one pass.

## 4. Visual quality against the released line

Worst case over the matrix, lower is better. `vs ref` is against the released
line's latest iteration; a mini shader has no scaler, so it has no counterpart
to compare against and the column is left blank.

| Shader | moiré, defaults | moiré, all on | crawl, defaults | crawl, all on | vs ref |
|---|---:|---:|---:|---:|---:|
| `pixel-turbo` | 0.044 | 5.784 | 0.051 | 1.908 | 1/255 |
| `pixel-perfect` v7 | 0.068 | 5.788 | 0.030 | 1.909 | — |
| `dmg-turbo` | 0.459 | 1.642 | 0.668 | 1.691 | 73/255 |
| `dmg-perfect` v10c | 0.485 | 1.698 | 0.664 | 1.698 | — |
| `lcd-turbo` | **3.400** | 2.205 | 0.879 | 2.976 | 27/255 |
| `lcd-perfect` v9a | 0.222 | — | 0.116 | — | — |
| `crt-turbo` | **7.256** | *33.057* | 1.001 | 4.513 | 27/255 |
| `crt-perfect` v13 | 0.334 | *32.216* | 0.093 | — | — |
| `colour-mini` | 0.182 | 2.005 | 0.021 | 0.571 | — |
| `dmg-mini` | 0.435 | 1.485 | 0.161 | 1.711 | — |
| `lcd-mini` | **1.062** | 1.427 | 0.646 | 2.993 | — |
| `crt-mini` | **1.275** | *23.228* | 0.724 | 4.437 | — |

Reading it:

- **The bold moiré figures are the brightness exception**, and only that. Every
  one is zero at brightness 1.00; `crt` and `lcd` ship at 1.25. See below.
- **They are worse than v2's** (1.860 lcd, 4.169 crt). That is the honest
  reading and it was expected: a clip has a harder edge than a curve, so it
  carries more energy into the beat band. v2 traded that for being gamma under
  another name, which is not a trade.
- **`pixel-turbo` and `colour-mini` need no exception at all.** With brightness
  back in the folded affine they are `pixel-perfect`'s grading exactly.
- **`vs ref` is 1/255 for `pixel-turbo`** — the one-tap scale *is* the four-tap
  scale, at every setting now rather than only at brightness 1.00.
- **`lcd-turbo` and `crt-turbo` are 1/255 from their `*-perfect` counterparts at
  brightness 1.00 and 27/255 at the 1.25 default.** That gap is deliberate and
  is where the two lines part: the four-tap line multiplies brightness into the
  *pattern*, so it brightens the effect too; the one-tap line gains the
  *content* and leaves the pattern's depth alone. Neither is the other's bug.
- **`dmg-turbo`'s 73/255 is edge-localised**: RMS 1.05, and 0.8% of pixels
  differ by more than 4. It is a sub-pixel shift of the dot grid at 2.13x, not a
  different picture, and it is unchanged from v1.
- ***The italic "all on" crt figures are a measurement artifact, not a defect.***
  "All on" includes curvature 0.15, and `docs/measurement.md` records that a
  row-mean metric is invalid on a warped image. `crt-perfect` reads 32.216 on
  the same row.
- **The mini shaders beat less than their turbo** (1.275 against 7.256 on crt)
  because standalone they have no box blend of their own — the frontend's
  bilinear upscale is smoother, so there is less structure for the clip to beat
  against.

## The brightness exception

**This is the largest quality decision in the project, and it is reversible in
one commit** by deleting the `moire_allow` blocks in `tools/baseline.toml` and
setting the brightness defaults to 1.00.

There are exactly three ways to give a shader a brightness control, and all
three were built and measured. Worst over the case matrix, at three settings;
limits are 0.35 crawl and 0.40 moiré:

| shader | form | crawl @1.25 | crawl @2.0 | moiré @1.25 | moiré @2.0 |
|---|---|---:|---:|---:|---:|
| `lcd-perfect` v6 / **v9a** | gain on the blend, clamped | 0.222 | **0.541** | 0.432 | 3.291 |
| `lcd-perfect` v8 | gain per tap, clamped there | 0.065 | 0.062 | 0.158 | 0.158 |
| `lcd-turbo` v2 | folded into the gamma exponent | 0.063 | 0.061 | **1.860** | 5.236 |
| `crt-perfect` v10 / **v13** | gain on the blend, clamped | 0.295 | **1.496** | 0.466 | 7.347 |
| `crt-perfect` v12 | gain per tap, clamped there | 0.094 | 0.077 | 0.494 | 0.494 |
| `crt-turbo` v2 | folded into the gamma exponent | 0.101 | 0.107 | **4.169** | 11.248 |

- **The per-tap clamp is strictly the best of the three on the numbers**, and it
  is flat in brightness on both metrics. It is also the one that was rejected in
  use, and rightly: the clamp lands on the *content*, before the pattern, so
  every highlight above `1/brightness` flattens to white and the mask can no
  longer shape it. The slider bleaches rather than brightens. Numbers cannot see
  that; a person can.
- **The gamma fold is not a brightness control.** `pow(c, g/b)` divides the same
  exponent `pow(c, g)` divides. It was shipped in v2 as "pushing the midtones"
  and that description was wrong.
- **So v3 ships the gain**, and takes the crawl and the beat with it. At the
  shipped 1.25 the crawl is *inside* the limit — 0.222 lcd and 0.295 crt — and
  it is raising brightness further that breaks it.

**Two things bound how bad this is.** The moiré metric renders a 1px
checkerboard, maximum energy at the source pixel grid, which no game reaches;
and the whole effect vanishes at an integer scale, because every output pixel
then has full coverage and there is nothing to beat against. Both PICO-8
samples, at 128 → 768, measure exactly 0.

**And there is a supported way to have brightness with no exception at all:**
put `colour-mini` at *source* resolution in front of the scaler. Applied per
source pixel a gain is legal, exactly like the released line's per-tap clamp,
and the pass costs 0.2 ms:

| | passes | frame | moiré at defaults |
|---|---:|---:|---:|
| `lcd-turbo`, brightness 1.25 | 1 | *64%* | 3.400 |
| `colour-mini @src → pixel-turbo → lcd-mini`, brightness 1.25 in pass 1 | 3 | *66%* | 1.062 |

**One point of frame time buys most of the exception back.** The turbo line
takes it so that one shader is enough; the mini line exists so it does not have
to be taken.

## Rejected, with the measurement

| Idea | Verdict |
|---|---|
| Cutting curvature and the slot mask (v1) | **Reverted.** They cost nothing when unselected: `crt-perfect-v12` is 449 ops with curvature present at 0 and 449 without the code at all; 449 with the slot mask unselected, 471 when chosen. Both are behind uniform guards. |
| Brightness by shallowing the pattern (v1) | **Replaced.** It does not beat, but it makes brightness read as "less effect", which is not what the control says. |
| Brightness folded into the gamma exponent (v2) | **Withdrawn, and it was a mistake to ship.** `pow(c, g/b)` divides the exponent `pow(c, g)` divides: it is gamma with a second name, not a second control. It should have been said when it was proposed. |
| Brightness clamped per tap (`crt-perfect-v12`, `lcd-perfect-v8`) | **Best on the numbers, rejected in use.** Flat in brightness on both metrics — 0.062 crawl against 0.541 at brightness 2.0. But the clamp lands on the content before the pattern, so every highlight above `1/b` flattens to white and the mask cannot shape it. The slider bleaches instead of brightening. |
| Brightness as `min(pattern × b, 1)` | **Rejected.** Position-only, so it does not beat, but the knees crawl at 0.719 against a limit of 0.35. |
| Plain area blend in `lcd-turbo` instead of aperture weighting | **Rejected.** The mesh's dark line and the scaler's transition pixel both sit on the cell boundary, so they correlate: 1.890 moiré. Keeping the aperture weighting costs nothing in taps. |
| `smoothstep` pair for `crt`'s corner mask | **Replaced with a linear ramp.** `clamp(uv/e)*clamp((1-uv)/e)` is one output pixel wide either way; the tube outline is identical to `crt-perfect-v12` to the pixel on a flat source. |
| Hoisting uniform-derived setup into the vertex shader | **Not worth it.** Pinning the sizes to literals — perfect hoisting — removes 23 of `crt-turbo`'s ops (8%) and 6 of `lcd-turbo`'s (2%). The driver very likely already does it, and varyings cost interpolation. |
| A source-resolution grading pass (v1) | **Reinstated in v2** as `colour-mini @src`, and it matters more in v3: with a plain gain it is the only route to brightness with no exception at all. Measures 0.2 ms. |
| The lcd grid's half-output-pixel phase | **Kept, with an alternative built.** It lands a sample on the sinusoid's trough, which is what stops every integer pitch losing contrast to sample phase. `lcd-perfect-v9b` phases it on the source-pixel boundary as `lcd1x` does, and `v9c` replaces the sinusoid with a gap aperture. See `docs/lcd-perfect.md`. |
| `mediump` / fp16 split | **Open, and unmeasurable here.** Rogue GE8300 has native fp16 ALU; every desktop GPU runs `mediump` at fp32 and will report no change. Needs a device run. The scale's `floor()` on a coordinate up to 480 must stay `highp`. |

## Next levers, in order

1. **`crt-turbo`'s 291-op floor.** The pitch, lock and Nyquist setup runs
   whether the patterns are on or off, and is 72% of the shader. The patterns
   themselves are 4 ops.
2. **`lcd`'s stripe block**, 88% of that shader's effect budget, most of it the
   cast correction — which is non-negotiable, so it needs a cheaper form rather
   than removal.
3. **`mediump`**, once there is a device run to measure it on.

## Running it

```sh
.venv/bin/python tools/test.py crt-turbo        # the gate, one family
.venv/bin/python tools/test.py crt-mini
.venv/bin/python tools/perf.py --cost --static  # the per-effect breakdown
.venv/bin/python tools/preview.py --diff        # look at it
```

Per-shader design records:

| | |
|---|---|
| `docs/optimized/pixel-turbo.md` | the one-tap identity, and why it is `sharp-shimmerless` |
| `docs/optimized/crt-turbo.md` | curvature, the slot mask, and the 291-op floor |
| `docs/optimized/lcd-turbo.md` | the aperture blend, and five brightness formulations |
| `docs/optimized/dmg-turbo.md` | the shadow in one tap, and a measurement trap |
| `docs/optimized/mini.md` | the contract every mini shares, and what the split buys |
| `docs/optimized/colour-mini.md` | grading at source resolution, and what it costs |
| `docs/optimized/crt-mini.md` | curvature without a footprint |
| `docs/optimized/lcd-mini.md` | the one mini that gets structurally cheaper |
| `docs/optimized/dmg-mini.md` | two taps, and the golden path it has to beat |

The released line's records stay in `docs/` — `docs/crt-perfect.md` for v13 and
`docs/lcd-perfect.md` for the three v9 grid arms.

## The device run, when you want it

**Not run.** Every figure marked *italic* above is predicted.
`tools/device/build/ShaderBench.pak` is built and current — ARM aarch64, **47
pipelines**: the six already measured, the seven reference stacks, **every
iteration of both new lines** (turbo v1/v2/v3, mini v2/v3), the six unreleased
`*-perfect` iterations including all three grid arms, and nine assembled
chains. `MAX_PIPELINES` was raised from 32 to 64 to hold them.

Every iteration is there deliberately: a single number with nothing beside it
cannot show whether a change helped.

```sh
cd tools/device && make pak

cp -r tools/device/build/ShaderBench.pak /Volumes/<card>/Tools/tg5040/
# then launch ShaderBench from the device's Tools menu; the screen stays black
# for a couple of minutes, then results.tsv and log.txt appear next to it

# or over SSH, which is quicker to iterate on
scp -r tools/device/build/ShaderBench.pak root@<ip>:/mnt/SDCARD/Tools/tg5040/
ssh root@<ip> 'cd /mnt/SDCARD/Tools/tg5040/ShaderBench.pak && ./launch.sh'
```

Four things to check when the numbers come back:

- **Whether the cost model held on setup-heavy shaders.** It predicts each row
  from `ops` and `taps` alone, and none of the six fitted rows was 73% uniform
  setup the way `crt-turbo` is. If `crt-turbo` lands well under 11.2 ms, the
  "reduce the band-limit machinery" lever is worth less than it looks.
- **What a pass really costs.** The one 2-pass row measured so far showed no
  per-pass overhead at all, which is surprising even for a tile-based GPU. The
  mini chains give eleven more data points, including three 3-pass rows.
- **Whether a source-resolution pass is really 0.2 ms.** The whole
  moiré-exception escape hatch rests on it.
- **Whether the one-tap scale still matches at 1/255.** The scaler anchor sits
  exactly on the tolerance on this desktop, and Rogue's bilinear weights are
  narrower fixed-point. Half a level is invisible; the *gate* would fail. See
  `docs/optimized/pixel-turbo.md`.

`bench --self-test` also fails one check on a desktop GPU — the blended-repeat
probe, because the work is far smaller than the fixed cost around it. That is
pre-existing and documented in `docs/device-perf.md`; on the device all six pass.
