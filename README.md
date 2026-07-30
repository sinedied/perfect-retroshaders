<div align="center">

# 📺<br>perfect-retroshaders

**My take on the "perfect" retro shaders: a convincing retro look that doesn't cost you
performance, brightness, or your sanity.**

![GLSL](https://img.shields.io/badge/GLSL-ES%201.00-5586A4?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-3DA639?style=flat-square)

</div>

## Perfect retroshaders, really?

I'm sure everyone has their own idea of what a "perfect" retro shader is, but for me, it has to meet a few criteria:

- Good enough to give a **nice retro look without compromising performance**. It runs fast on cheap handheld devices (Trimui Brick, H700, etc.)
- **Avoid brightness loss, moire patterns, and other artifacts** that can be annoying at non-integer scaling factors.
- **Good defaults, tweakable** yet easy to use even for non-technical users.

All shaders provided here follow these principles, and were tested on a real device to ensure they meet the performance and visual quality goals.

## Shaders

TODO

crt-perfect
lcd-perfect
pixel-perfect
dmg-perfect



> [!IMPORTANT]
> All shaders are designed to output at the final display resolution, as the upscaling is done internally. They are made to work at non-integer scaling factors with almost no visible artifacts/patterns, though the image will still look better at integer scales.


| Shader | Description |
|---|---|
| [`pixel-perfect.glsl`](shaders/pixel-perfect.glsl) | **Sharp pixel upscaling.** Uniform pixel blocks, no shimmer, fast |
| [`crt-perfect.glsl`](shaders/crt-perfect.glsl) | **CRT.** Scanlines, RGB mask, pixel-perfect scaling |
| [`lcd-perfect.glsl`](shaders/lcd-perfect.glsl) | **LCD.** Black-matrix grid, RGB subpixel stripes, pixel-perfect scaling |

<!-- Include screenshots here and links to RetroShader Lab for each shader, so users can see the differences and tweak the parameters to their liking. -->

### Parameters

TODO

#### pixel-perfect

Scaling only, no CRT effect. Each output pixel is the average of the source over its
own footprint, so source pixels become even blocks with a single soft pixel at each
boundary — no crawling or uneven blocks as the image scrolls, and no blurring of the
whole image either.

| Name | Default | Range | |
|---|---|---|---|
| `pp_sharpness` | 1.00 | 0.20–1.00 | transition width between blocks; lower is crisper |

Output is identical to the well-known `pixellate` shader (verified to 1/255 across 12
scale combinations and 4 source types) at **112 instructions instead of 294, and zero
transcendentals instead of 15 `pow` calls**. It also avoids `pixellate`'s default
linear-gamma blending, which is itself a moiré source: measured 3.5–5.7 against 0.000.

Needs a NEAREST sampler. Upscaling only.

#### crt-perfect

| Name | Default | Range | |
|---|---|---|---|
| `cp_scanlines` | 0.55 | 0.00–1.00 | scanline visibility |
| `cp_rgb_mask` | 0.40 | 0.00–1.00 | RGB mask visibility |
| `cp_mask_type` | 1 | 0 / 1 / 2 | off / aperture grille / slot mask |
| `cp_mask_size` | 1.00 | 0.25–2.00 | triads per source pixel |
| `cp_brightness` | 1.25 | 0.25–4.00 | output gain — clips highlights above ~1.5 |
| `cp_min_pitch` | 3.00 | 2.00–6.00 | smallest pattern pitch, in output pixels |
| `cp_gamma` | 1.00 | 0.50–2.00 | gamma; below 1 brightens **without** clipping |

To brighten, prefer `cp_gamma` below 1.0 over `cp_brightness` above 1.0: it lifts more,
crushes no highlights, and adds no moiré. `cp_brightness` is a linear gain into a hard
clamp — useful if you want blown highlights as a bloom effect, which is a look rather
than a correction.

The shader must render at final output resolution, one output pixel per display pixel.
Each file's header documents the pass settings a host needs to provide.

#### lcd-perfect

Simulates the panels of handhelds like the Game Boy Color, Game Boy Advance, DS and
PSP: a grid of rectangular apertures in a black matrix, each split into three coloured
stripes.

| Name | Default | Range | |
|---|---|---|---|
| `lp_grid` | 0.30 | 0.00–1.00 | grid visibility |
| `lp_gap` | 0.16 | 0.00–0.50 | matrix thickness, as a fraction of a cell |
| `lp_subpixels` | 0.20 | 0.00–1.00 | RGB stripe visibility |
| `lp_layout` | 0 | 0 / 1 | stripe order — RGB or BGR |
| `lp_brightness` | 1.00 | 0.25–4.00 | output gain — clips highlights, prefer `lp_gamma` |
| `lp_gamma` | 1.00 | 0.50–2.00 | gamma; below 1 brightens **without** clipping |

An LCD aperture is a rectangle, and the mean of a rectangular pulse train over an
output pixel has a closed form — so where a CRT beam profile has to be a band-limited
sinusoid, this is `floor`, `fract` and `clamp` with **no transcendentals at all**.
Contrast then falls to zero on its own as cells approach the pixel grid, so there is
no fade to tune and no minimum pitch to configure.

Measured against the shader it replaces, at 320×240 → 1024×768:

| | moiré beat | mean level | row swing | col swing |
|---|---|---|---|---|
| `lcd1x` (defaults) | 1.87 | 75.3% | 24.0 | 96.0 |
| `lcd3x` | 2.93 | 82.3% | 68.6 | 5.8 |
| `sharp-shimmerless-grid` | 3.14 | 82.8% | 66.6 | 66.6 |
| **`lcd-perfect` (defaults)** | **0.24** | **82.5%** | **57.6** | **36.2** |
| `crt-perfect` (for scale) | 0.26 | 83.9% | 63.8 | 40.9 |

So: a grid more than twice `lcd1x`'s strength, at **one seventh the moiré**, losing 3%
of the light where `lcd1x` loses 25% with nothing to claw it back. `lp_gap` drives the
row gap and scales the column gap by 0.4, the ratio measured off a Game Boy Color
panel — one knob instead of two.

`lp_subpixels` costs beat much faster than the grid does (0.24 at the default 0.20,
0.56 at 0.35, 1.18 at 0.50) and needs at least ~3 output pixels per cell to have room
for three stripes, so it fades out below that and is off almost everywhere at 640×480.

Needs a NEAREST sampler. Upscaling only.

#### lcd-perfect v2

Two iterations aimed at `lcd1x`'s look, which v1 cannot reach: `lcd1x` is
vertical-dominant at a 4:1 column-to-row swing ratio, v1 is horizontal-dominant at
0.44:1, and v1's `GAP_ASPECT` constant caps the column gap at 40% of the row gap — so
pushing `lp_gap` to maximum still only reaches 0.61. Both v2 shaders replace that
constant with an **`lp_balance`** parameter (0 = rows only, 0.5 = even, 1 = columns
only; the ratio is `b/(1−b)`), and both widen the stripe fade, which at v1's setting
left the stripes at 1.3% strength at 3.2 output pixels per cell — inert at the most
common scale there is.

**v2a** additionally replaces the trapezoid aperture with a **sinusoid**, which is
the shape `lcd1x` actually uses. A sinusoid carries no harmonics to fold back past
Nyquist, so it needs none of the ramp machinery the hard-edged aperture needs to stay
clean — and that machinery was most of v1's cost.

Measured on a white field at 320×240 → 1024×768, all rendered on the GPU:

| | mean | row swing | col swing | col/row | moiré | ops | SFU |
|---|---|---|---|---|---|---|---|
| **`lcd1x`** (the target) | 75.3% | 24.0 | 96.0 | **4.00** | 1.865 | 54 | 2 |
| `lcd3x` | 82.3% | 68.6 | 5.8 | 0.08 | 8.207 | 70 | 4 |
| `lcd-perfect` (v1) | 85.0% | 57.6 | 25.4 | 0.44 | 0.244 | 646 | 27 |
| `lcd-perfect-v2b` | 80.7% | 15.2 | 71.0 | 4.65 | 0.385 | 651 | 27 |
| **`lcd-perfect-v2a`** | **72.6%** | **24.4** | **96.2** | **3.94** | **0.144** | 515 | 33 |

**v2a lands on `lcd1x` within a couple of percent on every axis, at one thirteenth
the moiré** — and with even pixel blocks, which `lcd1x` has no scaler to provide.

It also survives the drop to 640×480, where the scale is exactly 2.0 output pixels
per cell and every other shader here loses its grid:

| at 320×240 → 640×480 | mean | row swing | col swing | col retained |
|---|---|---|---|---|
| `lcd1x` | 75.3% | 3.6 | 19.1 | 20% |
| `lcd-perfect` (v1) | 85.4% | 20.5 | 5.5 | 22% |
| `lcd-perfect-v2b` | 81.0% | 3.0 | 32.0 | 45% |
| **`lcd-perfect-v2a`** | 72.5% | 17.8 | **71.5** | **74%** |

An even-integer scale puts both samples of a cell on symmetric points of the profile,
which is why `lcd1x` — an unshifted sinusoid — nearly vanishes. v2a shifts by half an
output pixel unconditionally, which costs nothing and removes every such dropout.

**v2b cannot get there.** Every configuration at a 4:1 ratio with a column swing near
96 measures past the 0.4 visible threshold; its best inside the budget is a column
swing of 71, a quarter short. A column-dominant *hard-edged* matrix is mostly
harmonics and they fold back into the visible band. That is the same lesson v1's
ramp taught, arriving structurally: if you want a strong vertical grid, you want a
smooth profile.

#### lcd-perfect v3

v2a shipped with three defects that only real content and a missing test case
exposed. v3 is v2a with all three fixed, and adds **`lp_min_pitch`**.

**The PSP pattern.** PSP 480×272 was a stated target present in *neither* test
matrix, which is how a visible pattern reached a device with every measurement here
green. It is the hardest case in the set: 2.13 output pixels per cell at 1024×768 and
**1.33 at 640×480**, below the two per cycle any pattern needs. v2a inherited no
Nyquist fade and no minimum pitch, because the trapezoid it grew out of band-limits
itself and a sinusoid does not — nobody re-checked that when the aperture changed.

v3 does *not* pin the mesh to output space the way crt-perfect does; that was tried
and is worse, because a two-dimensional pattern that has stopped tracking the source
interferes with the pixel blocks. Instead the period grows to a **whole number of
cells**, which keeps it exactly periodic on the source grid so it cannot beat against
it at all.

**The colour cast.** A column mesh and a stripe mask both sit at one cycle per cell,
so whichever stripe lands on the dark line is dimmed — and swapping the stripe order
swaps which one, which is why RGB and BGR cast in opposite directions. The stripes
are now three sinusoids 120° apart and the residual is divided out in closed form.

**The SNES difference.** `lcd1x` drops ~20% of its contrast at integer scales,
because it point-samples and its samples reach only 0.707 of the sinusoid there. v3
stays consistent — copying that would be copying a sampling artefact — and the
default comes down instead.

| at 320×240 → 1024×768 | mean | row | col | col/row | moiré | ops |
|---|---|---|---|---|---|---|
| **`lcd1x`** (the target) | 75.3% | 24.0 | 96.0 | 4.00 | 1.865 | 54 |
| `lcd-perfect-v2a` | 72.6% | 24.4 | 96.2 | 3.94 | 0.131 | 515 |
| **`lcd-perfect-v3`** | **75.1%** | 22.5 | **90.2** | **4.00** | **0.098** | **434** |

Averaged across GB, GBA, SNES, NDS, 240p and PSP sources, v3 matches `lcd1x` on
every figure that describes the look — column swing 90.2 against 90.0, ratio 4.00
against 3.89, mean level 75.1% against 75.3% — at **one sixth the moiré**, and it is
the cheapest shader of the family.

| moiré, worst across all ten test scales | |
|---|---|
| `lcd-perfect-v2a` | 5.909 |
| `lcd-perfect-v2b` | 4.511 |
| `lcd-perfect` (v1) | 1.403 |
| `crt-perfect` | 0.575 |
| **`lcd-perfect-v3`** | **0.323** |

Colour cast on a white field falls from v2a's 3.5–4.2 levels to **0.01–0.76**, and
the RGB-versus-BGR difference from 3.5–5.3 to **exactly 0**.

One caveat worth knowing: `lp_balance` 0.79 is what matches `lcd1x` on the aggregate
figures, but around **0.65** looks closer to its weave on a real frame, because
`lcd1x` point-samples and its horizontal lines are sharper than a box-filtered one of
the same measured swing. The numbers and the eye disagree here; the parameter is
there to settle it.

`lp_grid` and `lp_balance` are shared; v2b keeps `lp_gap`, v2a has no use for one
because a sinusoid has no thickness.

## Performance

TODO: performance tests 

## Related

- **[RetroShader Lab](https://github.com/sinedied/retroshader-lab)** — browser bench
  that runs the same pipeline, for iterating in milliseconds instead of SD-card round
  trips. **[Open the lab ▶](https://sinedied.github.io/retroshader-lab/)**
- **[NextUI](https://github.com/LoveRetro/NextUI)** — the handheld firmware these
  target.

## Licence

MIT, see [LICENSE](LICENSE). Shaders under `tools/vendor/` are third-party, kept only
as benchmark references, each under its own licence as stated in its file header.
