<div align="center">

# 📺<br>perfect-retroshaders

**My take on the "perfect" retro shaders: a convincing retro look that doesn't cost you
performance, brightness, or your sanity.**

![GLSL](https://img.shields.io/badge/GLSL-ES%201.00-5586A4?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-3DA639?style=flat-square)

</div>

## Perfect retroshaders, really?

I'm sure everyone has their own idea of what a "perfect" retro shader is, but for me, it has to meet a few criteria:

- Good enough to give a **nice retro look without compromising performance**. It runs fast on cheap handheld devices (Trimui Brick, H700, etc).
- **Avoid brightness loss, moire patterns, and other artifacts** that can be annoying at non-integer scaling factors.
- **Good defaults but tweakable** to appeal both non-technical users and shader enthusiasts alike.

All shaders provided here follow these principles, and were tested on a real device to ensure they meet the performance and visual quality goals.

## Shaders

> [!IMPORTANT]
> All shaders are designed to output at the final display resolution, as the upscaling is done internally. They are made to work at non-integer scaling factors with almost no visible artifacts/patterns, though the image will still look better at integer scales. 

| Shader | Description |
|---|---|
| [`pixel-perfect.glsl`](shaders/pixel-perfect.glsl) | **Sharp pixel upscaling.** Uniform pixel blocks, no shimmer, fast |
| [`crt-perfect.glsl`](shaders/crt-perfect.glsl) | **CRT.** Scanlines, RGB mask, pixel-perfect scaling |
| [`lcd-perfect.glsl`](shaders/lcd-perfect.glsl) | **LCD.** Black-matrix grid, RGB subpixel stripes, pixel-perfect scaling |
| [`dmg-perfect-v8.glsl`](shaders/dmg-perfect-v8.glsl) | **Game Boy DMG.** Dot-matrix grid with light gaps, optional cast shadow, contrast wheel, pixel-perfect scaling |

<!-- Include screenshots here and links to RetroShader Lab for each shader, so users can see the differences and tweak the parameters to their liking. -->

### Parameters

(1-line intro here, then keep the descriptions short and to the point for each shader. Include notes and limitations where relevant, as well as tips (for example GBA has a BGR lcd IIRC). Saying to use gamma instead of brightness to brighten is NOT a good tip, as it kills the contrast and wash out the colors. Brightness clips, yes, but matches more the look of old CRTs and LCDs, which is what we're trying to simulate.)

#### pixel-perfect

Scaling only, no CRT effect. Each output pixel is the average of the source over its
own footprint, so source pixels become even blocks with a single soft pixel at each
boundary — no crawling or uneven blocks as the image scrolls, and no blurring of the
whole image either.

| Name | Default | Range | |
|---|---|---|---|
| `pp_sharpness` | 1.00 | 0.20–1.00 | transition width between blocks; lower is crisper |

Output is identical to the well-known `pixellate` shader with default params, but with a better performance.

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
| `sharp-shimmerless-grid` | 0.72 | 82.8% | 66.6 | 66.6 |
| **`lcd-perfect` (defaults)** | **0.24** | **82.5%** | **57.6** | **36.2** |
| `crt-perfect` (for scale) | 0.26 | 83.9% | 63.8 | 40.9 |

So: a grid more than twice `lcd1x`'s strength, at **one seventh the moiré**, losing 3%
of the light where `lcd1x` loses 25% with nothing to claw it back. `lp_gap` drives the
row gap and scales the column gap by 0.4, the ratio measured off a Game Boy Color
panel — one knob instead of two.

`lp_subpixels` costs beat much faster than the grid does (0.24 at the default 0.20,
0.56 at 0.35, 1.18 at 0.50) and needs at least ~3 output pixels per cell to have room
for three stripes, so it fades out below that and is off almost everywhere at 640×480.

#### dmg-perfect

Simulates an original Game Boy: square dots separated by a visible grid. Based on
`dmg_dot_matrix`, which already looks right at integer scaling and is kept as the
reference to match rather than to improve on.

| Name | Default | Range | |
|---|---|---|---|
| `dp_grid` | 0.30 | 0.00–1.00 | grid visibility |
| `dp_gap` | 1.00 | 0.25–2.00 | grid line thickness, in pixels |
| `dp_shadow` | 0.00 | 0.00–1.00 | shadow cast by driven dots; 0 disables it |
| `dp_red` | 1.00 | 0.00–2.00 | red gain |
| `dp_green` | 1.00 | 0.00–2.00 | green gain |
| `dp_blue` | 1.00 | 0.00–2.00 | blue gain |
| `dp_contrast` | 1.00 | 0.00–1.00 | the console's contrast wheel; 1.00 disables it |
| `dp_brightness` | 1.00 | 0.25–4.00 | output gain |
| `dp_gamma` | 1.00 | 0.50–2.00 | gamma |

A DMG is a **negative display**: reflective, no backlight, normally-white crystal.
Driving a pixel makes it dark, and the gaps between pixels have no electrode at all,
so they sit permanently at the lightest state. Its matrix is therefore *lighter* than
a lit pixel — the opposite of every backlit panel, and why the grid is invisible on a
white field and strongest on dark content, exactly as a real DMG reads.

**It reproduces, in one pass, what you get from two.** The way to get a good DMG out
of a frontend is to draw the dot matrix at a whole scale factor and let a `pixellate`
pass do the rest — and that is not a workaround, it is a better computation. Drawing
the matrix at a whole scale and resampling filters the image and the grid *together*;
multiplying a scaled image by a grid does not, and the difference shows up as cells
that break into a pattern at a fractional scale. Both passes are linear, so the
composite has a closed form, and this evaluates it directly: **no intermediate buffer,
no second pass, no preset change.** `tools/twopass.py` builds the two-pass pipeline
literally and gates the match, which comes out at 1/255.

Measured on a flat field against the reference:

| | 5× integer | 1024×768 | 640×480 |
|---|---|---|---|
| `dmg_dot_matrix` cell spacing | 5, 5, 5 | **6, 7, 6, 7** | 3, 3, 4, 3 down |
| `dmg_dot_matrix` lattice error | 0.0% | **6.7% / 7.6%** | 0.0% / **12.2%** |
| **`dmg-perfect` lattice error** | **0.0%** | **0.1% / 0.3%** | **0.0% / 0.7%** |
| **`dmg-perfect` line width** | 1.00px | 1.27, 1.05px | 1.34, 1.08px |

The reference draws a line of exactly one output pixel, which cannot be placed 6.4
apart, so its cells alternate six and seven wide. Here `dp_gap` is a thickness in
pixels *at the whole scale that fits the screen* — 5× at 1024×768, 3× at 640×480 —
so a line stays about one pixel wide at every resolution while the spacing stays
exact, and 1.00 is precisely the line the reference draws.

**At every whole scale factor the output is identical to `dmg_dot_matrix`, pixel for
pixel** (0/255 at 3×, 4× and 5×), whenever the two are set the same. Set
`dp_brightness` 1.20 and `dp_gamma` 1.40 to reproduce its defaults. Those two are a
contrast curve applied after the blend, so they give partial-coverage pixels a
coverage-dependent shift; the defaults leave them neutral and the trade to you.

`dp_shadow` casts a shadow down and to the right of each dot, so the dots read as
sitting above the panel rather than being printed on it. It is off by default and the
branch is uniform, so it costs nothing until it is asked for.

**Only a driven pixel casts one.** A dark pixel is opaque and blocks light; an
undriven one is transparent and casts nothing at all. That sounds obvious and is easy
to get wrong: strength has to be measured against the panel's *undriven* level, not
against white. Measured against white, every shade of a Game Boy palette counts as
most of the way opaque, and since the lightest shade is typically 67–75% of the screen
the result is a flat dimming of the whole picture rather than a shadow. The undriven
level is read from the pixels around each dot, so it follows whatever palette your
core is using, from Gambatte's dark DMG green through to a plain greyscale one.

**The shadow lies under the panel, not in the gaps between dots.** On a reflective
screen the light crosses the liquid crystal, bounces off the substrate and crosses
back, so a neighbour shading the substrate dims whatever that cell finally shows — it
reads through the pale undriven cells and is hidden by the dark driven ones. That is
what makes the dots look raised. Putting it in the gaps instead confines it to the
one-pixel grid lines, where it reads as a mesh laid over the picture.

Its distance and softness are fixed in **source** pixels, so they hold their
proportions at every resolution instead of shrinking as the screen grows, and it falls
further down than across as a panel lit from above would.

**The blur is on the opacity, not on the dot's outline.** Widening the box filter over
the dot's own shape is free, and it was tried first, and it is not a blur at all — it
softens the aperture's internal gaps while the edge of the shadow *as a whole* stays
exactly one output pixel wide, because that edge comes from a per-cell opacity that was
being sampled at the nearest cell. Interpolating that opacity between the four
surrounding cells is what actually softens it, and it costs four taps, which is the
price of the feature. They sit inside the uniform branch, so nothing is paid with the
shadow off.

Unlike most things here it is cheap in pattern terms — a shadow lying under everything
is a low-frequency multiply. Worst measured on a Game Boy palette across 1024×768,
853×768, 640×480 and 533×480, where anything past about 0.4 starts to show:

| `dp_shadow` | 0.00 | 0.25 | 0.45 | 0.70 | 1.00 |
|---|---|---|---|---|---|
| beat | 0.19 | 0.24 | **0.29** | 0.39 | 0.56 |

So most of the range is usable and only the top of it is worth avoiding.

`dp_contrast` is the wheel on the side of the console. On a real DMG that is a
potentiometer on the LCD board setting the amplitude of the bias ladder the driver
builds its four drive levels from, so it scales how hard every pixel is driven at once;
turned down, the picture washes out towards blank undriven panel. 1.00 is the wheel at
its correct setting and 0.00 is a blank screen.

It is an **affine** map — a gain and an offset — and that is what makes it safe to
apply to the finished colour rather than to the four taps. The scaler's weights sum to
one, so `a·(Σwᵢxᵢ) + b` is exactly `Σwᵢ(a·xᵢ + b)`: post-blend and per-tap are the same
number, at a quarter of the cost. This is the converse of the rule against post-blend
non-linearity, not an exception to it.

Pivoting on the substrate is what makes one multiply-add enough, and it is also what
makes it correct: the substrate is the map's fixed point, so **the gaps do not move at
any setting**, which is right, because a gap has no electrode over it and no bias
voltage can reach it.

**It stops at 1.00 deliberately.** The map sends `[0,1]` to `[1-c, 1]`, so at or below
1.00 nothing can leave the range whatever the source or the palette, while above it the
low end is clipped by exactly `c-1` — a property of the map, not of any content. A clip
after the blend gives partial-coverage pixels a coverage-dependent shift, which is
precisely the moire this family exists to avoid; on a Game Boy palette 1.15 already
measures 1.54 against a floor of 0.19. Every setting it does accept clips nothing and
measures at or below that floor:

| `dp_contrast` | 1.00 | 0.95 | 0.85 | 0.65 | 0.45 | 0.15 |
|---|---|---|---|---|---|---|
| beat | 0.19 | 0.19 | 0.16 | 0.12 | 0.10 | 0.04 |
| clipped | — | 0% | 0% | 0% | 0% | 0% |

libretro's Game Boy shader, the only other one with this control, ships the same
`[0, 1]` range, very likely for the same reason. For a darker picture use `dp_gamma`,
which costs some evenness but never clips.

`dp_red`, `dp_green` and `dp_blue` trim the colour balance, which is worth having
because Game Boy palettes vary a lot between cores and none of them is neutral. They
are plain gains, so above 1.00 they clip; the usual way to warm or cool a picture is
to pull the other two channels down instead. A gain is affine, so it adds no pattern
of its own, and it sits behind a uniform branch — leave it neutral and it costs
literally nothing.

Below two output pixels per cell there is no room for a dot and a line, so the grid
fades out rather than folding to a coarser pitch. Every Game Boy case is well above
that — the smallest is 3.33 at 640×480.


## Performance

TODO: performance tests: pixellate (baseline), pixel-perfect, crt-perfect, lcd-perfect. Include a table with the results and a graph, including real GPU usage.

## Related

- **[RetroShader Lab](https://github.com/sinedied/retroshader-lab)** — browser bench
  that runs the same pipeline, for iterating in milliseconds instead of SD-card round
  trips. **[Open the lab](https://sinedied.github.io/retroshader-lab/)**
- **[NextUI](https://github.com/LoveRetro/NextUI)** — the handheld firmware these
  were tested on.

## Licence

MIT, see [LICENSE](LICENSE). Shaders under `tools/vendor/` are third-party, kept only
as benchmark references, each under its own licence as stated in its file header.
