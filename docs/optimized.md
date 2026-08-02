# The `*-turbo` line

The shipped shaders do not fit the device. Measured on the Brick at 320x240 →
1024x768, `crt-perfect` uses 96% of a 60fps frame on its own, `lcd-perfect` 90%
and `dmg-perfect` 88% — with no emulator underneath. `*-turbo` is a second line
of the same four shaders, built for the device. **The released shaders are not
touched.**

Target: **≤ 75% of a frame (12.5 ms) with every feature on.** All four meet it.

## What changed

**One LINEAR tap instead of four NEAREST ones.** The four-tap area average is
exactly reproducible in one bilinear fetch: with `B = floor(p + 0.5)` and `w`
the low-side weight, sampling at `(B + 0.5 - w) / TextureSize` makes the texture
unit compute the identical `mix`. It works for *any* separable weight pair, not
just an area average, so `lcd-turbo` keeps its aperture weighting too.

**The dmg shadow's caster luma is one tap.** `dot` is linear, so `mix` and `dot`
commute and the four-tap bilinear of lumas is the luma of one bilinear tap.
Exact, and it deletes the float32 cell-boundary knife edge the four-tap form
carried. `dmg` goes 8 taps → 2.

**Brightness shallows the pattern instead of gaining the picture.** One tap
cannot clamp per source pixel — the texture unit has already blended — and
clamping the blend is the non-linearity the design rule names. Measured: 1.860
of moiré against a limit of 0.40. Above 1 the turbo shaders reduce the pattern's
depth instead; the peak stays at 1, so there is no knee and nothing clips. Below
1 they are bit-identical to the released line.

**`crt-turbo` drops curvature and the slot mask.** Curvature was 68% of what
crt's effects cost, and it is the setting that provably breaks the budget.

## 1. Process flow, and what each stage costs

Percentages are ops with everything on, each stage measured on its own over the
plain scaler. They overlap where stages share setup, so they do not sum to 100.

| Shader | Flow |
|---|---|
| `pixel-turbo` | one LINEAR tap **(65%)** → white balance **(20%)** → brightness · contrast · saturation, folded affine **(27%)** → gamma **(7%)** |
| `dmg-turbo` | one LINEAR tap **(51%)** → balance · brightness → dot aperture over substrate **(8%)** → cast shadow, +1 tap **(39%)** → gamma **(2%)** |
| `crt-turbo` | one LINEAR tap + pitch and band-limit setup **(97%)** → gamma **(2%)** → scanlines **(0.7%)** → RGB mask **(0.7%)** → brightness **(0%)** |
| `lcd-turbo` | one LINEAR tap, aperture-weighted **(69%)** → mesh **(2%)** → RGB stripes + cast correction **(28%)** → gamma **(2%)** → brightness **(0%)** |

Two things worth reading off it:

- **The patterns are nearly free; the scale and the band-limiting are the cost.**
  `crt-turbo`'s scanlines and mask are 2 ops each. Its 276-op floor is the pitch,
  lock and Nyquist machinery, which sits outside the guards and runs whether the
  patterns are on or off. That is the next lever, not the patterns.
- **`dmg`'s shadow is the one expensive effect in the set** at 39% and the only
  one still needing a second tap. It is off by default.

## 2. Performance

`ops` and `tex` are deterministic, from SPIR-V with the parameters folded.
Desktop is an M4 Max and is compressed to near-noise — the render pass around
these shaders costs more than the shaders — so read the device column.

**Device figures for the `*-turbo` rows are PREDICTED**, from a model fitted to
the six measured rows in `device-results.tsv`:

```
frag_ms = -0.003 + 0.03056 * ops + 0.6712 * taps      r2 = 0.974, rms 0.755 ms
frame   = frag_ms + 1.329                              (measured, and flat in pass count)
```

| Shader | ops | SFU | tex | desktop ms | desktop vs `pixellate` | device ms | device vs `pixellate` | frame |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `pixel-turbo`, defaults | 53 | 0 | 1 | 0.0511 | 116% | *3.6* | *341%* | ***22%*** |
| `pixel-turbo`, all on | 82 | 6 | 1 | — | — | *4.5* | *274%* | ***27%*** |
| `dmg-turbo`, defaults | 168 | 6 | 2 | 0.0520 | 114% | *7.8* | *158%* | ***47%*** |
| `dmg-turbo`, all on | 273 | 6 | 2 | — | — | *11.0* | *112%* | ***66%*** |
| `crt-turbo`, defaults | 282 | 8 | 1 | 0.0564 | 105% | *10.6* | *116%* | ***64%*** |
| `crt-turbo`, all on | 286 | 14 | 1 | — | — | *10.7* | *115%* | ***64%*** |
| `lcd-turbo`, defaults | 293 | 17 | 1 | 0.0583 | 101% | *11.0* | *113%* | ***66%*** |
| `lcd-turbo`, all on | 298 | 23 | 1 | — | — | *11.1* | *111%* | ***67%*** |
| `pixel-perfect`, defaults | 112 | 0 | 4 | 0.0532 | 111% | **6.7** | **183%** | **40%** |
| `dmg-perfect`, defaults | 267 | 6 | 8 | 0.0586 | 101% | **14.6** | **84%** | **88%** |
| `lcd-perfect`, defaults | 334 | 17 | 4 | 0.0610 | 97% | **15.0** | **82%** | **90%** |
| `crt-perfect`, defaults | 428 | 8 | 4 | 0.0612 | 96% | **15.9** | **77%** | **96%** |

