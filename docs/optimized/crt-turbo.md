# crt-turbo

From `crt-perfect-v12`, the latest iteration. 449 ops and 4 taps become **301
ops and 1 tap** at the shipped defaults; predicted device cost 15.9 ms →
11.2 ms, 96% of a frame to 67%.

Same eight parameters as `crt-perfect`, same defaults, same picture: at
brightness 1.00 the two differ by at most **1/255** over the whole case matrix.

## v1 cut curvature and the slot mask. That was wrong.

v1's reasoning was that curvature is 70% of what `crt-perfect`'s effects cost
and is the setting that provably breaks the frame budget. Both halves are true
and the conclusion did not follow, because **the parameter costs nothing when it
is not used**:

| `crt-perfect-v12` build | ops |
|---|---:|
| curvature code present, `cp_curvature = 0` | 449 |
| curvature code deleted | **449** |
| slot mask available, `cp_mask_type = 1` | 449 |
| slot mask selected, `cp_mask_type = 2` | 471 |

Both sit behind a uniform guard, so the driver takes the branch once per draw
rather than once per fragment, and `spirv-opt` folds the untaken side away
entirely. Cutting them removed two features and bought nothing. Both are back in
v2, at their `crt-perfect` defaults — curvature off, aperture grille.

The budget is still real: with curvature at 0.15 the shader is 394 ops, a
predicted 14.0 ms, **84% of a frame**. That is the one row in either line over
the 75% target, and it is opt-in.

## Curvature is simpler with one tap

The four-tap version warped four texcoords and recomputed the border weights.
The one-tap version warps `uv` once, scales the footprint by the warp's
Jacobian, and feeds the same texcoord identity:

```glsl
uv  = c * (1.0 + cp_curvature * r2) * norm * 0.5 + 0.5;
jac = (1.0 + cp_curvature * (vec2(3.0, 1.0) * cc.x
                           + vec2(1.0, 3.0) * cc.y)) * norm;
vec2 h = max(0.4995 * InputSize / OutputSize * jac, 1e-6);
```

so the box average stays exact under a varying local magnification.

**The corner mask is a linear ramp instead of a `smoothstep` pair.**
`clamp(uv/e, 0, 1) * clamp((1-uv)/e, 0, 1)` where `e` is one output pixel, in
place of `smoothstep(0, e, uv) * smoothstep(0, e, 1-uv)`. At one pixel wide the
two are indistinguishable, and the tube outline is identical: measured on a flat
white source at 320x240 → 1024x768, `crt-perfect-v12`, `crt-turbo-v2` and
`crt-mini-v2` all place the image edge at the same pixel on every probe row and
column.

Curvature also forces `noWarp = 0`, which switches off the source-lock term.
That is `crt-perfect`'s design and is kept: the pattern pitch is still computed
from the *flat* geometry, which is what keeps `boxSinc`'s `sin` and
`nyquistFade`'s `smoothstep` uniform-only and hoistable. `crt-perfect` records
16.5% of frame time lost the one time that stopped being true.

## Brightness

v1 shallowed the pattern. v2 pushes the midtones, folded into the gamma
exponent, because "brightness" should brighten the picture rather than fade the
effect:

```glsl
if (abs(cp_gamma - 1.0) > 0.001 || abs(cp_brightness - 1.0) > 0.001)
    color = pow(max(color, 1e-8), vec3(cp_gamma / max(cp_brightness, 1e-3)));
```

Applied to the blended colour, which is a non-linearity after the blend and
therefore beats. `cp_brightness` ships at **1.25**, so the exception is live at
the default: moiré 4.169 at 480x272 → 640x480 against a limit of 0.40, where
`crt-perfect-v12` reads 0.494.

That number is the synthetic worst case — the metric renders a 1px checkerboard.
On the 18 real screenshots in `retroshader-lab/public/samples` the same artifact
is **1.50 levels RMS, p99 of 7, and exactly 0 at an integer scale**. The full
evidence, and the two-pass assembly that removes it for 1 point of frame time,
are in `docs/optimized.md`.

Crawl is unaffected: 0.962 at the defaults against `crt-perfect-v12`'s 1.111.
The curve is a fixed function of the blended value, so it scrolls with the
picture instead of sitting on the screen.

## Where the cost actually is

| stage | ops | % of the effects budget |
|---|---:|---:|
| one LINEAR tap + pitch and band-limit setup | 289 | — *(the floor)* |
| curvature | 73 | 70% |
| slot mask, when selected | 22 | 21% |
| brightness · gamma | 6 | 6% |
| scanlines | 2 | 2% |
| RGB mask | 2 | 2% |

**The patterns are 4 ops.** Everything else in the floor is the machinery that
decides where to put them and how hard to band-limit them: `scanPitch`,
`scanLocked`, `maskPitch`, `maskLocked`, two `nyquistFade` smoothsteps and two
`boxSinc` calls, all of which sit outside the guards and run whether the
patterns are on or off. The scale alone is 53 ops, so that machinery is roughly
236.

It is uniform-derived, and the obvious response is to hoist it. Measured, that
is worth much less than it looks: pinning `OutputSize`, `TextureSize` and
`InputSize` to literals — which is perfect hoisting — removes only **23 ops**,
8%. The driver almost certainly already does it, and moving it to the vertex
shader would trade it for interpolation. What is left is genuinely
per-fragment, and reducing it means a cheaper band-limit, not a better-placed
one.

That is the next lever for this shader, and it is worth more than anything else
in either line.
