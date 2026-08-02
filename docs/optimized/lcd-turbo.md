# lcd-turbo

From `lcd-perfect-v8`, the latest iteration. 351 ops and 4 taps become **293 ops
and 1 tap**; predicted device cost 15.0 ms → 11.0 ms, 90% of a frame to 66%.

The saving is almost entirely taps. The arithmetic is nearly the same shader,
and that is the point: **at any brightness of 1.00 or below, `lcd-turbo` and
`lcd-perfect-v8` differ by at most 1/255 over the whole case matrix.**

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

```
float sb = pow(max(lp_brightness, 1e-4), 0.5 / max(lp_gamma, 1e-3));
vec3 a = min(texture(...).rgb * sb, 1.0);   // x4
```

Per tap, the clamp is per *source* pixel, identical for every output pixel
covering it, so it cannot vary with coverage and cannot beat. With one tap
there is no per-tap point: the texture unit has already blended.

Three formulations were tried, in order:

| form | result |
|---|---|
| `min(blend × b, 1)` | **1.860 moiré.** A clip after the blend — the design rule doing exactly what it says. |
| `pow(blend, gamma/b)` | **1.860 moiré.** Smooth, but still a non-linearity after the blend. `lcd-perfect` ships gamma at 1.00 precisely so it has none. |
| `min(pattern × b, 1)` | Moiré fine — the bound is position-only, so it cannot vary with coverage. But the pattern is already peak-normalised to 1, so any `b > 1` just flattens its top, and those knees **crawl at 0.719** against a limit of 0.35. |

What works is shallowing the pattern rather than clipping it:

```
float bs = max(lp_brightness, 0.0);
vec3 pat = 1.0 - (1.0 - stripe * gain) / max(bs, 1.0);
vec3 m   = sqrt(max(pat * min(bs, 1.0), 0.0));
```

Above 1 the pattern's depth shrinks toward zero while its peak stays exactly at
1: no knee, no clip, and the picture is never scaled at all. Below 1 it is a
plain multiply, which cannot clip either. Both branches are uniform-derived and
fold.

Measured against `lcd-perfect-v8` on the same source:

| brightness | v8 mean level | turbo mean level | max diff |
|---:|---:|---:|---:|
| 0.50 | 63.32 | 63.32 | **1/255** |
| 1.00 | 89.54 | 89.54 | **1/255** |
| 1.25 *(default)* | 94.47 | 98.43 | 36/255 |
| 2.00 | 104.51 | 110.16 | 78/255 |
| 4.00 | 119.38 | 118.95 | 116/255 |

Identical at and below 1.00, and tracking within a few levels above it. The
difference in kind: `v8` brightens by clipping highlights, `turbo` by giving
back the light the mesh costs. Neither can exceed the source's white, and
`turbo` reaches its ceiling smoothly instead of by clipping.

## Per-effect cost

Each measured on its own over the plain scaler.

| stage | ops | SFU | % of the shader with everything on |
|---|---:|---:|---:|
| one LINEAR tap, aperture-weighted | 205 | 13 | 69% |
| mesh | 7 | 0 | 2% |
| RGB stripes + cast correction | 82 | 4 | 28% |
| gamma | 6 | 6 | 2% |
| brightness | 0 | 0 | 0% |

The stripe block is the only remaining target of any size, and most of it is the
colour-cast correction — which is non-negotiable, so it needs a cheaper form
rather than removal.

## Inherited, not new

The crawl exception at full stripe depth (1.265 at GBA, 0.787 at GBC) is
`lcd-perfect-v8`'s own figure to three decimals — the two shaders are
bit-identical at brightness 1.00, which is where that regime is measured. It is
the stripe's aperture error, which `lcd-perfect-v7` fixed at +40% ops and was
rejected for. Nothing here made it worse.
