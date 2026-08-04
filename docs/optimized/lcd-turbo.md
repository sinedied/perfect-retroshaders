# lcd-turbo

From `lcd-perfect-v9a`, the latest iteration. 338 ops and 4 taps become **286
ops and 1 tap**; predicted device cost 15.0 ms → 10.7 ms, 90% of a frame to 64%.

The saving is almost entirely taps. The arithmetic is nearly the same shader,
and that is the point: **at brightness 1.00, `lcd-turbo` and `lcd-perfect-v9a`
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

## Brightness: five forms, and the best one is unavailable

`lcd-perfect-v8` applied brightness to each tap and clamped it there:

```glsl
float sb = pow(max(lp_brightness, 1e-4), 0.5 / max(lp_gamma, 1e-3));
vec3 a = min(texture(...).rgb * sb, 1.0);   // x4
```

Per tap, the clamp is per *source* pixel, identical for every output pixel
covering it, so it cannot vary with coverage and cannot beat. With one tap there
is no per-tap point: the texture unit has already blended.

Five formulations were built and measured, in order:

| form | result |
|---|---|
| `min(blend × b, 1)` *(v3, shipped)* | **3.400 moiré.** A clip after the blend — the design rule doing exactly what it says. |
| `min(pattern × b, 1)` | Moiré fine — the bound is position-only, so it cannot vary with coverage. But the pattern is already peak-normalised to 1, so any `b > 1` just flattens its top, and those knees **crawl at 0.719** against a limit of 0.35. |
| shallow the pattern *(v1)* | Clean on every metric, and wrong: the control fades the effect instead of brightening the picture. |
| `pow(blend, gamma/b)` *(v2)* | 1.860 moiré, and **not a brightness control**: it divides the same exponent gamma divides. Withdrawn. |
| gain per tap, clamped there *(`lcd-perfect-v8`)* | **Best on the numbers** — 0.062 crawl at brightness 2.0 against 0.541 — and unavailable here: one tap means the texture unit has already blended. It was also rejected in the four-tap line, because clamping the content flattens highlights to white before the mesh can shape them. |

v3 ships the first:

```glsl
if (lp_brightness != 1.0)
    color = min(color * lp_brightness, 1.0);
```

`lp_brightness` ships at 1.25, so it is live at the default. The checkerboard
figure is the synthetic worst case, and the effect is exactly 0 at an integer
scale; a source-resolution `colour-mini` pass in front removes it for 1 point of
frame time. Full evidence in `docs/optimized/overview.md`.

**It cost 2 ops and saved 6 SFU** — the guarded `pow` is gone at gamma 1.00.

## Per-effect cost

Each measured on its own over the plain scaler.

| stage | ops | SFU | % of the effects budget |
|---|---:|---:|---:|
| one LINEAR tap, aperture-weighted | 192 | 13 | — *(the floor)* |
| RGB stripes + cast correction | 82 | 4 | 88% |
| mesh | 7 | 0 | 8% |
| brightness · gamma | 6 | 6 | 7% |

The stripe block is the only remaining target of any size, and most of it is the
colour-cast correction — which is non-negotiable, so it needs a cheaper form
rather than removal. `lcd-mini` is what is left when the scaler goes: 120 ops of
floor instead of 190.

## Inherited, not new

The crawl exception at full stripe depth (1.270 at GBA, 0.790 at GBC) is
`lcd-perfect`'s own figure to two decimals — the two shaders are
bit-identical at brightness 1.00, which is where that regime is measured. It is
the stripe's aperture error, which `lcd-perfect-v7` fixed at +40% ops and was
rejected for. Nothing here made it worse.


## v4: the released shader, one tap

The `*-turbo` line had drifted from what ships. `lcd-turbo-v3` carried
`lcd-perfect-v9a`'s peak-normalised stripe and its own brightness — a clamp on
the content before the pattern — while the release, **v6**, has neither. The
owner prefers v6 with both of its known issues, so v4 goes back to it.

Two edits:

```glsl
stripe = vec3(rg, 3.0 - rg.x - rg.y);              // was  / (1.0 + ac)
vec3 m = sqrt(max(stripe * (gain * lp_brightness), 0.0));
// the guarded  min(color * lp_brightness, 1.0)  block is gone
```

`lcd-turbo-v3` was `lcd-perfect-v9a` with four taps replaced by one and nothing
else, so after these two edits **the only remaining difference from the release
is the scaler.** Measured as such:

| | vs released `lcd-perfect`, integer scales, brightness 0.25 → 4.00 |
|---|---|
| v3 | **137/255** |
| **v4** | **0/255** |

Not "within tolerance" — identical. Off an integer scale, where the one-tap and
four-tap scalers genuinely differ, v4 reads 1/255 at the defaults against v3's
47/255.

### What it cost and what it bought

| | moiré exceptions | crawl exceptions | ops @def | device |
|---|---:|---:|---:|---:|
| v3 | 6, worst 3.400 | 2 | 286 | 12.6 ms, 75% |
| **v4** | **1**, worst 0.435 | 3, inherited from v6 | **275** | **11.8 ms, 71%** |

The crawl exceptions are the price and they are not new: they are
`lcd-perfect`'s own, within 0.07 of v6's figures, and they are the clamp on the
product that the owner chose over bleaching the picture. `docs/lcd-perfect.md`
has why.

**It got faster by doing less.** Brightness is 1 op in v4 — a multiply into the
pattern gain — where v3 had a guarded clamp, and the stripe lost a divide. That
is 11 ops and 0.72 ms on the device, which makes v4 **the first lcd head to
clear the 75% target**.

### The `lcd-mini` v4 result

The same two edits, and it comes out with **no exceptions at all**: v3 carried
six for moiré, worst 1.062, and the worst case here reads 0.110 against a limit
of 0.40. 209 ops and 47% of a frame. Nothing to declare is the strongest result
the harness can produce.
