# The optimized line: flow and cost

Two tables and nothing else. Every new iteration updates both, and both are
measured on the desktop *and* on the device before an iteration is called done.

The essay — why any of this is shaped the way it is, what was rejected, and the
measurement traps behind each number — is in
[`docs/optimized/overview.md`](optimized/overview.md), with a design record per
shader beside it.

## 1. Process flow, and what each stage costs

Each stage is measured on its own, on top of the same shader with every effect
neutral, and quoted as a share of what that shader's effects add in total.
Stages that share a guarded block overlap, so a flow can sum past 100%.

**`floor`** is the shader with every effect off: the scale, the pitch and the
band-limiting. It is what a user pays before choosing anything, and for the
`crt` family it is most of the shader.

| Shader | floor | Flow |
|---|---:|---|
| `pixel-perfect` *(released)* | 112 | four NEAREST taps, box blend **(floor)** → white balance **(55%)** → brightness · contrast · saturation **(75%)** → gamma **(20%)** |
| `pixel-turbo` v1 · v2 · **v3** | 53 | one LINEAR tap, box blend **(floor)** → white balance **(55%)** → brightness · contrast · saturation **(75%)** → gamma **(20%)** |
| `colour-mini` v2 · **v3** | 20 | one tap at 1:1 **(floor)** → white balance **(55%)** → brightness · contrast · saturation **(75%)** → gamma **(20%)** |
| `crt-perfect` *(released)* | 421 | four taps + pitch, lock, Nyquist **(floor)** → curvature **(68%)** → slot mask **(21%)** → gamma **(5%)** → scanlines **(1%)** → RGB mask **(1%)** |
| `crt-turbo` v1 | 276 | one tap + band-limit **(floor)** → gamma **(60%)** → scanlines **(20%)** → RGB mask **(20%)** *(no curvature, no slot mask)* |
| `crt-turbo` v2 · v3 | 289 | one tap + band-limit **(floor)** → curvature **(69%)** → slot mask **(20%)** → gamma **(5%)** → scanlines **(1%)** → RGB mask **(1%)** |
| **`crt-turbo` v4a** | 289 | one tap + band-limit **(floor)** → curvature **(69%)** → slot mask **(20%)** → brightness · gamma **(5%)** → scanlines **(1%)** → RGB mask **(1%)** |
| `crt-turbo` v4b | 285 | as v4a, with the warp's Jacobian pinned: curvature **(65%)** → slot mask **(23%)** → brightness · gamma **(6%)** → scanlines **(2%)** → RGB mask **(2%)** |
| `crt-mini` v2 · v3 · **v4** | 252 | one tap at 1:1 + band-limit **(floor)** → curvature **(65%)** → slot mask **(23%)** → brightness · gamma **(6%)** → scanlines **(2%)** → RGB mask **(2%)** |
| `lcd-perfect` *(released, v6)* | 249 | four taps, aperture-weighted **(floor)** → RGB stripes + cast correction **(87%)** → mesh **(8%)** → brightness **(1%)** → gamma **(7%)** |
| `lcd-turbo` v1 · v2 · v3 | 192 | one tap, aperture-weighted **(floor)** → RGB stripes + cast correction **(88%)** → mesh **(7%)** → brightness · gamma **(6%)** |
| **`lcd-turbo` v4** | 190 | one tap, aperture-weighted **(floor)** → RGB stripes + cast correction **(87%)** → mesh **(8%)** → brightness **(1%)** → gamma **(7%)** |
| `lcd-mini` v2 · v3 | 122 | one tap at 1:1 **(floor)** → RGB stripes + cast correction **(88%)** → mesh **(7%)** → brightness · gamma **(6%)** |
| **`lcd-mini` v4** | 120 | one tap at 1:1 **(floor)** → RGB stripes + cast correction **(87%)** → mesh **(7%)** → brightness **(1%)** → gamma **(6%)** |
| `dmg-perfect` *(released)* | 194 | four taps, box + dot aperture **(floor)** → cast shadow, +4 taps **(74%)** → grid **(18%)** |
| `dmg-turbo` v1 · v2 · **v3** | 140 | one tap, box + dot aperture **(floor)** → cast shadow, +1 tap **(83%)** → grid **(16%)** |
| `dmg-mini` v2 · **v3** | 120 | one tap at 1:1 + dot aperture **(floor)** → cast shadow, +1 tap **(83%)** → grid **(16%)** |

Reading it:

- **The floor is the cost, not the effects.** `crt-turbo`'s patterns are 2 ops
  each; its 289-op floor is the pitch, lock and Nyquist machinery that runs
  whether they are on or off.
- **Curvature is the largest single effect in the repo** and, uniquely, it is
  *not* free when switched off: it costs 3.58 ms on the device with the slider
  at zero, because it makes uniform-derived work per-fragment. The slot mask,
  behind an identical-looking guard, really is free. v4b trades the warp's
  Jacobian to recover 0.60 ms of that; pinning `noWarp` as well would recover
  2.82 ms, and is unshipped pending a decision.
