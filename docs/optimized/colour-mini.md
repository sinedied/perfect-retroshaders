# colour-mini

`pixel-turbo` with the scaler removed: one tap at 1:1 and the grade. 20 ops at
its defaults, 49 with everything on, and it is the cheapest shader in the
repository.

Read `docs/optimized/mini.md` first for the contract every mini shares.

## Why it exists

Two reasons, and the second is the important one.

**It replaces `image-adjustment`.** The vendored RetroArch grading pass is 345
ops and 2 taps — a predicted 11.9 ms, **71% of a frame on its own** — and it is
what turns every otherwise-cheap reference stack into one that does not fit:

| stack | frame |
|---|---:|
| `shimmerless → lcd1x` | *34%* |
| `shimmerless → lcd1x → adjust` | *105%* |

`colour-mini` does the same job with the same controls in 20 ops.

**It is where brightness belongs.** The turbo line applies brightness as a gain
and clamps it after the blend, which is the one thing `AGENTS.md` prohibits,
taken deliberately as a recorded exception. Put the same gain at *source*
resolution, in front of the scaler, and it is per source pixel, which is legal
and exact — the same status the released line's per-tap clamp has.

Measured over the 18 real screenshots in `retroshader-lab/public/samples` at
1024x768, against the exact answer (`box_average(grade(source))` computed in
float):

| route | RMS, levels | p99 | max |
|---|---:|---:|---:|
| one pass — grading after the blend, brightness 1.25 | **1.50** | 7 | 21 |
| two passes — `colour-mini @src` → `pixel-turbo` | **0.11** | 1 | 1 |

The residual 0.11 is the 8-bit intermediate render target rounding, and nothing
else.

## The cost of putting it first

A pass declared `minarch_shaderN_upscale = 1` renders at the source size. At
320x240 → 1024x768 that is 76 800 pixels against 786 432 — **9.8%** — so the
fragment cost scales by the same factor:

| stack | passes | device ms | frame |
|---|---:|---:|---:|
| `pixel-turbo` alone | 1 | *3.6* | *22%* |
| `colour-mini @src → pixel-turbo` | 2 | *3.7* | *22%* |
| `pixel-turbo → colour-mini` *(wrong order)* | 2 | *4.9* | *29%* |

**0.2 ms, one point of frame time.** That is the whole price of removing the
exception, and it is why the `@src` pipelines exist in
`tools/device/pipelines/`.

The wrong order is measured too, and is worth keeping: at 1:1 behind the scaler
`colour-mini` is 7 points more expensive *and* carries the artifact. There is no
reason to run it there.

## Controls

Identical to `pixel-turbo`'s and in the same order — `pp_` prefixed, geometry
first and colour last, ending `pp_brightness` then `pp_gamma`:

| control | ops | share of the shader with everything on |
|---|---:|---:|
| white balance (temperature, tint) | 16 | 33% |
| brightness · contrast · saturation | 22 | 45% |
| gamma | 6 | 12% |

They share one guarded block, so the whole grade is 29 ops rather than 44. At
the shipped defaults the guard is false and every one of them folds away: **20
ops, 1 tap, 0 SFU** — the tap, the clamp and nothing else.

## Measured

| | worst over the matrix |
|---|---:|
| moiré, defaults | 0.182 |
| moiré, everything on | 2.005 |
| crawl, defaults | 0.021 |
| crawl, everything on | 0.571 |

The defaults are neutral, so what the moiré figure measures is the frontend's
bilinear upscale, not this shader. `crawl` at 0.021 is the lowest in either
line — with no pattern there is nothing screen-locked for the picture to move
underneath.

The passthrough anchor is the real check: at 1:1 with the grade neutral, the
output must equal the input exactly, verified at 320x240, 256x224 and 480x272.
