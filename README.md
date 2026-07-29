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

budget: 8 params max per shader


Note: all shaders are designed to output at the final display resolution, as the upscaling is done internally. They are made to be work at non-integer scaling factor without any visible moire patterns, though the image will still always be better at integer scales.


| File | |
|---|---|
| `shaders/pixel-perfect.glsl` | **scaling only.** Uniform pixel blocks, no shimmer, no blur |
| `shaders/crt-perfect.glsl` | **CRT.** Scanlines, RGB mask, pixel-perfect scaling, gamma |
| `shaders/lcd-perfect.glsl` | **LCD.** Black-matrix grid, RGB subpixel stripes, pixel-perfect scaling, gamma |

Earlier iterations live in [`tools/iterations/`](tools/iterations), kept so the
trade-offs stay visible. They are still verified on every harness run.

Third-party shaders used only as benchmark references live in
[`tools/vendor/`](tools/vendor) and are not part of this project's licence.

Include screenshots here and links to RetroShader Lab for each shader, so users can see the differences and tweak the parameters to their liking.

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
