# lcd-turbo

From `lcd-perfect-v8`, the latest iteration. 351 ops and 4 taps become **284 ops
and 1 tap**; predicted device cost 15.0 ms → 10.7 ms, 90% of a frame to 64%.

The saving is almost entirely taps. The arithmetic is nearly the same shader,
and that is the point: **at brightness 1.00, `lcd-turbo` and `lcd-perfect-v8`
differ by at most 1/255 over the whole case matrix.**

## The aperture weighting stays, and one tap is still enough

The obvious cut was the aperture-weighted blend. `lcd-perfect` does not weight
its taps by footprint overlap; it weights them by the mesh's own aperture,
because the mesh's dark line sits on the cell boundary and so does the scaler's
soft transition pixel — the two correlate, and a plain area blend leaves the
correlation in the picture as a beat.

Dropping it and using the area weights measured:

| | worst moiré over the matrix |
|---|---:|
| plain area blend | **1.890** |
| aperture-weighted | **0.118** |

against a limit of 0.40. So it stays.

It costs nothing in taps. The one-tap identity — `t = (B + 0.5 - w)/TextureSize`
returns `mix(T[B], T[B-1], w)` — holds for *any* separable weight pair, so the
aperture weight `w = clamp((AB - Alo)/I, 0, 1)` goes straight into the texcoord.
The only thing lost against the four-tap form is the ability to do something
non-linear to each tap before the blend, which is what the brightness work below
is about.

## Brightness could not stay a gain

`lcd-perfect-v8` applies brightness to each tap and clamps it there:

```glsl
float sb = pow(max(lp_brightness, 1e-4), 0.5 / max(lp_gamma, 1e-3));
vec3 a = min(texture(...).rgb * sb, 1.0);   // x4
```

Per tap, the clamp is per *source* pixel, identical for every output pixel
covering it, so it cannot vary with coverage and cannot beat. With one tap there
is no per-tap point: the texture unit has already blended.

Four formulations were tried, in order:

| form | result |
|---|---|
| `min(blend × b, 1)` | **1.860 moiré.** A clip after the blend — the design rule doing exactly what it says. |
| `min(pattern × b, 1)` | Moiré fine — the bound is position-only, so it cannot vary with coverage. But the pattern is already peak-normalised to 1, so any `b > 1` just flattens its top, and those knees **crawl at 0.719** against a limit of 0.35. |
| shallow the pattern *(v1)* | Clean on every metric, and wrong: the control fades the effect instead of brightening the picture. |
| `pow(blend, gamma/b)` *(v2, shipped)* | **1.860 moiré.** Smooth, nothing clips, 0 stays 0 and 1 stays 1 — but still a non-linearity after the blend. |

v2 ships the fourth, on the owner's call, as a recorded exception:

```glsl
if (abs(lp_gamma - 1.0) > 0.001 || abs(lp_brightness - 1.0) > 0.001)
    color = pow(max(color, 1e-8), vec3(lp_gamma / max(lp_brightness, 1e-3)));
```

`lp_brightness` ships at 1.25, so it is live at the default. The checkerboard
figure of 1.860 is the synthetic worst case; on real screenshots the artifact is
1.50 levels RMS and exactly 0 at an integer scale, and a source-resolution
`colour-mini` pass in front removes it for 1 point of frame time. Full evidence
in `docs/optimized.md`.

Measured against `lcd-perfect-v8` on the same source:

| brightness | v8 mean level | turbo mean level | max diff |
|---:|---:|---:|---:|
| 1.00 | 89.54 | 89.54 | **1/255** |
| 1.25 *(default)* | 94.47 | 96.19 | 22/255 |

Identical at 1.00, and the difference above it is a level shift with no
structure — RMS 4.76 over the frame. The difference in kind: `v8` brightens by
clipping highlights, `turbo` by lifting the midtones, which cannot clip at all.

## Per-effect cost

Each measured on its own over the plain scaler.

| stage | ops | SFU | % of the effects budget |
|---|---:|---:|---:|
| one LINEAR tap, aperture-weighted | 190 | 13 | — *(the floor)* |
| RGB stripes + cast correction | 82 | 4 | 88% |
| mesh | 7 | 0 | 8% |
| brightness · gamma | 6 | 6 | 7% |

The stripe block is the only remaining target of any size, and most of it is the
colour-cast correction — which is non-negotiable, so it needs a cheaper form
rather than removal. `lcd-mini` is what is left when the scaler goes: 120 ops of
floor instead of 190.

## Inherited, not new

The crawl exception at full stripe depth (1.270 at GBA, 0.790 at GBC) is
`lcd-perfect-v8`'s own figure to two decimals — the two shaders are
bit-identical at brightness 1.00, which is where that regime is measured. It is
the stripe's aperture error, which `lcd-perfect-v7` fixed at +40% ops and was
rejected for. Nothing here made it worse.
