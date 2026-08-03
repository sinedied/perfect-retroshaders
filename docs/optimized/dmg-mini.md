# dmg-mini

`dmg-turbo` with the scaler removed: the dot matrix, the cell shadow and the
grading, at 1:1. **148 ops and 2 taps** against `dmg-turbo`'s 168; predicted
device cost 7.2 ms, 43% of a frame against 47%.

Read `docs/optimized/mini.md` first for the contract every mini shares.

## Two taps, not one

Every other mini takes a single tap. This one needs two, and it is the same
second tap `dmg-turbo` needs: the cell shadow reads how driven the *casting*
cell is, which is a different texel from the one being shaded.

```glsl
float casterLum = dot(COMPAT_TEXTURE(Source, q).rgb, LUMA);
```

`dmg-perfect` spent four taps on that, taking the luma of each neighbour and
interpolating. `dot` is linear, so it commutes with `mix` and the luma of the
blend is the blend of the lumas — one tap does it exactly. See
`docs/optimized/dmg-turbo.md`, which also records the float32 knife edge the
four-tap form needed fifteen lines to explain and this form does not have.

The shadow is off at the shipped default, so the second tap is only paid when
`dp_shadow > 0`. At the defaults this is 148 ops and 2 declared taps of which
one is live.

## What removing the scaler bought

20 ops, and that is all. `dmg`'s floor is mostly the dot-matrix geometry —
which cell, where in the cell, how wide the gap — and none of that changes with
who did the scaling.

| stage | ops | tex | share of the shader with everything on |
|---|---:|---:|---:|
| one tap at 1:1 + cell geometry | 120 | 1 | 47% |
| dot aperture over the substrate | 21 | 0 | 8% |
| cast shadow | 106 | +1 | 42% |
| brightness · gamma | 6 | 0 | 2% |
| white balance | 0 | 0 | 0% |

**The shadow is 42% of the shader and the only reason for the second tap.**
Turning it off is by far the largest saving available here, and it is already
the default.

## The golden path it has to beat

The owner's reference for DMG is `dmg_dot_matrix` plus `image-adjustment`:

| stack | passes | ops | tex | device ms | frame |
|---|---:|---:|---:|---:|---:|
| `dmg_dot_matrix` | 1 | 78 | 1 | *4.4* | *26%* |
| `dmg_dot_matrix → adjust` | 2 | 423 | 3 | *16.3* | ***98%*** |
| `dmg-mini` | 1 | 148 | 2 | *7.2* | *43%* |
| `pixel-turbo → dmg-mini` | 2 | 201 | 3 | *9.5* | *57%* |
| `colour-mini @src → pixel-turbo → dmg-mini` | 3 | 221 | 4 | *9.6* | *58%* |
| `dmg-turbo` | 1 | 168 | 2 | *7.8* | *47%* |

All predicted.

The bare vendor shader is cheaper. The moment grading is added it is not, by a
factor of two: `image-adjustment` alone is 345 ops. A full graded, box-scaled,
band-limited dot matrix is 58% of a frame in three passes, or 47% in one.

## Measured

| | worst over the matrix |
|---|---:|
| moiré, defaults | 0.435 |
| moiré, everything on | 1.485 |
| crawl, defaults | 0.161 |
| crawl, everything on | 1.711 |

One exception is recorded, 0.435 at 480x272 → 1024x768. `dp_gamma` ships at
1.20, so this shader carries a `pow` after the tap at its defaults; without a
box blend in front of it there is much less structure for that to beat against
than in `dmg-turbo`, which reads 0.459 on the same measure with three exceptions.

Crawl at defaults is 0.161 against `dmg-turbo`'s 0.668 — the dot pattern is
screen-locked in both, but a bilinear upscale gives it less to beat against.

Against `dmg-perfect-v10c` the difference is 157/255, and that number means
nothing: it is a shader with a box scaler being compared to one without.


## The standalone shadow, and why it is left alone

With no scaler in front, the mini's shadow is weak: it reaches a factor of 0.510
where `dmg-perfect` reaches 0.299. The cause is structural. `dmg-perfect` takes
`paper` from a **box** average — blocky, constant across a source cell — while
`casterLum` is a **bilinear** tap; the shadow lives on the contrast between
them. Standalone, the mini's `area` is itself bilinear, so paper and caster
track each other and the ratio flattens toward 1.

**Behind a scaler it is right.** Measured with the C benchmark, which renders
real chains: `pixel-turbo → dmg-mini` reaches **0.194** against `dmg-perfect`'s
0.299, rms 2.99% of the factor field. The box-scaled input restores the blocky
reference on its own.

A fix for the standalone case was built and rejected. Sampling `paper` at the
source cell centre costs +7 ops and a third tap when the shadow is on, and moves
the standalone field **0.03–0.14% closer** to `dmg-perfect` on eight cases and
*further* on two. That is noise, and it is not worth a tap.
