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
| `pixel-perfect` *(the four-tap line, superseded)* | 112 | four NEAREST taps, box blend **(floor)** → white balance **(55%)** → brightness · contrast · saturation **(75%)** → gamma **(20%)** |
| **`pixel-perfect` v8** *(released, was pixel-turbo v3)* | 53 | one LINEAR tap, box blend **(floor)** → white balance **(55%)** → brightness · contrast · saturation **(75%)** → gamma **(20%)** |
| **`colour-mini` v3** *(released)* | 20 | one tap at 1:1 **(floor)** → white balance **(55%)** → brightness · contrast · saturation **(75%)** → gamma **(20%)** |
| `crt-perfect` v10 *(the four-tap line, superseded)* | 421 | four taps + pitch, lock, Nyquist **(floor)** → curvature **(68%)** → slot mask **(21%)** → gamma **(5%)** → scanlines **(1%)** → RGB mask **(1%)** |
| `crt-turbo` v1 | 276 | one tap + band-limit **(floor)** → gamma **(60%)** → scanlines **(20%)** → RGB mask **(20%)** *(no curvature, no slot mask)* |
| `crt-turbo` v2 · v3 | 289 | one tap + band-limit **(floor)** → curvature **(69%)** → slot mask **(20%)** → gamma **(5%)** → scanlines **(1%)** → RGB mask **(1%)** |
| `crt-turbo` v4a *(the arm that was not taken)* | 289 | one tap + band-limit **(floor)** → curvature **(69%)** → slot mask **(20%)** → brightness · gamma **(5%)** → scanlines **(1%)** → RGB mask **(1%)** |
| **`crt-perfect` v14** *(released, was crt-turbo v4b)* | 285 | as v4a, with the warp's Jacobian pinned: curvature **(65%)** → slot mask **(23%)** → brightness · gamma **(6%)** → scanlines **(2%)** → RGB mask **(2%)** |
| `crt-mini` v2 · v3 · v4 | 252 | one tap at 1:1 + band-limit **(floor)** → curvature **(65%)** → slot mask **(23%)** → brightness · gamma **(6%)** → scanlines **(2%)** → RGB mask **(2%)** |
| **`crt-mini` v5** *(released)* | 240 | one tap at 1:1 + band-limit **(floor)** → slot mask **(67%)** → gamma **(18%)** → scanlines **(6%)** → RGB mask **(6%)** → brightness **(3%)** *(no curvature)* |
| **`unflat-mini` v1** *(released)* | 25 | one tap at 1:1 **(floor)** → barrel warp + tube edge **(all of it, and it is 25 ops)** |
| `lcd-perfect` v6 *(the four-tap line, superseded)* | 249 | four taps, aperture-weighted **(floor)** → RGB stripes + cast correction **(87%)** → mesh **(8%)** → brightness **(1%)** → gamma **(7%)** |
| `lcd-turbo` v1 · v2 · v3 | 192 | one tap, aperture-weighted **(floor)** → RGB stripes + cast correction **(88%)** → mesh **(7%)** → brightness · gamma **(6%)** |
| **`lcd-perfect` v10** *(released, was lcd-turbo v4)* | 190 | one tap, aperture-weighted **(floor)** → RGB stripes + cast correction **(87%)** → mesh **(8%)** → brightness **(1%)** → gamma **(7%)** |
| `lcd-mini` v2 · v3 | 122 | one tap at 1:1 **(floor)** → RGB stripes + cast correction **(88%)** → mesh **(7%)** → brightness · gamma **(6%)** |
| **`lcd-mini` v4** *(released)* | 120 | one tap at 1:1 **(floor)** → RGB stripes + cast correction **(87%)** → mesh **(7%)** → brightness **(1%)** → gamma **(6%)** |
| `dmg-perfect` v10c *(the four-tap line, superseded)* | 194 | four taps, box + dot aperture **(floor)** → cast shadow, +4 taps **(74%)** → grid **(18%)** |
| **`dmg-perfect` v11** *(released, was dmg-turbo v3)* | 140 | one tap, box + dot aperture **(floor)** → cast shadow, +1 tap **(83%)** → grid **(16%)** |
| **`dmg-mini` v3** *(released)* | 120 | one tap at 1:1 + dot aperture **(floor)** → cast shadow, +1 tap **(83%)** → grid **(16%)** |

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
default and all-on rows differ. **Every timing here is the device**, a Trimui
Brick at 320x240 into 1024x768; the desktop column is gone because the render
pass around these shaders costs more than the shaders and it separated nothing.

`vs pix.` is against `pixellate`, which ships on the target and holds 60fps, so
higher is cheaper. **frame** is the share of one 60fps frame (16.67 ms).