- **`dmg`'s shadow is the most expensive effect in the set** at 83%, and the
  only one still needing a second tap. It is off by default.
- **`lcd`'s stripe block is 87%**, most of it the colour-cast correction, which
  is not optional — without it the stripes tint the picture.
- **`lcd`'s brightness is 1 op in v4**, against a guarded clamp in v3. It
  multiplies into the pattern gain, which is where the released shader has it,
  so there is nothing to branch on and nothing to clamp separately. The three
  `lcd` rows now read identically apart from the floor, which is the whole point
  of v4: same shader, cheaper scaler.

## 2. Performance

`ops`, `SFU` and `tex` are with the parameters folded at that setting, so the
two rows differ. Desktop is an M4 Max: the render pass around these shaders
costs more than the shaders, so its column separates almost nothing and is here
only to show it does not contradict the device. **Read the device columns.**

`vs pix.` is against `pixellate`, which ships on the target and holds 60fps, so
higher is cheaper. **frame** is the share of one 60fps frame (16.67 ms).

| Shader | setting | ops | SFU | tex | desktop ms | vs pix. | device ms | vs pix. | frame |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pixel-perfect *(released)* | defaults | 112 | 0 | 4 | 0.0599 | 98% | 6.7 | 182% | **40%** |
|  | all on | 141 | 6 | 4 | 0.0673 | 88% | 8.9 | 137% | **54%** |
| pixel-turbo v1 | defaults | 53 | 0 | 1 | — | — | 4.4 | 276% | **27%** |
|  | all on | 82 | 6 | 1 | — | — | — | — | — |
| pixel-turbo v2 | defaults | 53 | 0 | 1 | — | — | 4.7 | 264% | **28%** |
|  | all on | 82 | 6 | 1 | — | — | — | — | — |
| **pixel-turbo v3** | defaults | 53 | 0 | 1 | 0.0506 | 116% | 4.5 | 272% | **27%** |
|  | all on | 82 | 6 | 1 | 0.0523 | 113% | 6.7 | 184% | **40%** |
| colour-mini v2 | defaults | 20 | 0 | 1 | — | — | 3.1 | 399% | **18%** |
|  | all on | 49 | 6 | 1 | — | — | — | — | — |
| **colour-mini v3** | defaults | 20 | 0 | 1 | 0.0493 | 119% | 3.1 | 395% | **19%** |
|  | all on | 49 | 6 | 1 | 0.0488 | 121% | 5.1 | 240% | **31%** |
| crt-perfect *(released)* | defaults | 428 | 8 | 4 | 0.0650 | 91% | 15.9 | 77% | **95%** |
|  | all on | 503 | 14 | 4 | 0.0678 | 87% | 19.9 | 62% | **119%** |
| crt-turbo v1 | defaults | 282 | 8 | 1 | — | — | 9.3 | 132% | **56%** |
|  | all on | 286 | 14 | 1 | — | — | — | — | — |
| crt-turbo v2 | defaults | 301 | 14 | 1 | — | — | 14.3 | 86% | **86%** |
|  | all on | 372 | 14 | 1 | — | — | — | — | — |
| crt-turbo v3 | defaults | 303 | 8 | 1 | — | — | 13.0 | 95% | **78%** |
|  | all on | 380 | 14 | 1 | — | — | — | — | — |
| **crt-turbo v4a** | defaults | 296 | 8 | 1 | 0.0578 | 102% | 12.6 | 97% | **76%** |
|  | all on | 373 | 14 | 1 | 0.0595 | 99% | 15.8 | 78% | **95%** |
| crt-turbo v4b | defaults | 292 | 8 | 1 | 0.0570 | 103% | 12.1 | 102% | **72%** |
|  | all on | 357 | 14 | 1 | 0.0580 | 102% | — | — | — |
| crt-mini v2 | defaults | 264 | 14 | 1 | — | — | 12.3 | 100% | **74%** |
|  | all on | 323 | 14 | 1 | — | — | — | — | — |
| crt-mini v3 | defaults | 266 | 8 | 1 | — | — | 11.0 | 111% | **66%** |
|  | all on | 331 | 14 | 1 | — | — | — | — | — |
| **crt-mini v4** | defaults | 259 | 8 | 1 | 0.0556 | 106% | 10.6 | 116% | **63%** |
|  | all on | 324 | 14 | 1 | 0.0567 | 104% | 13.6 | 90% | **82%** |
| lcd-perfect *(released, v6)* | defaults | 334 | 17 | 4 | 0.0602 | 96% | 15.0 | 82% | **90%** |
|  | all on | 339 | 23 | 4 | 0.0602 | 96% | 16.5 | 75% | **99%** |
| lcd-turbo v1 | defaults | 293 | 17 | 1 | — | — | 12.8 | 96% | **77%** |
|  | all on | 298 | 23 | 1 | — | — | — | — | — |
| lcd-turbo v2 | defaults | 284 | 23 | 1 | — | — | 13.9 | 89% | **83%** |
|  | all on | 283 | 23 | 1 | — | — | — | — | — |
| lcd-turbo v3 | defaults | 286 | 17 | 1 | 0.0585 | 101% | 12.6 | 98% | **75%** |
|  | all on | 291 | 23 | 1 | 0.0586 | 101% | 14.1 | 87% | **85%** |
| **lcd-turbo v4** | defaults | 275 | 17 | 1 | 0.0574 | 100% | 11.8 | 104% | **71%** |
|  | all on | 280 | 23 | 1 | 0.0571 | 101% | 13.4 | 92% | **80%** |
| lcd-mini v2 | defaults | 218 | 19 | 1 | — | — | 9.8 | 125% | **59%** |
|  | all on | 217 | 19 | 1 | — | — | — | — | — |
| lcd-mini v3 | defaults | 220 | 13 | 1 | 0.0534 | 110% | 8.6 | 143% | **52%** |
|  | all on | 225 | 19 | 1 | 0.0534 | 110% | 10.1 | 121% | **61%** |
| **lcd-mini v4** | defaults | 209 | 13 | 1 | 0.0515 | 112% | 7.9 | 156% | **47%** |
|  | all on | 214 | 19 | 1 | 0.0522 | 110% | 9.4 | 131% | **56%** |
| dmg-perfect *(released)* | defaults | 267 | 6 | 4 | 0.0599 | 98% | 14.6 | 84% | **88%** |
|  | all on | 443 | 6 | 8 | 0.0673 | 88% | 20.6 | 60% | **124%** |
| dmg-turbo v1 | defaults | 168 | 6 | 1 | — | — | 8.4 | 146% | **51%** |
|  | all on | 273 | 6 | 2 | — | — | — | — | — |
| dmg-turbo v2 | defaults | 168 | 6 | 1 | — | — | 8.4 | 146% | **50%** |
|  | all on | 273 | 6 | 2 | — | — | — | — | — |
| **dmg-turbo v3** | defaults | 168 | 6 | 1 | 0.0525 | 112% | 8.4 | 147% | **50%** |
|  | all on | 273 | 6 | 2 | 0.0565 | 104% | 12.5 | 98% | **75%** |
| dmg-mini v2 | defaults | 148 | 6 | 1 | — | — | 7.4 | 165% | **45%** |
|  | all on | 253 | 6 | 2 | — | — | — | — | — |
| **dmg-mini v3** | defaults | 148 | 6 | 1 | 0.0507 | 116% | 7.3 | 167% | **44%** |
|  | all on | 253 | 6 | 2 | 0.0545 | 108% | 11.5 | 107% | **69%** |
|  |  |  |  |  |  |  |  |  |  |
| `sharp-shimmerless` | — | 49 | 0 | 1 | 0.0481 | 122% | 3.8 | 320% | **23%** |
| `dmg_dot_matrix` | — | 78 | 6 | 1 | 0.0480 | 123% | 5.2 | 237% | **31%** |
| `barrel-distortion` | — | 81 | 0 | 1 | 0.0477 | 123% | 4.4 | 280% | **26%** |
| `shimmerless → scanlines` | — | 101 | 1 | 2 | — | — | 5.7 | 214% | **34%** |
| `shimmerless → lcd1x` | — | 96 | 2 | 2 | — | — | 6.3 | 194% | **38%** |
| `shimmerless → lcd3x` | — | 117 | 4 | 2 | — | — | 6.8 | 180% | **41%** |
| `pixellate` | — | 240 | 30 | 4 | 0.0589 | 100% | 12.3 | 100% | **74%** |
| `image-adjustment` | — | 345 | 6 | 2 | 0.0572 | 103% | 12.0 | 102% | **72%** |
| `dmg_dot_matrix → adjust` | — | 423 | 12 | 3 | — | — | 15.7 | 78% | **94%** |

Device figures are from `docs/device-results.tsv`, 69 pipelines, self-test
passed. **A dash means not measured, not zero** — archived iterations and the
two-pass references were run at their defaults only.

Desktop worst per-case IQR was 27.7%, so a desktop difference smaller than that
is noise; the device run's was 2.5%.

Four rows to read twice:

- **`lcd-turbo` v4 is the first lcd head to clear the 75% target**, at 71%
  against v3's 75%. It got there by doing *less*: brightness moved into the
  pattern gain, which is one multiply where v3 had a guarded clamp, and the
  stripe lost a divide. 11 ops and 0.7 ms.
- **`crt-turbo` v4a is 75% at its defaults and sits exactly on the target**,
  where v4b is 72%. The difference is one line — whether the warp's Jacobian is
  multiplied into the footprint — and it changes nothing at all when curvature
  is off.
- **`crt-perfect` and `dmg-perfect` cross a whole frame with everything on**
  (119% and 124%). The turbo line's worst all-on row is 95%.
- **`image-adjustment` alone is 72% of a frame**, which is the entire reason the
  vendor stacks stop fitting the moment grading is added.
