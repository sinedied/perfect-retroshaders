<div align="center">

# perfect-retroshaders

**My take on the "perfect" retro shaders: a convincing CRT look that doesn't cost you
performance, brightness, or your sanity.**

![GLSL](https://img.shields.io/badge/GLSL-ES%201.00-5586A4?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-3DA639?style=flat-square)

</div>

## What this is

Retro shaders are usually tuned on a desktop GPU and then wilt on a handheld: they eat
the frame budget, wash the picture out, or paint moiré across every scrolling
background. These are built the other way round — the constraint comes first.

- **A nice retro look without compromising performance.** The current version costs
  less than `pixellate.glsl`, a scaler that already ships on the target device and
  holds 60fps there.
- **No brightness loss, no moiré, no artifacts.** Not "reduced" — measured. Every
  version is checked against a numerical model and a real GPU, and the moiré figure is
  a number in a table, not an opinion.
- **Good defaults, tweakable, easy for non-technical users.** Sensible out of the box,
  seven parameters if you want them, and the scanline count follows the content
  automatically — 224-line content gets 224 scanlines with nothing to configure.
- **Built for cheap hardware.** Target is a Mali G31 MP2 at 1024x768/60, and it works
  down to a 640x480 output.

## Shaders

| File | |
|---|---|
| `shaders/crt-perfect-v5.glsl` | **current.** Scanlines, RGB mask, pixel-perfect scaling, gamma |
| `shaders/crt-perfect-v5b.glsl` | same, with gamma applied after scaling — cheaper, slightly less moiré-immune |
| `shaders/crt-perfect-v4.glsl` … `crt-perfect.glsl` | earlier iterations, kept so the trade-offs stay visible |
| `shaders/pixellate.glsl` | third-party (Fes), included as the performance baseline |

### Parameters

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

## Screenshots

_To add: side-by-side captures from the device._

## Development

Verification harness in `tools/` — an independent numpy model of each shader, diffed
against the real `.glsl` running on a GPU, plus static cost analysis from SPIR-V.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install glslang

.venv/bin/python tools/validate_glsl.py shaders/*.glsl
cd tools && PYTHONPATH=. ../.venv/bin/python spirv_cost.py
cd tools && PYTHONPATH=. ../.venv/bin/python gl_check.py
```

See [AGENTS.md](AGENTS.md) for the design rules, the traps, and the things that turned
out to be wrong.

## Related

- **[RetroShader Lab](https://github.com/sinedied/retroshader-lab)** — browser bench
  that runs the same pipeline, for iterating in milliseconds instead of SD-card round
  trips. **[Open the lab ▶](https://sinedied.github.io/retroshader-lab/)**
- **[NextUI](https://github.com/LoveRetro/NextUI)** — the handheld firmware these
  target.

## Licence

MIT — see [LICENSE](LICENSE). `shaders/pixellate.glsl` is third-party, by Fes, under
its own permissive licence reproduced in the file header.
