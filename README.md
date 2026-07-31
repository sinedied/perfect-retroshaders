<div align="center">

# 📺<br>perfect-retroshaders

**My take on the "perfect" retro shaders: a convincing retro look that doesn't cost you
performance, brightness, or your sanity.**

![Retro](https://img.shields.io/badge/%F0%9F%95%B9%EF%B8%8F-retro%20%7C%20pixels-C64A8F?style=flat-square)
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

Clean upscaling and nothing else, plus a few colour controls for tuning the picture to your screen.

| Parameter | Range | Default | |
|---|---|---|---|
| Brightness | 0.50 – 2.00 | 1.00 | Overall gain |
| Contrast | 0.00 – 2.00 | 1.00 | |
| Saturation | 0.00 – 2.00 | 1.00 | 0 is black and white |
| Gamma | 0.50 – 2.00 | 1.00 | Below 1 lifts the mid-tones |
| Cool / warm balance | −1.00 – 1.00 | 0.00 | Above 0 is warmer |
| Magenta / green balance | −1.00 – 1.00 | 0.00 | Above 0 is greener |

> [!NOTE]
> Output is identical to the well-known `pixellate` shader with default params, but with a better performance.

#### crt-perfect

| Parameter | Range | Default | |
|---|---|---|---|
| Scanline visibility | 0.00 – 1.00 | 0.60 | |
| RGB mask visibility | 0.00 – 1.00 | 0.20 | The subpixel pattern |
| Mask type | 0 / 1 / 2 | 1 | Off, aperture grille, slot mask |
| Mask triads per pixel | 0.25 – 2.00 | 1.00 | Lower is a coarser mask |
| Min. pitch in px | 2.00 – 6.00 | 3.00 | How fine the patterns may get |
| Screen curvature | 0.00 – 0.15 | 0.00 | Off by default |
| Brightness | 0.25 – 4.00 | 1.25 | Compensates the scanlines |
| Gamma | 0.50 – 2.00 | 1.00 | |

**Tips**

- Keep **min. pitch** at 2.50 or above. Below that a triad has fewer than three output pixels to sit in, and the mask falls back to two colours.
- **Curvature** is off by default and costs a little when on. It bends the image onto a tube without cropping anything: the corners round off, the edges still reach the screen.

#### lcd-perfect

| Parameter | Range | Default | |
|---|---|---|---|
| Grid visibility | 0.00 – 1.00 | 0.30 | |
| Row/column balance | 0.00 – 1.00 | 0.50 | 0 is all rows, 1 all columns |
| Minimum pitch in px | 2.00 – 6.00 | 3.00 | How fine the grid may get |
| RGB stripe visibility | 0.00 – 1.00 | 0.20 | The subpixel stripes |
| Stripe order | 0 / 1 | 0 | RGB or BGR |
| Brightness | 0.25 – 4.00 | 1.25 | Compensates the grid |
| Gamma | 0.50 – 2.00 | 1.00 | |

**Tips**

- **Set stripe order to BGR (1) for Game Boy Advance content.** The GBA panel really is laid out blue-green-red, so RGB puts the colour fringes on the wrong side.
- **Row/column balance** decides which way the grid leans. Real panels are row-dominant; around 0.80 matches the look of `lcd1x` if that is what you are used to.

#### dmg-perfect

| Parameter | Range | Default | |
|---|---|---|---|
| Grid visibility | 0.00 – 1.00 | 0.30 | |
| Grid line thickness | 0.25 – 2.00 | 1.00 | In output pixels |
| Dot shadow | 0.00 – 1.00 | 0.00 | Off by default |
| Brightness | 0.25 – 4.00 | 1.00 | |
| Gamma | 0.50 – 2.00 | 1.20 | |
| Cool / warm balance | −1.00 – 1.00 | 0.00 | Above 0 is warmer |
| Magenta / green balance | −1.00 – 1.00 | 0.00 | Above 0 is greener |

**Tips**

- **Grid line thickness is in output pixels**, not a fraction of a cell, so the panel reads the same at 640x480 as at 1024x768. 1.00 is a one-pixel line.
- **Dot shadow** lifts the dots off the panel, as if lit from above. It is off by default and free until you turn it on. Only driven pixels cast one.
- The **balance pair** is worth a small trim, because Game Boy palettes vary a lot between emulator cores and none of them is neutral.

> [!TIP]
> To brighten a picture, use **brightness**, not gamma. Brightness clips the highlights, and that is what a real CRT or LCD does when you turn it up — gamma instead lifts the mid-tones, which washes out the colours and flattens the contrast.

## Performance

Measured against [`pixellate`](tools/vendor/pixellate.glsl), the shader most people already use for clean upscaling, at 320x240 into 1024x768.

| Shader | Instructions | Texture taps | Special-function ops | Frame time vs `pixellate` |
|---|---|---|---|---|
| `pixellate` (baseline) | 292 | 4 | 30 | 100% |
| **`pixel-perfect`** | **190** | 4 | **6** | **79%** |
| `dmg-perfect` | 498 | 8 | 6 | 103% |
| `lcd-perfect` | 396 | 4 | 23 | 107% |
| `crt-perfect` | 610 | 4 | 14 | 108% |

`pixel-perfect` is a drop-in replacement for `pixellate` that produces the same image for a fifth less work. The three effect shaders do considerably more and still land within a tenth of it, because the expensive part of all four is the same scaler underneath.

The counts come from the compiled shader and are exact. The frame times are from a desktop GPU, not a handheld — treat them as a ranking, not as milliseconds you will see on a device, and note that no difference under about 2% is bigger than the measurement noise.

Everything that can be switched off is behind a check on the parameter itself, so a control left at its default is skipped entirely rather than computed and thrown away. Turning curvature, the shadow or a colour balance off costs nothing.

## Related

- **[RetroShader Lab](https://github.com/sinedied/retroshader-lab)** — browser bench
  that runs the same pipeline, for iterating in milliseconds instead of SD-card round
  trips. **[Open the lab](https://sinedied.github.io/retroshader-lab/)**
- **[NextUI](https://github.com/LoveRetro/NextUI)** — the handheld firmware these
  were tested on.

## Licence

MIT, see [LICENSE](LICENSE). Shaders under `tools/vendor/` are third-party, kept only
as benchmark references, each under its own licence as stated in its file header.
