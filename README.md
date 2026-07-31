<div align="center">

# 📺<br>perfect-retroshaders

**My take on the "perfect" retro shaders: a convincing retro look that doesn't cost you
performance, brightness, or your sanity.**

![Retro look](https://img.shields.io/badge/%F0%9F%95%B9%EF%B8%8F%20retro-look-C64A8F?style=flat-square)
![GLSL](https://img.shields.io/badge/GLSL-ES%201.00-5586A4?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-3DA639?style=flat-square)

</div>

## Perfect retroshaders, really?

I'm sure everyone has their own idea of what a "perfect" retro shader is, but for me, it has to meet a few criteria:

- Good enough to give a **nice retro look without compromising performance**. It runs fast on cheap handheld devices (Trimui Brick, H700, etc).
- **Avoid brightness loss, moire patterns, and other artifacts** that can be annoying at non-integer scaling factors.
- **Good defaults but tweakable** to appeal both non-technical users and shader enthusiasts alike. They're optimized for single-pass pipelines and handle pixel perfect upscaling, no need for complex setups.

All shaders provided here follow these principles, and were tested on a real device to ensure they meet the performance and visual quality goals. I even built a [custom lab](https://sinedied.github.io/retroshader-lab/) to experiment and pixel-peep them against many popular alternatives.

## Shaders

| Shader | Description |
|---|---|
| [`pixel-perfect.glsl`](shaders/pixel-perfect.glsl) | **Sharp pixel upscaling.** Uniform pixel blocks, no shimmer, fast |
| [`crt-perfect.glsl`](shaders/crt-perfect.glsl) | **CRT.** Scanlines, RGB mask, pixel-perfect scaling |
| [`lcd-perfect.glsl`](shaders/lcd-perfect.glsl) | **LCD.** Black-matrix grid, RGB subpixel stripes, pixel-perfect scaling |
| [`dmg-perfect.glsl`](shaders/dmg-perfect.glsl) | **Game Boy DMG.** Dot-matrix grid with light gaps, optional cast shadow, white balance, pixel-perfect scaling |

> [!IMPORTANT]
> All shaders are designed to output at the final display resolution, as the upscaling is done internally. They are made to work at non-integer scaling factors with almost no visible artifacts/patterns, though the image will still look better at integer scales.

### Screenshots

<!-- TODO manually, not by agent: Include screenshots here and links to RetroShader Lab for each shader, so users can see the differences and tweak the parameters to their liking. -->

### Parameters

Every shader ships ready to use, so the defaults are the recommendation: only reach for these if you want to change the look. Any control set to its neutral value costs nothing at all, not just visually but in GPU time.

#### pixel-perfect

A clean upscale: every source pixel becomes an even block, with no shimmer and no blur. The plain, fast default when you want the picture and nothing else, plus simple colour controls for tuning it to a screen.

| Parameter | Range | Default | |
|---|---|---|---|
| Brightness | 0.50 – 2.00 | 1.00 | Output gain. |
| Contrast | 0.00 – 2.00 | 1.00 |  |
| Saturation | 0.00 – 2.00 | 1.00 | Colour intensity. |
| Gamma | 0.50 – 2.00 | 1.00 | Output gamma. |
| Cool / warm balance | −1.00 – 1.00 | 0.00 | Warm above 0, cool below. |
| Magenta / green balance | −1.00 – 1.00 | 0.00 | Green above 0, magenta below. |

> [!NOTE]
> Output is identical to the well-known `pixellate` shader with default params, but with a better performance.

#### crt-perfect

A CRT look: soft scanlines and an RGB shadow mask over a clean pixel scale, with optional screen curvature. Reads like a small tube TV, sharp rather than blurry, and neither pattern beats against the pixel grid at any scale.

| Parameter | Range | Default | |
|---|---|---|---|
| Scanline visibility | 0.00 – 1.00 | 0.60 |  |
| RGB mask visibility | 0.00 – 1.00 | 0.20 |  |
| Mask | 0 / 1 / 2 | 1 | Off, aperture grille, slot grille. |
| Mask triads per pixel | 0.25 – 2.00 | 1.00 | Mask triads per source pixel. |
| Min. pitch in px | 2.00 – 6.00 | 3.00 | Smallest pattern pitch, in output pixels. |
| Screen curvature | 0.00 – 0.15 | 0.00 |  |
| Brightness | 0.25 – 4.00 | 1.25 | Output gain. |
| Gamma | 0.50 – 2.00 | 1.00 | Output gamma. |

> [!TIP]
> - Keep **min. pitch** at 2.50 or above. Below that a triad has fewer than three output pixels to sit in, and the mask falls back to two colours.
>
> - **Curvature** is off by default. It bends the image onto a tube without cropping anything: the corners round off, the edges still reach the screen.

#### lcd-perfect

A handheld LCD look: a soft backlit mesh with RGB subpixel stripes, over a clean pixel scale. Reads like a Game Boy Color or GBA screen in good light — a gentle grid rather than a hard black matrix, and it stays even at every scale instead of breaking into a pattern.

| Parameter | Range | Default | |
|---|---|---|---|
| Grid visibility | 0.00 – 1.00 | 0.30 |  |
| Row/column balance | 0.00 – 1.00 | 0.50 | 0 rows, 1 columns. |
| Minimum pitch in px | 2.00 – 6.00 | 3.00 | Smallest pattern pitch, in output pixels. |
| RGB stripe visibility | 0.00 – 1.00 | 0.20 |  |
| Stripe order | 0 / 1 | 0 | RGB or BGR. |
| Brightness | 0.25 – 4.00 | 1.25 | Output gain. |
| Gamma | 0.50 – 2.00 | 1.00 | Output gamma. |

> [!TIP]
> - **Set stripe order to BGR (1) for Game Boy Advance content.** The GBA panel really is laid out blue-green-red, so RGB puts the colour fringes on the wrong side.
>
> - **Row/column balance** decides which way the grid leans. Real panels are row-dominant; around 0.80 matches the look of `lcd1x` if that is what you are used to.

#### dmg-perfect

An original Game Boy look: the dot matrix grid with its pale gaps, over a clean pixel scale. Dots can cast a shadow so they sit above the panel. The grid is invisible on white and strongest on dark content, as a real DMG is.

| Parameter | Range | Default | |
|---|---|---|---|
| Grid visibility | 0.00 – 1.00 | 0.30 |  |
| Grid line thickness | 0.25 – 2.00 | 1.00 | Grid line thickness, in pixels. |
| Dot shadow | 0.00 – 1.00 | 0.00 | Shadow cast by driven dots. |
| Brightness | 0.25 – 4.00 | 1.00 | Output gain. |
| Gamma | 0.50 – 2.00 | 1.20 | Output gamma. |
| Cool / warm balance | −1.00 – 1.00 | 0.00 | Warm above 0, cool below. |
| Magenta / green balance | −1.00 – 1.00 | 0.00 | Green above 0, magenta below. |

> [!TIP]
> - **Grid line thickness is in output pixels**, not a fraction of a cell, so the panel reads the same at 640x480 as at 1024x768. 1.00 is a one-pixel line.
>
> - **Dot shadow** lifts the dots off the panel, as if lit from above. It is off by default. Only driven pixels cast one.

## Performance

Measured against [`pixellate`](tools/vendor/pixellate.glsl), the shader most people already use for clean upscaling, at 320x240 into 1024x768. Two rows per shader: as it ships, and with every effect it has turned up.

| Shader | Active instructions | Texture taps | Speed vs `pixellate` |
|---|---|---|---|
| `pixellate` (baseline) | 240 | 4 | 100% |
| **`pixel-perfect`**, defaults | **111** | 4 | **127%** |
| `pixel-perfect`, everything on | 143 | 4 | 123% |
| `dmg-perfect`, defaults | 265 | 4 | 97% |
| `dmg-perfect`, everything on | 447 | 8 | 78% |
| `lcd-perfect`, defaults | 334 | 4 | 94% |
| `lcd-perfect`, everything on | 339 | 4 | 94% |
| `crt-perfect`, defaults | 428 | 4 | 93% |
| `crt-perfect`, everything on | 503 | 4 | 86% |

`pixel-perfect` is a drop-in replacement for `pixellate` that produces the same image with better performance. The three effect shaders do considerably more and still stay within a tenth of it at their defaults, because the expensive part of all four is the same scaler underneath.

*Active instructions* are what actually runs at those settings, not what the file contains: every optional feature sits behind a check on its own parameter, so a control left alone is skipped rather than computed and thrown away. That is why the two rows differ, and why turning curvature, the dot shadow or a colour balance off costs almost nothing.

Speed is throughput: 127% means the same GPU time buys 27% more frames than `pixellate` does. The instruction and tap counts come from the compiled shader and are exact. The timings are from a desktop GPU, not a handheld so consider them a rough guide.

## Related

- **[RetroShader Lab](https://github.com/sinedied/retroshader-lab)** — browser bench
  that runs the same pipeline, for iterating in milliseconds instead of SD-card round
  trips. **[Open the lab](https://sinedied.github.io/retroshader-lab/)**
- **[NextUI](https://github.com/LoveRetro/NextUI)** — the handheld firmware these
  were tested on.

## Licence

MIT, see [LICENSE](LICENSE). Shaders under `tools/vendor/` are third-party, kept only
as benchmark references, each under its own licence as stated in its file header.
