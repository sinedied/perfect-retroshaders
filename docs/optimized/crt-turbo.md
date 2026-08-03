# crt-turbo

From `crt-perfect-v13`, the latest iteration. 428 ops and 4 taps become **303
ops and 1 tap** at the shipped defaults; predicted device cost 15.9 ms →
11.3 ms, 96% of a frame to 68%.

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
white source at 320x240 → 1024x768, `crt-perfect`, `crt-turbo` and `crt-mini`
all place the image edge at the same pixel on every probe row and column.

Curvature also forces `noWarp = 0`, which switches off the source-lock term.
That is `crt-perfect`'s design and is kept: the pattern pitch is still computed
from the *flat* geometry, which is what keeps `boxSinc`'s `sin` and
`nyquistFade`'s `smoothstep` uniform-only and hoistable. `crt-perfect` records
16.5% of frame time lost the one time that stopped being true.

## Brightness

v1 shallowed the pattern, which made the control fade the effect. v2 folded it
into the gamma exponent and called that "pushing the midtones" — but
`pow(c, g/b)` divides the exponent `pow(c, g)` divides, so that was gamma with a
second name and not a brightness control at all.

v3 is the released shader's form: a plain gain on the content, clamped, before
the pattern.

```glsl
if (cp_brightness != 1.0)
    color = min(color * cp_brightness, 1.0);
```

The clamp is a non-linearity after the blend, and with one tap there is no
per-source-pixel clamp to use instead. `cp_brightness` ships at **1.25**, so the
exception is live at the default: moiré **7.256** at 480x272 → 640x480 against
a limit of 0.40, where `crt-perfect-v13` reads 0.466. Worse than v2's 4.169,
which is the honest reading — a clip has a harder edge than a curve, so more of
its energy lands in the beat band.

Two things bound it. The metric renders a 1px checkerboard, maximum energy at
the source pixel grid, which no game reaches; and the whole effect **vanishes at
an integer scale**, because every output pixel then has full coverage. The full
evidence, and the source-resolution `colour-mini` pass that removes it for 1
point of frame time, are in `docs/optimized/overview.md`.

Crawl at the defaults is 1.001, against `crt-perfect`'s 0.295 on the same
control — the one-tap scale has no per-tap clamp to fall back on, so the clip
is the only bound and it moves with coverage.

**It cost 2 ops and saved 6 SFU.** The guarded `pow` is gone at gamma 1.00,
where v2's fused exponent kept it alive whenever brightness moved.

## Where the cost actually is

| stage | ops | % of the effects budget |
|---|---:|---:|
| one LINEAR tap + pitch and band-limit setup | 291 | — *(the floor)* |
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
238.

It is uniform-derived, and the obvious response is to hoist it. Measured, that
is worth much less than it looks: pinning `OutputSize`, `TextureSize` and
`InputSize` to literals — which is perfect hoisting — removes only **23 ops**,
8%. The driver almost certainly already does it, and moving it to the vertex
shader would trade it for interpolation. What is left is genuinely
per-fragment, and reducing it means a cheaper band-limit, not a better-placed
one.

That is the next lever for this shader, and it is worth more than anything else
in either line.


## v4: crt-perfect's brightness, and what curvature really costs

**Brightness moves into the pattern gain**, as `crt-perfect` v10 has it, instead
of v3's clamp on the content before the pattern:

```glsl
vec3 gain = sqrt(max(mask * (scan * cp_brightness), 0.0));
```

| | moiré @1.25 | vs `crt-perfect` at any brightness |
|---|---:|---|
| v3, clamp the content | 7.256 | 27/255 at the default |
| **v4a, `b` in the pattern gain** | **0.480** | **1/255 at every setting** |

Seven recorded moiré exceptions become one, and the two lines stop disagreeing:
`crt-turbo-v4a` is now within 1/255 of the released shader at 1.00, 1.25 and
2.00 alike. `docs/crt-perfect.md` has why the alternatives lose.

### The two arms, and the measurement that inverted the guess

Curvature costs even at `cp_curvature = 0` because `jac` and `noWarp` are
written inside the guard, which makes `h`, `scanLocked` and `maskLocked`
per-fragment. `v4b` pins the Jacobian; two further probes pin `noWarp` and both.

| build | frame | saves |
|---|---:|---:|
| **v4a**, full fidelity | **76%** | — |
| **v4b**, `jac` pinned | **72%** | 0.60 ms |
| probe, `noWarp` pinned | 63% | 2.22 ms |
| probe, both pinned | 60% | 2.82 ms |
| v1, no curvature at all | 56% | 3.58 ms |

**`noWarp` is worth nearly three times what the Jacobian is**, which is the
reverse of the prediction. The Jacobian feeds the texture coordinate and looked
like the expensive one; the pattern's pitch and lock terms turned out to be the
larger loss, because they are what the driver was hoisting away entirely.

At `cp_curvature = 0` every arm is byte-identical, so none of this costs a user
who leaves curvature alone anything in picture — only in the frame time they
pay for carrying the code. **v4a misses the 75% target at 76%; v4b clears it at
72%**, and pinning both would reach 60%. Which arm ships is the owner's call;
`v4a` is `current` because it is the one that gives up nothing.

There is no `crt-mini-v4b`. The mini has no footprint to correct, so a b arm
would be byte-identical to `v4` — the trap `crt-perfect-v13` fell into.
