# dmg-turbo

From the released `dmg-perfect`. 267 ops and 8 taps become **168 ops and 2
taps**; predicted device cost 14.6 ms → 7.8 ms, 88% of a frame to 47%.

## The shadow is one tap, exactly

`dmg-perfect` samples four neighbours, takes the luma of each, and bilinearly
interpolates them to get how driven the casting cells are:

```
cl = vec4(dot(T[gi  ], LUMA), dot(T[gi+x], LUMA),
          dot(T[gi+y], LUMA), dot(T[gi+xy], LUMA));
casterLum = mix(mix(cl.x, cl.y, gf.x), mix(cl.z, cl.w, gf.x), gf.y);
```

`dot` is linear, so it commutes with `mix`: the luma of the bilinear blend is
the bilinear blend of the lumas. With the texture unit doing the blend, the
whole block is

```
casterLum = dot(texture(Texture, q / TextureSize).rgb, LUMA);
```

This is exact, not an approximation — and it retires the longest comment in the
shader. The four-tap form had to `floor()` a shifted coordinate to pick its cell
pair, and `dmg-perfect` carries fifteen lines explaining why no epsilon fixes the
float32 knife edge on that boundary. There is no longer a `floor()` to
disagree over.

## The two blends collapse into one

`dmg-perfect` computes the same four taps twice: `area`, weighted by footprint
overlap, and `dotm`, weighted by how much of the lit dot falls each side of the
boundary. The second is the aperture-weighted blend, which gives
`mean(source × dot)` where the plain blend gives `mean(source)`.

The owner marked aperture weighting as sacrificeable, so `dotm` is dropped.
With `dotm == area` the two nested mixes fold algebraically:

```
mix(g, mix(SUB, g, dot2d), dp_grid)  ==  mix(g, SUB, dp_grid * (1 - dot2d))
```

One `mix` on a scalar. What it costs is visible only on cell-boundary pixels:
the preview diff against `dmg-perfect` is a max of 6/255 confined to the edges
of the dot grid, and the moiré figures are unchanged or better.

Unlike `lcd-turbo`, the aperture weighting could be dropped here without a moiré
penalty. The difference is what the pattern's dark line sits on: `lcd`'s mesh
line lands on the cell boundary, where the scaler's soft transition pixel also
is, so the two correlate. `dmg`'s gap is a fraction of a cell wide and the
correlation is weaker.

## Measured

Moiré, worst per case, against `dmg-perfect-v10c` on a real Game Boy palette:

| case | dmg-turbo | dmg-perfect |
|---|---:|---:|
| 320x240 → 1024x768 | 0.458 | 0.443 |
| 256x224 → 1024x768 | 0.376 | 0.381 |
| 240x160 → 1024x768 | 0.368 | 0.367 |
| 160x144 → 1024x768 | 0.293 | 0.289 |
| 480x272 → 1024x768 | 0.400 | 0.422 |
| 480x272 → 640x480 | **0.459** | **0.485** |

Within noise everywhere, better at the hardest scale. The three exceptions over
the 0.40 limit are `dp_gamma`, which ships at 1.20 and is a `pow` after the
blend — the same cause and the same cases as the released line's.

Whole-shader difference from `dmg-perfect-v10c` at the shipped defaults, over
the case matrix: **max 73/255, RMS 1.05, and 0.8% of pixels differ by more than
4.** It is a sub-pixel shift of the dot grid at awkward scales — worst at
480x272 → 1024x768, a 2.13x — not a different picture.

Per-effect cost, each measured on its own over the plain scaler:

| stage | ops | tex | % of the shader with everything on |
|---|---:|---:|---:|
| one LINEAR tap | 140 | 1 | 51% |
| dot aperture over the substrate | 21 | 0 | 8% |
| cast shadow | 106 | +1 | 39% |
| brightness · gamma | 6 | 0 | 2% |
| white balance | 0 | 0 | 0% |

The shadow is the only expensive effect and the only thing still needing a
second tap. It is off by default, so the shipped configuration is 168 ops.

## Brightness, in v3

`dp_brightness` is folded into the balance factor, exactly as the released
shader does it:

```glsl
vec3 grade = (1.0 + dp_temperature * vec3(1.0, 0.0, -1.0)
                  + dp_tint        * vec3(-0.5, 1.0, -0.5)) * dp_brightness;
```

Applied to `area` but **not to `DMG_SUBSTRATE`**, so brightening lifts the dots
toward a fixed paper and softens the grid rather than washing the panel out.
That is the one place in either line where the released design already had the
right answer and neither v2 nor v3 needed to move it.

**At the shipped defaults `dmg-turbo-v3` is byte-identical to v1 and v2** on
every case in the matrix — `dp_brightness` ships at 1.00, so nothing acts. The
v2 experiment of folding it into the gamma exponent is gone; it was gamma under
a second name.

`dp_gamma` ships at 1.20, so this shader already has a `pow` after the blend and
already carries the exceptions for it. Those are unchanged.

## The measurement trap this hit

`measure.py` chose its checkerboard by comparing the family name to the exact
string `"dmg-perfect"`, so `dmg-turbo` was scored on the plain white
checkerboard — the one input on which a DMG shader's characteristic defect is
invisible, and which the function's own docstring exists to warn about. It read
**4.634** against the 0.459 the same picture scores on a real palette.

Fixed by keying on the panel kind, `family.split("-")[0]`, rather than the whole
family name. The same class of bug as every other one in
`docs/measurement.md`: a constant that was right when it was written and that
nothing rechecks.
