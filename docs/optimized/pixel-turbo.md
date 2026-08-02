# pixel-turbo

The substrate. Everything else in the turbo line is this scaler with a pattern
multiplied in afterwards, and `colour-mini` is this shader with the scaler taken
out.

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

## It is `sharp-shimmerless`

Found by accident, when two device pipelines that differed only in their first
pass dumped byte-identical images. Rendered through the harness at every case in
the matrix:

| | worst difference over the matrix |
|---|---:|
| `pixel-turbo` vs `sharp-shimmerless` | **1/255**, and 0/255 on 9 of the 10 cases |
| `pixel-turbo` vs `pixel-perfect` | 1/255 |

The vendored `sharp-shimmerless` reaches the same place by a different route —
it clamps the subtexel offset into a `region_range` derived from the scale
rather than deriving a footprint weight — but the function is the same one-tap
box filter. That is useful rather than a problem:

- **The reference-stack rows transfer.** Anything measured as `shimmerless → X`
  is also `pixel-turbo → X`, picture for picture.
- **The grading is what `pixel-turbo` adds**, and it adds it for 4 ops: 53
  against 49 at the shipped defaults, both 1 tap and 0 SFU.
- It is independent corroboration of the identity above, from a shader nobody
  here wrote.

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

Same folded affine as `pixel-perfect`, same order (balance before saturation, so
saturation 0 really is monochrome). Measured cost with each control on its own,
over the plain scaler:

| control | ops | % of the shader with everything on |
|---|---:|---:|
| white balance (temperature, tint) | 16 | 20% |
| brightness · contrast · saturation | 22 | 27% |
| gamma | 6 | 7% |

They overlap: the balance and the affine live in the same guarded block, so the
whole grade is 29 ops, not 44. At the shipped defaults the guard is false and
the grade folds away entirely — 53 ops, 0 SFU.

**Brightness changed in v2**, from a gain-and-clamp to a midtone push folded
into the gamma exponent, so the control means the same thing in all four turbo
shaders:

```glsl
if (abs(pp_gamma - 1.0) > 0.001 || abs(pp_brightness - 1.0) > 0.001)
    col = pow(max(col, 1e-8), vec3(pp_gamma / max(pp_brightness, 1e-3)));
```

The guard is on the two parameters separately, not on their ratio. `max()` of
two literals does not constant-fold in `spirv-opt`, so a guard reading
`abs(gamma / max(brightness, 1e-3) - 1.0) > 0.001` kept the `pow` in the shader
at settings where it does nothing — 68 ops at the defaults instead of 53.

`pp_brightness` ships at 1.00, so the moiré exception in `docs/optimized.md`
does not apply to `pixel-turbo` at its defaults: 0.044 against a limit of 0.40.
With everything on, gamma at 1.40 takes it to 5.784 — and `pixel-perfect` reads
5.788 on the same setting, so that is the released line's behaviour, not a
regression.

If you raise brightness or gamma and the scale is not an integer, the clean
place to do it is `colour-mini` at source resolution in front of this shader.
See `docs/optimized/colour-mini.md`.