Bold device figures are measured; *italic* ones are predicted. Worst desktop
per-case IQR was 6.5%, so desktop differences smaller than that are noise.

Every turbo shader is **under the 75% target with everything enabled**, and the
three panel shaders roughly halve their released counterpart.

## 3. The reference stacks — what already works

What a user can assemble today from `tools/vendor/`, measured the same way.
All predicted, from the same model.

| Stack | passes | ops | tex | device ms | frame | vs `pixellate` |
|---|---:|---:|---:|---:|---:|---:|
| `sharp-shimmerless` | 1 | 49 | 1 | 3.5 | 21% | 353% |
| `dmg_dot_matrix` | 1 | 78 | 1 | 4.4 | 26% | 281% |
| `shimmerless → lcd1x` | 2 | 96 | 2 | 5.6 | 34% | 220% |
| `shimmerless → scanlines` | 2 | 101 | 2 | 5.8 | 35% | 214% |
| `shimmerless → lcd3x` | 2 | 117 | 2 | 6.2 | 37% | 197% |
| `pixellate` | 1 | 240 | 4 | **12.3** | **74%** | **100%** |
| `pixellate → lcd3x` | 2 | 308 | 5 | **15.2** | **91%** | **81%** |
| `shimmerless → adjust` | 2 | 394 | 3 | 15.4 | 92% | 80% |
| `dmg_dot_matrix → adjust` | 2 | 423 | 3 | 16.3 | 98% | 76% |
| `shimmerless → lcd1x → adjust` | 3 | 441 | 4 | 17.5 | 105% | 70% |

**`image-adjustment` costs more than any shader in this repo.** At 345 ops and
2 taps it is ~11.9 ms on its own — 71% of a frame — which is what turns every
otherwise-cheap stack into one that does not fit. The bare stacks are cheaper
than the turbo line; the moment grading is added, they are not:

| golden path | frame | turbo equivalent | frame |
|---|---:|---|---:|
| `shimmerless → lcd1x → adjust` | 105% | `lcd-turbo` | **66%** |
| `dmg_dot_matrix → adjust` | 98% | `dmg-turbo` | **47%** |
| `shimmerless → scanlines` + grading | ~92%+ | `crt-turbo` | **64%** |

The turbo shaders also do more: a real box-filtered scale, band-limited patterns
that do not beat, and grading, in one pass.

## 4. Visual quality against the released line

`moire` and `crawl` are the repo's own metrics, worst case over the matrix,
lower is better. `vs ref` is the largest 8-bit difference from the released
line's latest iteration.

| Shader | setting | moiré | crawl | vs ref |
|---|---|---:|---:|---:|
| `pixel-turbo` | defaults | 0.044 | 0.009 | 1/255 |
| `pixel-turbo` | all on | 5.784 | 0.517 | 1/255 |
| `pixel-perfect` v7 | defaults | 0.068 | 0.000 | — |
| `pixel-perfect` v7 | all on | 5.788 | 0.517 | — |
| `dmg-turbo` | defaults | 0.459 | 0.127 | 21/255 |
| `dmg-turbo` | all on | 1.642 | 1.042 | 105/255 |
| `dmg-perfect` v10c | defaults | 0.485 | 0.075 | — |
| `dmg-perfect` v10c | all on | 1.698 | 1.036 | — |
| `lcd-turbo` | defaults | 0.135 | 0.074 | 38/255 |
| `lcd-turbo` | all on | 2.613 | 0.408 | 109/255 |
| `lcd-perfect` v8 | defaults | 0.158 | 0.065 | — |
| `lcd-perfect` v8 | all on | 1.886 | 0.620 | — |
| `crt-turbo` | defaults | 0.306 | 0.070 | 25/255 |
| `crt-turbo` | all on | 5.439 | 0.091 | 98/255 |
| `crt-perfect` v12 | defaults | 0.494 | 0.068 | — |
| `crt-perfect` v12 | all on | *32.216* | *2.725* | — |

Reading it:

- **At defaults the turbo line is at or better than the released line on every
  metric.** `crt-turbo` needs no moiré exception at all, where `crt-perfect`
  needs two.
