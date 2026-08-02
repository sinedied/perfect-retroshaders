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

## What v2 changed

**Brightness pushes the midtones.** v1 shallowed the pattern instead, which
made brightness read as "less effect" rather than "brighter". It is now folded
into the gamma exponent, so the pair costs one `pow()`:

```glsl
if (abs(gamma - 1.0) > 0.001 || abs(brightness - 1.0) > 0.001)
    color = pow(max(color, 1e-8), vec3(gamma / max(brightness, 1e-3)));
```

It leaves 0 at 0 and 1 at 1, so nothing clips and the output clamp is never
reached. It is also a non-linearity after the blend, which is the design rule's
one prohibition — [what that costs is measured below](#the-midtone-exception),
along with the two-pass assembly that removes it entirely for 2% of a frame.

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
| `lcd-turbo` | one LINEAR tap, aperture-weighted **(67%)** → mesh **(2%)** → RGB stripes + cast correction **(29%)** → brightness · gamma **(2%)** |
| `lcd-mini` | one tap at 1:1 **(55%)** → mesh **(3%)** → RGB stripes + cast correction **(40%)** → brightness · gamma **(3%)** |
| `crt-turbo` | curvature **(19%)** → one LINEAR tap + pitch and band-limit setup **(73%)** → brightness · gamma **(2%)** → scanlines **(0.5%)** → RGB mask **(0.5%)**, slot variant **(+6%)** |
| `crt-mini` | curvature **(18%)** → one tap at 1:1 + band-limit setup **(73%)** → brightness · gamma **(2%)** → scanlines **(0.6%)** → RGB mask **(0.6%)**, slot variant **(+6%)** |

The grade block is one guard, so `pixel-turbo`'s and `colour-mini`'s three
colour rows are 29 ops between them, not 44.

Four things worth reading off it:

- **The patterns are nearly free; the scale and the band-limiting are the cost.**
  `crt-turbo`'s scanlines and mask are 2 ops each. Its 289-op floor is the pitch,
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
| `lcd-turbo`, defaults | 284 | 23 | 1 | 0.0585 | *10.7* | *115%* | ***64%*** |
| `lcd-turbo`, all on | 283 | 23 | 1 | — | *10.6* | *116%* | ***64%*** |
| `lcd-mini`, defaults | 218 | 19 | 1 | 0.0566 | *8.7* | *142%* | ***52%*** |
| `lcd-mini`, all on | 217 | 19 | 1 | — | *8.6* | *143%* | ***52%*** |
| `crt-turbo`, defaults | 301 | 14 | 1 | 0.0585 | *11.2* | *110%* | ***67%*** |
| `crt-turbo`, all on | 394 | 14 | 1 | — | *14.0* | *88%* | ***84%*** |
| `crt-mini`, defaults | 264 | 14 | 1 | 0.0588 | *10.1* | *122%* | ***60%*** |
| `crt-mini`, all on | 345 | 14 | 1 | — | *12.5* | *98%* | ***75%*** |
| `pixel-perfect`, defaults | 112 | 0 | 4 | 0.0538 | **6.7** | **183%** | **40%** |
| `dmg-perfect`, defaults | 267 | 6 | 8 | 0.0591 | **14.6** | **84%** | **88%** |
| `lcd-perfect`, defaults | 334 | 17 | 4 | 0.0631 | **15.0** | **82%** | **90%** |
| `crt-perfect`, defaults | 428 | 8 | 4 | 0.0663 | **15.9** | **77%** | **96%** |

Bold device figures are measured; *italic* ones are predicted. Worst desktop
per-case IQR was 33.9%, so the desktop column separates almost nothing here and
is included only to show that it does not contradict the ordering.

- **Every shader is under the 75% target at its shipped defaults**, and the
  three panel shaders roughly halve their released counterpart.
- **`crt-turbo` with everything on is 84%, over target.** That row is curvature
  at 0.15 — the one setting that provably breaks the budget, which is why it
  ships at 0. Everything else maxed is 67%.
- **`lcd`'s "all on" is one op cheaper than its default.** Not a mistake: with
  the parameters folded as literals the optimiser removes more from the maxed
  build than the extra work adds. Read it as "the lcd patterns cost nothing to
  turn up".

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
| `lcd-turbo` | **1.860** | 1.220 | 0.872 | 3.253 | 22/255 |
| `lcd-perfect` v8 | 0.158 | 1.886 | 1.001 | 3.922 | — |
| `crt-turbo` | **4.169** | *32.353* | 0.962 | 4.328 | 22/255 |
| `crt-perfect` v12 | 0.494 | *32.216* | 1.111 | 4.925 | — |
| `colour-mini` | 0.182 | 2.005 | 0.021 | 0.571 | — |
| `dmg-mini` | 0.435 | 1.485 | 0.161 | 1.711 | — |
| `lcd-mini` | 0.406 | 0.990 | 0.714 | 2.944 | — |
| `crt-mini` | **0.977** | *18.617* | 0.814 | 4.235 | — |

Reading it:

- **The bold moiré figures are the midtone exception**, and only that. They are
  zero at brightness 1.00; the defaults ship at 1.25. See below.
- **`vs ref` is 1/255 for `pixel-turbo`** — the one-tap scale *is* the four-tap
  scale. `lcd-turbo` and `crt-turbo` read 22/255 at their 1.25 default and
  **1/255 at brightness 1.00**, so the whole difference is the brightness
  reformulation: a level shift with no structure, RMS 5 over the frame.
- **`dmg-turbo`'s 73/255 is edge-localised**: RMS 1.05, and 0.8% of pixels
  differ by more than 4. It is a sub-pixel shift of the dot grid at 2.13x, not a
  different picture, and it is unchanged from v1.
- ***The italic "all on" crt figures are a measurement artifact, not a defect.***
  "All on" includes curvature 0.15, and `docs/measurement.md` records that a
  row-mean metric is invalid on a warped image. `crt-perfect` reads 32.216 on
  the same row.
- **`crt-mini` beats less than `crt-turbo`** (0.977 against 4.169) because
  standalone it has no box blend of its own — the frontend's bilinear upscale is
  smoother, so there is less structure for the curve to beat against.

## The midtone exception

**This is the largest quality decision in the project, and it is reversible in
one commit** by deleting the `moire_allow` blocks in `tools/baseline.toml` and
setting the brightness defaults to 1.00.

A `pow()` after the blend beats, and it beats in proportion to how far the
exponent is from 1. Measured on the scaler alone, worst moiré over the matrix
against a limit of 0.40:

| exponent | 1.00 | 0.95 | 0.90 | 0.85 | 0.80 | 0.70 |
|---|---:|---:|---:|---:|---:|---:|
| worst moiré | **0.044** | 1.215 | 2.510 | 3.888 | 5.317 | 8.019 |

Roughly linear in `|exponent − 1|`, with no usable region. **But the moiré
metric renders a 1px checkerboard** — maximum energy at the source pixel grid,
the worst case that exists — and real game content is nothing like it. Isolating
the artifact exactly (curve-after-blend minus curve-before-blend, at the shipped
brightness of 1.25, 1024x768) over the 18 real screenshots in
`retroshader-lab/public/samples`:

| route | RMS, levels | p99 | max | integer scale |
|---|---:|---:|---:|---:|
| **one pass** — curve after the blend | **1.50** | 7 | 21 | **0** |
| **two passes** — `colour-mini @src` in front of the scaler | **0.11** | 1 | 1 | **0** |

Read that as:

- The one-pass artifact is **1.5 levels RMS, confined to transition pixels**
  (99% of the frame is within 7 levels, and the max of 21 lands only on hard
  edges). It is a static error, not a crawl: the curve is a fixed function of
  the blended value, so it scrolls *with* the picture. `crawl` at defaults is
  0.962, against `crt-perfect`'s 1.111.
- It is **exactly zero at an integer scale** — both PICO-8 samples, at 128 →
  768, read 0.000. That is the mechanism confirming itself: every output pixel
  has full coverage, so there is nothing to beat against.
- **Grading in front of the scaler removes it**, leaving 0.11 RMS which is
  entirely the 8-bit intermediate render target rounding. This is legal by the
  design rule, because a curve applied at source resolution is per source pixel,
  exactly like the released line's per-tap clamp.

So there are two supported ways to raise brightness, and they cost about the
same:

| | passes | frame | moiré at defaults |
|---|---:|---:|---:|
| `lcd-turbo`, brightness 1.25 | 1 | *64%* | 1.860 |
| `colour-mini @src → pixel-turbo → lcd-mini`, brightness 1.25 in pass 1 | 3 | *66%* | 0.406 |

**One point of frame time buys the exception back.** The turbo line takes it so
that one shader is enough; the mini line exists so it does not have to be taken.

## Rejected, with the measurement

| Idea | Verdict |
|---|---|
| Cutting curvature and the slot mask (v1) | **Reverted.** They cost nothing when unselected: `crt-perfect-v12` is 449 ops with curvature present at 0 and 449 without the code at all; 449 with the slot mask unselected, 471 when chosen. Both are behind uniform guards. |
| Brightness by shallowing the pattern (v1) | **Replaced.** It does not beat, but it makes brightness read as "less effect", which is not what the control says. |
| Brightness as a gain on the blended colour | **Rejected.** 1.860 moiré against a limit of 0.40, and one tap cannot clamp per source pixel — the texture unit has already blended. This is the design rule doing exactly what it says. |
| Brightness as `min(pattern × b, 1)` | **Rejected.** Position-only, so it does not beat, but the knees crawl at 0.719 against a limit of 0.35. |
| Plain area blend in `lcd-turbo` instead of aperture weighting | **Rejected.** The mesh's dark line and the scaler's transition pixel both sit on the cell boundary, so they correlate: 1.890 moiré. Keeping the aperture weighting costs nothing in taps. |
| `smoothstep` pair for `crt`'s corner mask | **Replaced with a linear ramp.** `clamp(uv/e)*clamp((1-uv)/e)` is one output pixel wide either way; the tube outline is identical to `crt-perfect-v12` to the pixel on a flat source. |
| Hoisting uniform-derived setup into the vertex shader | **Not worth it.** Pinning the sizes to literals — perfect hoisting — removes 23 of `crt-turbo`'s ops (8%) and 6 of `lcd-turbo`'s (2%). The driver very likely already does it, and varyings cost interpolation. |
| A source-resolution grading pass (v1) | **Reinstated in v2** as `colour-mini @src`. v1 rejected it because pattern-shallowing avoided the clamp in one pass; with the midtone push it is the only clean route, and it measures 0.2 ms. |
| `mediump` / fp16 split | **Open, and unmeasurable here.** Rogue GE8300 has native fp16 ALU; every desktop GPU runs `mediump` at fp32 and will report no change. Needs a device run. The scale's `floor()` on a coordinate up to 480 must stay `highp`. |

## Next levers, in order

1. **`crt-turbo`'s 289-op floor.** The pitch, lock and Nyquist setup runs
   whether the patterns are on or off, and is 73% of the shader. The patterns
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
| `docs/optimized/crt-turbo.md` | curvature, the slot mask, and the 289-op floor |
| `docs/optimized/lcd-turbo.md` | the aperture blend, and four brightness formulations |
| `docs/optimized/dmg-turbo.md` | the shadow in one tap, and a measurement trap |
| `docs/optimized/mini.md` | the contract every mini shares, and what the split buys |
| `docs/optimized/colour-mini.md` | grading at source resolution, and what it costs |
| `docs/optimized/crt-mini.md` | curvature without a footprint |
| `docs/optimized/lcd-mini.md` | the one mini that gets structurally cheaper |
| `docs/optimized/dmg-mini.md` | two taps, and the golden path it has to beat |

The released line's records stay in `docs/`.

## The device run, when you want it

**Not run.** Every figure marked *italic* above is predicted.
`tools/device/build/ShaderBench.pak` needs rebuilding for v2 — ARM aarch64, 29
pipelines: the six already measured, the seven reference stacks, the four turbo
shaders, the four minis alone and eight assembled chains.

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
