# crt-mini

`crt-turbo` with the scaler removed: scanlines, the RGB mask, curvature and the
slot grille, at 1:1. **264 ops and 1 tap** against `crt-turbo`'s 301; predicted
device cost 10.1 ms, 60% of a frame against 67%.

Read `docs/optimized/mini.md` first for the contract every mini shares.

## It saves the least, and that is the finding

37 ops. The reason is that almost nothing in `crt`'s floor is the scale:

| | `crt-turbo` | `crt-mini` |
|---|---:|---:|
| floor, patterns neutral | 289 | 252 |
| one LINEAR tap, box-weighted | 53 | — |
| pitch, lock, `nyquistFade`, `boxSinc` | ~236 | ~232 |

The band-limit machinery has to run either way: it is what decides how hard to
fade the scanlines and the mask as their pitch approaches Nyquist, and that
depends on the output geometry, not on who did the scaling. Removing the scaler
removes the scaler and nothing else.

So `crt-mini` is for composition, not for speed. `pixel-turbo → crt-mini` is 74%
of a frame against `crt-turbo`'s 67% — **the chain is the more expensive way to
get the same picture**, and it exists so a user can put a different scaler,
no scaler, or a source-resolution colour pass into the same pipeline.

## Curvature without a footprint

`crt-turbo` warps `uv`, then scales its box footprint by the warp's Jacobian so
the area average stays exact under a varying local magnification. `crt-mini` has
no footprint — it has one tap at a coordinate — so the Jacobian is dropped and
the sampler's own LINEAR filtering smooths the warp instead. That is 12 ops
cheaper than `crt-turbo`'s curvature (61 against 73) and it is why the mini's
sampler is declared LINEAR rather than NEAREST.

The rest is identical, including the two things worth not losing:

- **`noWarp = 0` under curvature**, which switches off the source-lock term.
- **The pattern pitch is computed from the flat geometry**, which keeps
  `boxSinc`'s `sin` and `nyquistFade`'s `smoothstep` uniform-only and hoistable.
  `crt-perfect` records 16.5% of frame time lost the one time that stopped being
  true.

**The tube outline is identical to `crt-perfect-v12`.** Measured on a flat white
source at 320x240 → 1024x768, `crt-perfect-v12`, `crt-turbo-v2` and `crt-mini-v2`
place the image edge at the same pixel on every probe row and column — x 27..996
and y 20..747 at the 8% and 92% lines, edge to edge at the centres.

Curvature is free when off, and the corner mask with it: 0 ops at
`cp_curvature = 0`, 61 when selected. Same for the slot grille, 0 at
`cp_mask_type = 1` and 22 at 2. Both are behind uniform guards.

## Where the cost is

| stage | ops | share of the shader with everything on |
|---|---:|---:|
| one tap at 1:1 + pitch and band-limit setup | 252 | 73% |
| curvature | 61 | 18% |
| slot mask, when selected | 22 | 6% |
| brightness · gamma | 6 | 2% |
| scanlines | 2 | 0.6% |
| RGB mask | 2 | 0.6% |

The patterns are 4 ops. Everything above them is band-limiting, and reducing it
means a cheaper band-limit rather than a better-placed one. It is the first
lever in `docs/optimized.md` and it applies to `crt-turbo` and `crt-mini`
equally.

## Measured

| | worst over the matrix |
|---|---:|
| moiré, defaults | 0.977 |
| moiré, everything on | *18.617* |
| crawl, defaults | 0.814 |
| crawl, everything on | 4.235 |

**0.977 against `crt-turbo`'s 4.169**, and the difference is the missing box
blend rather than anything this shader does better: a bilinear upscale is smooth,
so the brightness curve — which ships at 1.25 and is a non-linearity after the
blend — has much less structure to beat against. Two exceptions are recorded,
0.460 and 0.977.

*The 18.617 is a measurement artifact, not a defect.* "Everything on" includes
curvature at 0.15, and `docs/measurement.md` records that a row-mean metric is
invalid on a warped image. `crt-perfect-v12` reads 32.216 on the same row.

Against `crt-perfect-v12` the difference is 120/255 at brightness 1.00, and that
number means nothing: it is a shader with a box scaler being compared to one
without. The comparison that matters is `pixel-turbo → crt-mini` against
`crt-turbo`, and that is a device measurement, not a harness one.
