# pixel-turbo

The substrate. Everything else in the turbo line is this scaler with a pattern
multiplied in afterwards.

## The one-tap identity

`pixel-perfect` takes four NEAREST taps around the nearest texel boundary
`B = floor(p + 0.5)` and blends them with a separable weight `w`, the share of
the output pixel's footprint lying on the low side of `B`:

```
col = mix(mix(d, c, w.x), mix(b, a, w.x), w.y)
```

A bilinear fetch at texcoord `t` returns `mix(T[i], T[i+1], f)` with
`i = floor(t·TS − 0.5)` and `f = frac(t·TS − 0.5)`. Setting `i = B−1` and
`f = 1−w` gives `mix(T[B−1], T[B], 1−w)`, which is the expression above. Solving
for `t`:

```
t = (B + 0.5 - w) / TextureSize
```

So one LINEAR tap computes exactly what four NEAREST taps did. 112 ops and 4
taps become **53 ops and 1 tap**, and predicted device cost falls from 6.7 ms to
3.6 ms — 40% of a frame to 22%.

It works for any separable weight pair, which is why `lcd-turbo` can keep its
aperture weighting and still use one tap.

Edge behaviour is unchanged. At `w = 0` the sample lands on texel `B`; at
`w = 1` on `B−1`; outside the image `CLAMP_TO_EDGE` gives the same result the
four-tap form did, because both ask for texels the sampler clamps identically.

## What it cost to verify

The repo prototyped and rejected this construction before, for leaning on the
GPU's subtexel precision. That was the risk worth measuring first, before
anything was built on it.

**The scaler anchor holds at exactly 1/255**, the tolerance, across the whole
case matrix and three sources:

| source | worst over the matrix |
|---|---|
| scene | 1/255 |
| checkerboard | 1/255 |
| colour bars | 0/255 |

Mean absolute difference is 0.0–0.16 levels. The worst cases are 256x192 →
640x480 and 256x224 → 1024x768, both awkward scales where many output pixels sit
mid-transition and the bilinear weight is quantised.

`tools/tests/device.py` independently renders it through the C benchmark and
demands byte equality with the Python harness: **max delta 0**.

**This is a desktop result.** Bilinear weight precision is fixed-point and its
width is not specified; on Rogue it is likely 8-bit, giving up to ~0.5 levels of
error rather than the ~0 an Apple GPU delivers. Sitting exactly on the tolerance
means a coarser sampler could push it over. Nothing in the picture depends on
it — half a level is invisible — but the *gate* would fail, and it should be
re-checked once there is a device render to diff.

## Grading

Unchanged from `pixel-perfect`, deliberately: same folded affine, same guarded
`pow`, same order (balance before saturation, so saturation 0 really is
monochrome). Measured cost with each control on its own, over the plain scaler:

| control | ops | % of the shader with everything on |
|---|---:|---:|
| white balance (temperature, tint) | 16 | 20% |
| brightness · contrast · saturation | 22 | 27% |
| gamma | 6 | 7% |

They overlap: the balance and the affine live in the same guarded block, so the
whole grade is 29 ops, not 44. At the shipped defaults the guard is false and
the grade folds away entirely — 53 ops, 0 SFU.

`pixel-turbo` keeps the gain-and-clamp form of brightness rather than the
pattern-shallowing the other three use, because it has no pattern to shallow.
Its moiré at the shipped defaults is 0.044 against a limit of 0.40; with
everything on, gamma at 1.40 takes it to 5.784 — and `pixel-perfect` reads 5.788
on the same setting, so this is the released line's behaviour, not a regression.