- **`vs ref` is 1/255 for `pixel-turbo`** — the one-tap scale is the four-tap
  scale. The larger figures elsewhere are the brightness reformulation, which is
  a level shift with no structure; at brightness 1.00 or below every turbo
  shader is within 1/255 of its counterpart.
- **The "all on" moiré figures are dominated by gamma at 1.40**, a `pow` after
  the blend that every shader here has. `pixel-perfect` reads 5.788 on it too.
- ***`crt-perfect` v12's 32.216 / 2.725 is a measurement artifact, not a defect.***
  "All on" includes curvature 0.15, and `docs/measurement.md` records that a
  row-mean metric is invalid on a warped image. `crt-turbo` has no curvature, so
  the pair is not comparable on that row.

## Rejected, with the measurement

| Idea | Verdict |
|---|---|
| Plain area blend in `lcd-turbo` instead of aperture weighting | **Rejected.** The mesh's dark line and the scaler's transition pixel both sit on the cell boundary, so they correlate: 1.890 moiré against a limit of 0.40. Keeping the aperture weighting costs nothing in taps. |
| Brightness as a gain on the blended colour | **Rejected.** 1.860 moiré. This is the design rule doing exactly what it says. |
| Brightness folded into the gamma exponent | **Rejected.** Still a non-linearity after the blend: 1.860 → the released line ships gamma at 1.00 precisely so it has none. |
| Brightness as `min(pattern × b, 1)` | **Rejected.** Position-only, so it does not beat, but the knees crawl at 0.719 against a limit of 0.35. |
| Hoisting uniform-derived setup into the vertex shader | **Not worth it.** Pinning the sizes to literals — perfect hoisting — removes 23 of `crt-turbo`'s 282 ops (8%) and 6 of `lcd-turbo`'s 293 (2%). The driver very likely already does it, and varyings cost interpolation. |
| A source-resolution grading pass | **Not needed.** It was the fix for the brightness clamp, but shallowing the pattern solves that in one pass at zero cost. `image-adjustment` at output resolution measures 11.9 ms, which is the ceiling it would have to beat. |
| `mediump` / fp16 split | **Open, and unmeasurable here.** Rogue GE8300 has native fp16 ALU; every desktop GPU runs `mediump` at fp32 and will report no change. Needs a device run to claim anything. The scale's `floor()` on a coordinate up to 480 must stay `highp`. |

## Next levers, in order

1. **`crt-turbo`'s 276-op floor.** The pitch, lock and Nyquist setup runs whether
   the patterns are on or off, and is 97% of the shader. The patterns themselves
   are 4 ops.
2. **`lcd-turbo`'s stripe block**, 28% of the shader, most of it the cast
   correction — which is non-negotiable, so it needs a cheaper form rather than
   removal.
3. **`mediump`**, once there is a device run to measure it on.

## Running it

```sh
.venv/bin/python tools/test.py crt-turbo        # the gate, one family
.venv/bin/python tools/perf.py --cost --static  # the per-effect breakdown
.venv/bin/python tools/preview.py crt-perfect-v12.glsl crt-turbo-v1.glsl --diff --as-shipped
```

Per-shader design records are in `docs/optimized/`. The released line's records
stay in `docs/`.

## The device run, when you want it

**Not run.** Every device figure above is predicted. `tools/device/build/ShaderBench.pak`
is built and ready — ARM aarch64, 18 pipelines, the four turbo shaders and the
seven reference stacks alongside the six rows already measured.

```sh
cp -r tools/device/build/ShaderBench.pak /Volumes/<card>/Tools/tg5040/
# then launch ShaderBench from the device's Tools menu; the screen stays black
# for a couple of minutes, then results.tsv and log.txt appear next to it

# or over SSH, which is quicker to iterate on
scp -r tools/device/build/ShaderBench.pak root@<ip>:/mnt/SDCARD/Tools/tg5040/
ssh root@<ip> 'cd /mnt/SDCARD/Tools/tg5040/ShaderBench.pak && ./launch.sh'
```

Two things to check when the numbers come back:

- **Whether the cost model held.** It predicts each row from `ops` and `taps`
  alone; the reference stacks are the interesting test, since none of the six
  fitted rows had three passes or a shader as arithmetic-heavy as
  `image-adjustment`.
- **Whether the one-tap scale still matches at 1/255.** The scaler anchor sits
  exactly on the tolerance on this desktop, and Rogue's bilinear weights are
  narrower fixed-point. Half a level is invisible in the picture, but the *gate*
  would fail — see `docs/optimized/pixel-turbo.md`.

`bench --self-test` also fails one check on a desktop GPU — the blended-repeat
probe, because the work is far smaller than the fixed cost around it. That is
pre-existing and documented in `docs/device-perf.md`; on the device all six pass.