| Shader | ops | SFU | tex | device ms | vs pix. | frame |
|---|---:|---:|---:|---:|---:|---:|
| **`pixel-perfect` v8** *(released)*, defaults | 53 | 0 | 1 | 4.4 | 282% | **26%** |
| &nbsp;&nbsp;all on | 82 | 6 | 1 | 6.6 | 186% | **40%** |
| `pixel-perfect` v7 *(superseded, four taps)* | 112 | 0 | 4 | — | — | — |
| **`colour-mini` v3** *(released)* | 20 | 0 | 1 | 3.1 | 396% | **19%** |
| &nbsp;&nbsp;all on | 49 | 6 | 1 | 5.1 | 243% | **30%** |
| **`crt-perfect` v14** *(released)*, defaults | 292 | 8 | 1 | 12.1 | 101% | **73%** |
| &nbsp;&nbsp;all on | 357 | 14 | 1 | 15.0 | 82% | **90%** |
| `crt-turbo` v4a *(arm not taken)* | 296 | 8 | 1 | 12.6 | 98% | **75%** |
| `crt-perfect` v10 *(superseded, four taps)* | 428 | 8 | 4 | — | — | — |
| **`crt-mini` v5** *(released)*, defaults | 247 | 8 | 1 | 8.0 | 154% | **48%** |
| &nbsp;&nbsp;all on | 251 | 14 | 1 | 10.1 | 122% | **61%** |
| `crt-mini` v4 *(superseded, had curvature)* | 259 | 8 | 1 | 10.5 | 117% | **63%** |
| **`unflat-mini` v1** *(released)* | 25 | 0 | 1 | 4.2 | 296% | **25%** |
| **`lcd-perfect` v10** *(released)*, defaults | 275 | 17 | 1 | 11.9 | 103% | **71%** |
| &nbsp;&nbsp;all on | 280 | 23 | 1 | 13.4 | 92% | **80%** |
| `lcd-perfect` v6 *(superseded, four taps)* | 334 | 17 | 4 | — | — | — |
| **`lcd-mini` v4** *(released)*, defaults | 209 | 13 | 1 | 7.9 | 156% | **47%** |
| &nbsp;&nbsp;all on | 214 | 19 | 1 | 9.4 | 131% | **56%** |
| **`dmg-perfect` v11** *(released)*, defaults | 168 | 6 | 1 | 8.4 | 147% | **50%** |
| &nbsp;&nbsp;all on | 273 | 6 | 2 | 12.5 | 98% | **75%** |
| `dmg-perfect` v10c *(superseded, four taps)* | 267 | 6 | 4 | — | — | — |
| **`dmg-mini` v3** *(released)*, defaults | 148 | 6 | 1 | 7.4 | 167% | **44%** |
| &nbsp;&nbsp;all on | 253 | 6 | 2 | 11.5 | 107% | **69%** |
| | | | | | | |
| `sharp-shimmerless` | 49 | 0 | 1 | 3.9 | 319% | **23%** |
| `dmg_dot_matrix` | 78 | 6 | 1 | 5.2 | 238% | **31%** |
| `barrel-distortion` | 81 | 0 | 1 | 4.4 | 279% | **26%** |
| `shimmerless → scanlines` | 101 | 1 | 2 | 5.7 | 214% | **34%** |
| `shimmerless → lcd1x` | 96 | 2 | 2 | 6.3 | 195% | **38%** |
| `shimmerless → lcd3x` | 117 | 4 | 2 | 6.8 | 180% | **41%** |
| `pixellate` | 240 | 30 | 4 | 12.3 | 100% | **74%** |
| `image-adjustment` | 345 | 6 | 2 | 12.0 | 102% | **72%** |
| `dmg_dot_matrix → adjust` | 423 | 12 | 3 | 15.7 | 78% | **94%** |
| `crt-mini → unflat-mini` | 272 | 8 | 2 | 10.4 | 118% | **63%** |
| `pixel-perfect → crt-mini` | 300 | 8 | 2 | 13.7 | 90% | **82%** |
| `res-independent-scanlines` | 52 | 1 | 1 | 3.3 | 371% | **20%** |
| `barrel → scanlines` | 133 | 1 | 2 | 6.3 | 197% | **38%** |

Device figures are from `docs/device-results.tsv`, 79 pipelines, self-test
passed. Run-to-run reproducibility on the repeated rows is ±0.35%, and the worst
per-case IQR was 2.5%. **A dash means not measured, not zero** — the superseded
iterations and the two-pass references were run at their defaults only.

Five rows to read twice:

- **The vendor CRT stacks are cheaper than `crt-perfect`, and the README used to
  say the opposite.** `res-independent-scanlines` is **3.3 ms** against
  `crt-perfect`'s 12.1, and the two-pass `barrel → scanlines` is **6.3 ms**
  against 15.0 with everything on. The old figures were desktop-measured and had
  the second one **the wrong way round**. They buy their speed by doing almost
  nothing - one sine, no scaling, no mask, no band-limiting - which is the
  honest way to state the trade, and it is now stated that way.

- **Moving curvature out of `crt-mini` took it from 10.5 ms to 7.9**, a 24% cut
  for deleting a block that was switched off. That is the clearest measurement
  in this file of what carrying an option costs when the option writes something
  the rest of the shader depends on.
- **And the split pays for itself.** `crt-mini → unflat-mini` with curvature
  *on* is 10.4 ms — cheaper than the old single-pass `crt-mini` v4 was with
  curvature **off**.
- **Every released shader now fits in a frame at its defaults**, worst 73%. The
  four-tap line it replaces was 88–96%, and crossed a whole frame with
  everything on.
- **A stack is not automatically cheaper.** `pixel-perfect → crt-mini` is 13.7 ms
  against `crt-perfect`'s 12.1: each pass re-reads the screen. Compose for
  flexibility and for curvature, not for speed.
