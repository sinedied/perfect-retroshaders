<div align="center">

# 📺<br>perfect-retroshaders

**My take on the "perfect" retro shaders: a convincing retro look that doesn't cost you
performance, brightness, or your sanity.**

<!-- TODO: add extra badge for fun, something like Retro|Pixels with a fun logo -->
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

<!-- TODO: 1-line intro here, then keep the descriptions below short and to the point for each shader. Include notes and limitations where relevant, as well as tips (for example GBA has a BGR lcd IIRC). Saying to use gamma instead of brightness to brighten is NOT a good tip, as it kills the contrast and wash out the colors. Brightness clips, yes, but matches more the look of old CRTs and LCDs, which is what we're trying to simulate. -->

#### pixel-perfect

TODO

> [!NOTE]
> Output is identical to the well-known `pixellate` shader with default params, but with a better performance.

#### crt-perfect

TODO

#### lcd-perfect

TODO

#### dmg-perfect

TODO

## Performance

<!-- TODO: performance tests: pixellate (baseline), pixel-perfect, crt-perfect, lcd-perfect. Include a table with the results and a graph, including real GPU usage. For the retroshaders, 2 entries for each shader: one with default params, one with max params (for example, crt-perfect with max scanlines and rgb mask). -->

## Related

- **[RetroShader Lab](https://github.com/sinedied/retroshader-lab)** — browser bench
  that runs the same pipeline, for iterating in milliseconds instead of SD-card round
  trips. **[Open the lab](https://sinedied.github.io/retroshader-lab/)**
- **[NextUI](https://github.com/LoveRetro/NextUI)** — the handheld firmware these
  were tested on.

## Licence

MIT, see [LICENSE](LICENSE). Shaders under `tools/vendor/` are third-party, kept only
as benchmark references, each under its own licence as stated in its file header.
