# crt-turbo

From `crt-perfect-v12`, the latest iteration. 449 ops and 4 taps become **282
ops and 1 tap**; predicted device cost 15.9 ms → 10.6 ms, 96% of a frame to 64%.

At any brightness of 1.00 or below and with curvature off, `crt-turbo` and
`crt-perfect-v12` differ by at most 1/255.

## What was removed

**Curvature.** It was 71 of the 104 ops `crt-perfect`'s effects add — 68% of
them — and it is the setting the owner reports provably breaking the frame
budget. It also forces `noWarp = 0`, which switches off the locked path that
keeps the patterns cheap, and it makes the border-mask `smoothstep` pair live.
Removing the parameter removes all of it.

Its absence is why `crt-turbo` has six parameters where `crt-perfect` has eight,
and why the two cannot be compared on the "everything on" row of
`docs/optimized.md`: with curvature at 0.15 the moiré metric is measuring a
warped image, which `docs/measurement.md` records as invalid.

**The slot mask.** `cp_mask_type` selected off / aperture grille / slot grille;
the slot variant costs a `floor()` and a `mod()` per fragment, 22 ops, for a
second look. One mask type was explicitly allowed, so the aperture grille — the
default — is the only one. `cp_rgb_mask = 0` still turns it off.

**Three of the four taps**, by the one-tap identity in `docs/optimized/pixel-turbo.md`.
With curvature gone, `crt-perfect`'s scaler is exactly `pixel-perfect`'s — the
family test already asserted that — so the substitution is the same one.

## Brightness

Same problem and same fix as `lcd-turbo`: `crt-perfect-v12` applies brightness
per tap and clamps there, which one tap cannot do. Both patterns are already
peak-normalised to 1, so shallowing them works unchanged:

```
float bs  = max(cp_brightness, 0.0);
vec3 pat  = 1.0 - (1.0 - mask * scan) / max(bs, 1.0);
vec3 gain = sqrt(max(pat * min(bs, 1.0), 0.0));
```

| brightness | v12 mean level | turbo mean level | max diff |
|---:|---:|---:|---:|
| 0.50 | 70.66 | 70.66 | **1/255** |
| 1.00 | 99.95 | 99.95 | **1/255** |
| 1.25 *(default)* | 105.45 | 106.12 | 25/255 |
| 2.00 | 116.66 | 114.56 | 69/255 |

The closest match of the three panel shaders — under a level apart at the
shipped default.

## Measured

**Moiré needs no exception at all.** Worst over the whole matrix is 0.306
against a limit of 0.40. `crt-perfect-v12` carries two exceptions, 0.466 and
0.434; both are gone.

Crawl at full mask depth is 1.403 / 0.914, which is `crt-perfect-v12`'s own
figure to three decimals — the two are bit-identical at brightness 1.00, where
that regime is measured. Inherited, not new.

The scanline lock is checked directly: one cycle per source line at 320x240 and
256x224, measured by FFT down the centre of the frame, reading 1.000 at both.

## Where the cost actually is

| stage | ops | % of the shader with everything on |
|---|---:|---:|
| one LINEAR tap + pitch and band-limit setup | 276 | 97% |
| gamma | 6 | 2% |
| scanlines | 2 | 0.7% |
| RGB mask | 2 | 0.7% |
| brightness | 0 | 0% |

**The patterns are 4 ops.** Everything else is the machinery that decides where
to put them and how hard to band-limit them: `scanPitch`, `scanLocked`,
`maskPitch`, `maskLocked`, two `nyquistFade` smoothsteps and two `boxSinc`
calls, all of which sit outside the guards and run whether the patterns are on
or off. The scale alone is 53 ops, so that machinery is roughly 223.

It is uniform-derived, and the obvious response is to hoist it. Measured, that
is worth much less than it looks: pinning `OutputSize`, `TextureSize` and
`InputSize` to literals — which is perfect hoisting — removes only **23 of the
282 ops**, 8%. The driver almost certainly already does it, and moving it to the
vertex shader would trade it for interpolation. What is left is genuinely
per-fragment, and reducing it means a cheaper band-limit, not a better-placed
one.

That is the next lever for this shader, and it is worth more than anything else
in the turbo line.
