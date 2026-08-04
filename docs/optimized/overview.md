# The `*-turbo` and `*-mini` lines

The shipped shaders do not fit the device. Measured on the Brick at 320x240 →
1024x768, `crt-perfect` uses 96% of a 60fps frame on its own, `lcd-perfect` 90%
and `dmg-perfect` 88% — with no emulator underneath. Two new lines answer that,
and **the released shaders are not touched.**

| line | what it is | when to use it |
|---|---|---|
| `*-turbo` | the same four shaders, one pass, rebuilt around a single texture tap | you want one shader and the best picture per millisecond |
| `*-mini` | the pattern only, no scaler, composable behind anything | you want to pick your own scaler, or chain a source-resolution colour pass |

Target: **≤ 75% of a frame (12.5 ms) at the shipped defaults.** Measured on the
device: seven of the eight meet it. **`lcd-turbo-v4` clears it at 71%** and
`crt-turbo-v4a` sits exactly on it at 75%; `crt-turbo-v4b` has room at 72%, for
one line of fidelity under curvature. Every one of them halves what it
replaces.

**Every device figure on this page is measured**, from the run in
`docs/device-results.tsv`. See [the device run](#the-device-run).

## What v6 changed

**The lcd line goes back to the released shader.** `lcd-perfect`'s release is
**v6**, and the owner prefers it over every arm built since — including the one
that fixes the stripe peaking near 2. So `lcd-turbo-v4` and `lcd-mini-v4` adopt
its brightness *and* its stripe, and `lcd-perfect`'s head moves back onto v6.

`lcd-turbo-v3` was `lcd-perfect-v9a` with four taps replaced by one and nothing
else, so two edits leave the scaler as the only difference from the release:

```glsl
stripe = vec3(rg, 3.0 - rg.x - rg.y);              // was  / (1.0 + ac)
vec3 m = sqrt(max(stripe * (gain * lp_brightness), 0.0));
```

| | vs the release, integer scales, brightness 0.25 → 4.00 | moiré exceptions | device |
|---|---:|---:|---:|
| `lcd-turbo-v3` | 137/255 | 6, worst 3.400 | 12.6 ms, 75% |
| **`lcd-turbo-v4`** | **0/255** | **1**, worst 0.435 | **11.8 ms, 71%** |
| `lcd-mini-v3` | — | 6, worst 1.062 | 8.6 ms, 51% |
| **`lcd-mini-v4`** | — | **none** | **7.9 ms, 47%** |

0/255 is identity, not tolerance. **And it got faster by doing less**: brightness
is one multiply into the pattern gain where v3 had a guarded clamp, and the
stripe lost a divide — 11 ops, 0.72 ms, and the first lcd head to clear the 75%
target.

The crawl exceptions are the price, and they are `lcd-perfect`'s own to within
0.07. That is the trade the owner chose: a gain above 1 has to clip somewhere,
and clipping the pattern beats while clipping the picture bleaches. Same choice
as `crt-perfect`'s, recorded in `docs/crt-perfect.md`.

**`lcd-mini-v4` declares no exceptions at all**, which is the strongest result
the harness can produce. Standalone the mini has no scaler, so v3's clamp was
beating against its own pattern rather than a footprint; moving the gain out of
the content removed it.

## What v5 changed

**`crt-turbo` and `crt-mini` take `crt-perfect`'s brightness.** v3 clamped the
content before the pattern; v4 multiplies brightness into the pattern gain, as
the released v10 does. Moiré at the 1.25 default falls from **7.256 to 0.480**
— seven recorded exceptions become one — and `crt-turbo-v4a` now matches
`crt-perfect` within 1/255 at *every* brightness, where v3 was 27/255 out at the
default.

**Curvature's cost was traced, and the answer was the reverse of the guess.**
It is not the warp arithmetic and not the dependent texture read: `jac` and
`noWarp` are written inside the guard, which turns three hoistable quantities
into per-fragment ones.

| build | frame | saves |
|---|---:|---:|
| **`crt-turbo-v4a`**, full fidelity — `current` | **76%** | — |
| **`crt-turbo-v4b`**, `jac` pinned | **72%** | 0.60 ms |
| probe, `noWarp` pinned | 63% | 2.22 ms |
| probe, both pinned | 60% | 2.82 ms |
| `crt-turbo-v1`, no curvature code at all | 56% | 3.58 ms |

**`noWarp` is worth 1.62 ms against the Jacobian's 0.60**, nearly three times
as much, and it only scales two pattern terms. The value that feeds the texture
coordinate was the cheaper half. Both arms are byte-identical at
`cp_curvature = 0` and differ by 74/255 at 0.15 — a difference nobody sees
without a diff. `v4a` ships as `current` because it gives up nothing; `v4b`
exists because it is the arm that meets the target.

**There is no `crt-mini-v4b`.** The mini has no footprint to correct, so a b arm
would be byte-identical to `v4` — which is exactly the trap `crt-perfect-v13`
fell into, caught this time before it was built.

**No `dmg` v4, deliberately.** The shadow was investigated for all three things
asked of it and none justified a version number: the reported missing blur was a
NEAREST filter rather than a shader defect; the blur is already near-minimal,
with nothing to hoist and nothing shareable with the main coverage integral; and
it is **already free when disabled** — 0.045 ms on `dmg-turbo`, 0.151 ms on
`dmg-mini`, against `dp_shadow` shipping at 0. A cell-centre `paper` fix for the
standalone mini was built and measured at 0.03–0.14% closer on eight cases and
worse on two, for +7 ops and a third tap. Rejected. See
`docs/optimized/dmg-turbo.md`.

**`lcd-perfect-v9c`'s grid goes to 3.0 px**, edited in place at the owner's
request rather than as a new iteration. Levels stay monotonic (250.0 → 196.8
mean at ×4) and worst moiré is 0.248 against a 0.40 limit.

**Every `*-mini` header now opens its Notes with the LINEAR requirement.** None
of them mentioned it, and under NEAREST the pattern still draws while the
picture underneath silently becomes nearest-neighbour — the failure mode looks
like a broken effect, not a wrong filter.

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
picture rather than brightening it. `crt-perfect` went back to **v10, which is
the shipped release**, and `lcd-perfect-v9a` put the same form back — both take
the crawl with it.

*(A `crt-perfect-v13` existed briefly. It turned out to be v10 with three
comment lines and byte-identical code, so it was withdrawn rather than kept.
Reverting v12's brightness and gamma to where v10 has them lands exactly on v10,
which is the whole point and was worth noticing sooner.)*

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

**Every figure below is MEASURED on the device.** 47 pipelines, one run,
`docs/device-results.tsv`; self-test passed, worst IQR 2.5% and most under 1%.

| Shader | ops | SFU | tex | desktop ms | device ms | vs `pixellate` | frame |
|---|---:|---:|---:|---:|---:|---:|---:|
| `pixel-turbo`, defaults | 53 | 0 | 1 | 0.0493 | **4.5** | **269%** | **27%** |
| `colour-mini`, defaults | 20 | 0 | 1 | 0.0493 | **3.1** | **391%** | **19%** |
| `dmg-turbo`, defaults | 168 | 6 | 2 | 0.0538 | **8.4** | **145%** | **50%** |
| `dmg-mini`, defaults | 148 | 6 | 2 | 0.0522 | **7.4** | **166%** | **44%** |
| `lcd-turbo`, defaults | 286 | 17 | 1 | 0.0585 | **12.6** | **97%** | **76%** |
| `lcd-mini`, defaults | 220 | 13 | 1 | 0.0566 | **8.6** | **142%** | **52%** |
| `crt-turbo`, defaults | 303 | 8 | 1 | 0.0585 | **13.0** | **94%** | **78%** |
| `crt-mini`, defaults | 266 | 8 | 1 | 0.0588 | **11.0** | **111%** | **66%** |
| `pixel-perfect`, defaults | 112 | 0 | 4 | 0.0538 | **6.7** | **181%** | **40%** |
| `dmg-perfect`, defaults | 267 | 6 | 8 | 0.0591 | **14.6** | **84%** | **88%** |
| `lcd-perfect`, defaults | 334 | 17 | 4 | 0.0631 | **15.0** | **81%** | **90%** |
| `crt-perfect`, defaults | 428 | 8 | 4 | 0.0663 | **15.9** | **77%** | **95%** |

- **Six of the eight new shaders are inside the 75% target.** `lcd-turbo` at
  **76%** and `crt-turbo` at **78%** miss it. Both are still far better than
  what they replace — `lcd-perfect` is 90% and `crt-perfect` 95% — but the
  target was not met for those two, and saying otherwise would be a lie the next
  measurement would catch.
- **The panel shaders roughly halve their released counterpart** at the same
  picture: `dmg` 88% → 50%, `lcd` 90% → 76%, `crt` 95% → 78%.
- **The mini line is genuinely cheaper standalone**, by 8 to 24 points, and the
  frontend's bilinear upscale is what pays for it.

### One `pow()` costs 1.34 ms, and that changes the guidance

The v2 → v3 brightness change is a controlled experiment: nothing else moved,
and at the shipped defaults it flips a guarded `pow()` from live to dead.

| pair | Δops | ΔSFU | Δfrag_ms | ships gamma at |
|---|---:|---:|---:|---:|
| `crt-turbo` v2→v3 | +2 | **−6** | **−1.350** | 1.00 |
| `lcd-turbo` v2→v3 | +2 | **−6** | **−1.352** | 1.00 |
| `crt-mini` v2→v3 | +2 | **−6** | **−1.346** | 1.00 |
| `lcd-mini` v2→v3 | +2 | **−6** | **−1.333** | 1.00 |
| `dmg-turbo` v2→v3 | 0 | 0 | **0.000** | **1.20** |
| `dmg-mini` v2→v3 | 0 | 0 | **+0.005** | **1.20** |

Four shaders lose six SFU and each saves **0.22 ms per SFU op**. The two `dmg`
shaders ship `dp_gamma` at 1.20, so the `pow` runs either way — and they move by
**0.000 and 0.005 ms**. That is the control the experiment needed, and it is as
clean as this repository has ever measured anything.

**So one `vec3 pow()` per fragment is 1.34 ms — 8% of a 60fps frame**, against
about 0.023 ms for an ordinary op. A transcendental is worth roughly **ten
ordinary ops** here.

`AGENTS.md` said the opposite — "time tracks ops, not SFU ... unrelated to SFU"
— and that was inferred from six rows in which ops and SFU happened to be
correlated. It is wrong and has been corrected. The evidence that misled it is
still real: `pixellate` carries the most SFU here and is not the slowest,
because it also has far fewer ops. **Both terms matter; neither alone predicts.**

The practical rule: **guard every `pow()` on the parameter that actually
disables it, and ship that parameter neutral if you can.** `lcd-turbo` and
`crt-turbo` ship gamma at 1.00 and get the branch for free; `dmg` ships 1.20 and
pays 1.34 ms for it every frame.

### The cost model, refitted on 47 rows

```
frag_ms = 0.0278*ops + 0.409*tex + 0.098*sfu + 0.639     r2 = 0.961, rms 0.87 ms
frame   = frag_ms + 1.46   (1 pass)   1.64 (2 passes)   1.50 (3 passes)
```

The `sfu` coefficient here (0.098) is an average over shaders whose SFU sit in
branches that may not execute; the controlled pairs above measure the *executed*
price at 0.224. Use the model to rank, and the pair figure to decide.

**A second pass costs ~0.2 ms and a third costs nothing measurable.** Frame
overhead is 1.46 ms at one pass, 1.64 at two and 1.50 at three — flat inside the
spread. On a tile-based GPU that is expected, and it is what makes the mini line
viable at all.

### What the old predictions got wrong

Median error **+2.2 points**, so the ranking held everywhere. Two systematic
misses are worth recording:

- **The turbo line was underpredicted by 5–12 points** — `lcd-turbo` predicted
  64% and measured 76%, `crt-turbo` 68% against 78%. The old model had no SFU
  term, and these are the shaders carrying the most.
- **`lcd-perfect-v9c` was predicted at 108% and measured 84.5%** — a 24-point
  miss, and in the useful direction. See below.

### The unreleased `*-perfect` iterations, and a reversal

| Shader | ops | SFU | tex | device ms | frame |
|---|---:|---:|---:|---:|---:|
| `crt-perfect` v10, released | 428 | 8 | 4 | **15.9** | **95%** |
| `crt-perfect` v12, per-tap clamp | 449 | 8 | 4 | **16.2** | **97%** |
| **`crt-perfect` v10, head and release** | **428** | **8** | **4** | **15.9** | **95%** |
| `lcd-perfect` v6, released | 334 | 17 | 4 | **15.0** | **90%** |
| `lcd-perfect` v8, per-tap clamp | 351 | 17 | 4 | **15.7** | **94%** |
| **`lcd-perfect` v9a, head** | 338 | 17 | 4 | **15.3** | **92%** |
| `lcd-perfect` v9b, lcd1x phase | 336 | 17 | 4 | **14.8** | **89%** |
| **`lcd-perfect` v9c, gap aperture** | **432** | **12** | 4 | **14.1** | **84%** |

`crt-perfect` v10 and v12 differ by 21 ops and 0.3 ms, so the per-tap clamp was
costing time as well as bleaching highlights. The withdrawn v13 was measured
separately at 15.863 ms against v10's 15.884 — the same file twice, 0.02 ms
apart, which is a free reading of the run's own reproducibility.

**`v9c` is the fastest of the whole `lcd-perfect` family, and I predicted it
would be the slowest.** 432 ops against v9a's 338, and it measures **14.1 ms
against 15.3** — cheaper than the shipped release too. The reason is the finding
above: the gap aperture replaces transcendentals with `floor`, `min` and
`fract`, dropping **5 SFU**, and 5 SFU buy far more than 94 ordinary ops cost.

That reverses the conclusion in the v3 plan. **The gap aperture is not a
looks-versus-speed trade — it is better on both**, and nothing needs making
cheap before it could go into `lcd-turbo`.

## 3. What a chain costs

The mini line is meant to be assembled. A pass rendered at **source** resolution
(`upscale = 1`) covers 1/10 of the pixels at 320x240 → 1024x768. All measured.

| Stack | passes | device ms | frame | vs `pixellate` |
|---|---:|---:|---:|---:|
| `colour-mini` | 1 | **3.1** | **19%** | **391%** |
| `colour-mini @src → pixel-turbo` | 2 | **4.7** | **28%** | **260%** |
| `pixel-turbo → colour-mini` | 2 | **6.3** | **38%** | **192%** |
| `dmg-mini` | 1 | **7.4** | **44%** | **166%** |
| `pixel-turbo → dmg-mini` | 2 | **10.1** | **60%** | **121%** |
| `lcd-mini` | 1 | **8.6** | **52%** | **142%** |
| `shimmerless → lcd-mini` | 2 | **10.6** | **64%** | **115%** |
| `pixel-turbo → lcd-mini` | 2 | **11.2** | **67%** | **109%** |
| `colour-mini @src → pixel-turbo → lcd-mini` | 3 | **11.6** | **70%** | **105%** |
| `crt-mini` | 1 | **11.0** | **66%** | **111%** |
| `pixel-turbo → crt-mini` | 2 | **13.7** | **82%** | **89%** |

**A source-resolution colour pass costs 0.16 ms** — `pixel-turbo` alone is
4.53 ms and `colour-mini @src → pixel-turbo` is 4.69. Predicted 0.2 ms, and it
is the number the whole escape hatch from the brightness exception rests on.

**Order matters more than anything else in this table.** The same two shaders
cost 4.7 ms with the grade first at source resolution and 6.3 ms with it last at
output resolution — **11× the marginal cost for the identical picture.** Grading
at source resolution is both the cheap way and the correct way.

**A chain is not cheaper than the single shader that does the same thing.**
`pixel-turbo → lcd-mini` is 67% against `lcd-turbo`'s 76% — actually *cheaper*
here, because `lcd-turbo` carries the aperture-weighted blend that `lcd-mini`
does not need. But `pixel-turbo → crt-mini` is 82% against `crt-turbo`'s 78%.
The mini line wins on *choice*, and sometimes on the clock.

### The reference stacks — what already works

What a user can assemble today from `tools/vendor/`, measured the same way.

| Stack | passes | device ms | frame | vs `pixellate` |
|---|---:|---:|---:|---:|
| `sharp-shimmerless` | 1 | **3.9** | **23%** | **316%** |
| `dmg_dot_matrix` | 1 | **4.9** | **30%** | **247%** |
| `shimmerless → scanlines` | 2 | **5.7** | **34%** | **214%** |
| `shimmerless → lcd1x` | 2 | **6.3** | **38%** | **192%** |
| `shimmerless → lcd3x` | 2 | **6.8** | **41%** | **179%** |
| `pixellate` | 1 | **12.2** | **73%** | **100%** |
| `shimmerless → adjust` | 2 | **14.4** | **87%** | **84%** |
| `pixellate → lcd3x` | 2 | **15.2** | **91%** | **80%** |
| `dmg_dot_matrix → adjust` | 2 | **15.7** | **94%** | **78%** |
| `shimmerless → lcd1x → adjust` | 3 | **16.7** | **100%** | **73%** |

**`image-adjustment` costs 8.1 ms on its own** — `shimmerless` is 3.9 and
`shimmerless → adjust` is 14.4, so the grading pass is 10.5 ms of frame at
output resolution. That is what turns every otherwise-cheap stack into one that
does not fit, and `shimmerless → lcd1x → adjust` lands at **exactly 100.2% of a
frame** — it does not fit, measured.

`colour-mini` does the same job at source resolution for **0.16 ms**, which is
**65× cheaper**.

The bare vendor stacks are cheaper than either of our lines, and honestly so.
The moment grading is added, they are not:

| golden path | frame | ours | frame |
|---|---:|---|---:|
| `shimmerless → lcd1x → adjust` | **100%** | `lcd-turbo` | **76%** |
| `dmg_dot_matrix → adjust` | **94%** | `dmg-turbo` | **50%** |
| `shimmerless → scanlines` + grading | **~85%** | `crt-turbo` | **78%** |

And ours do more: a real box-filtered scale, band-limited patterns that do not
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
| `crt-perfect` v10 | 0.334 | *32.216* | 0.093 | — | — |
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
| **`crt-perfect` v10**, the release | gain on the blend, clamped | 0.295 | **1.496** | 0.466 | 7.347 |
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
| `lcd-turbo`, brightness 1.25 | 1 | **76%** | 3.400 |
| `colour-mini @src → pixel-turbo → lcd-mini`, brightness 1.25 in pass 1 | 3 | **70%** | 1.062 |

**Six points of frame time buys most of the exception back** — measured, where
the prediction said one. The extra is `lcd-mini` and `pixel-turbo` doing the
scale in two passes rather than `lcd-turbo` doing it in one; the grading pass
itself is 0.16 ms. The turbo line takes the exception so one shader is enough;
the mini line exists so it does not have to be taken.

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

## Next levers, reordered by what the device said

The device run moved every item on this list, because the old order was sorted
by op count and ops are not what costs.

1. **Kill transcendentals.** One `vec3 pow()` is 1.34 ms — 8% of a frame, worth
   about ten ordinary ops each. `lcd-turbo` still carries 17 SFU and `crt-turbo`
   8. `lcd-perfect-v9c` already demonstrates the payoff: +94 ops and −5 SFU made
   it the *fastest* shader in its family. Every `sin`, `cos`, `sqrt` and `pow`
   in a pattern is now a candidate for a polynomial or a table.
2. **~~Settle whether a disabled uniform branch is free.~~ Answered: it depends
   on what the branch writes.** Curvature costs **3.58 ms with `cp_curvature` at
   0.00**; the dmg shadow costs **0.045 ms** with `dp_shadow` at 0, and the slot
   mask 0.14 ms unselected. The cheap ones write only values that were already
   per-fragment; curvature writes two that the driver was hoisting out of the
   shader entirely. Pinning those two back recovers 2.82 of the 3.58 ms, and
   **that is now the largest single saving available in this line** — it is
   waiting on a decision, not a measurement.
3. **`mediump` / fp16**, which is now the obvious follow-on from item 1 rather
   than an afterthought.
4. **`crt-turbo`'s 291-op floor.** Still real, still 72% of the shader — but at
   0.023 ms an op it is worth less than any of the above.

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

The released line's records stay in `docs/` — `docs/crt-perfect.md` for the
brightness forms and `docs/lcd-perfect.md` for the three v9 grid arms.

## The device run

**Run, 3 August 2026.** All 47 pipelines, self-test passed, results in
`docs/device-results.tsv`. PowerVR Rogue GE8300, OpenGL ES 3.2 build
1.19@6345021, 320x240 into 1024x768, GPU 42.9 → 47.1 °C over the run. Worst IQR
2.5%, median under 0.5%.

Every figure on this page is measured. The five that were `italic` predictions
are now bold, and the two places the prediction was materially wrong are called
out where they matter — the turbo line was 5–12 points optimistic, and
`lcd-perfect-v9c` was 24 points pessimistic.

To repeat it:

```sh
cd tools/device && make pak

# over SSH, which is quicker to iterate on
ssh root@<ip> 'rm -rf /mnt/SDCARD/.shadercache'
tar czf - -C tools/device/build ShaderBench.pak \
  | ssh root@<ip> 'cd /mnt/SDCARD/Tools/tg5040 && tar xzf -'
ssh root@<ip> 'cd /mnt/SDCARD/Tools/tg5040/ShaderBench.pak && ./launch.sh'
ssh root@<ip> 'cat /mnt/SDCARD/Tools/tg5040/ShaderBench.pak/results.tsv' \
  > docs/device-results.tsv
python tools/report.py docs/device-results.tsv
```

Three practical notes, each of which cost time:

- **There is no `scp` on the device.** Use `tar` over `ssh` as above; `scp -O`
  fails with `ash: scp: not found`.
- **Delete `.shadercache` first, every time.** It is keyed on filename with no
  content hash, so a new `crt-turbo-v3.glsl` silently loads the old binary.
- **The screen stays black for the whole run.** Nothing is presented; that is
  what success looks like. The self-test runs first, and if it fails the table
  is discarded rather than printed.

### Settled after the run: curvature is not free when off

`crt-turbo-v1` measured 56% of a frame against `v3`'s 78%, so three probes were
built from `v3` by deleting one guarded block each — byte-identical at the
shipped defaults, and verified to have genuinely lost the feature at curvature
0.15:

| build | live ops | ops@def | frame |
|---|---:|---:|---:|
| `crt-turbo-v3` | 443 | 303 | **78.1%** |
| slot-mask branch deleted | 416 | 301 | **77.3%** |
| **curvature block deleted** | 360 | 301 | **59.8%** |
| both deleted | 333 | 299 | **57.8%** |

**The v2 decision was half right.** The slot mask really is free when
unselected — 0.14 ms, inside the noise. **Curvature costs 3.26 ms with
`cp_curvature` at its shipped 0.00**: nearly 20% of a frame, paid by everyone
who never turns it on. That is the difference between `crt-turbo` missing the
75% target at 78% and clearing it comfortably at 60%.

The reason the two differ is what they write. The curvature block writes `uv`,
and `uv` is the texture coordinate — its mere presence makes the fetch address
depend on fragment arithmetic, so the read becomes *dependent* and cannot be
issued ahead of the shader. The slot-mask branch only adds to a local scalar.

**`ops@def` moved by 2 across that 3.26 ms**, because it folds parameters to
literals and deletes the branch a live uniform keeps. It is the wrong column for
pricing an option; `live` is the right one, and even it under-prices a texcoord.

**This is the owner's original report, explained.** "Adding curvature and it
falls under 60fps every time" — it was never only the curvature setting. The
code being present costs a fifth of the frame at every setting.

**The fix has to be a second shader file, not a cheaper branch.** No guard can
make this free; that is what the measurement says. Not done, because it is a
shipping decision rather than an optimisation — see `docs/device-perf.md`.

### Still open

- **`mediump` / fp16.** Untested, and now the clearest remaining lever: if a
  transcendental costs ten ordinary ops, half-precision on the SFU path is where
  the wins are.
