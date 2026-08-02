# The `*-mini` line

Four shaders that draw an effect and nothing else. No scaler, so you choose what
goes in front — or put nothing in front and let the frontend upscale.

| mini | its turbo | what it draws |
|---|---|---|
| `colour-mini` | `pixel-turbo` | grading only: brightness, contrast, saturation, gamma, temperature, tint |
| `dmg-mini` | `dmg-turbo` | dot matrix, cell shadow, grading |
| `lcd-mini` | `lcd-turbo` | mesh, RGB stripes, cast correction, grading |
| `crt-mini` | `crt-turbo` | scanlines, mask, curvature, slot grille, grading |

They are versioned to match their turbo, so `*-mini-v2` is the first of them:
a mini and its turbo always carry the same number.

## The hard contract: 1:1, and never `TextureSize`

A mini shader takes exactly one tap, at the coordinate it was handed:

```glsl
vec3 color = COMPAT_TEXTURE(Source, vTexCoord).rgb;
```

and derives its pattern pitch from `InputSize` and `OutputSize` only.

**`TextureSize` is unusable here**, and this is a frontend quirk rather than a
style choice: a later pass is handed the *original source size* in `TextureSize`
and `InputSize`, not the size of the texture it is actually sampling. Recorded
in `docs/device-perf.md`. Using `vTexCoord` alone makes the same shader correct
as pass 1, where the frontend upscales, and as pass 2 behind any scaler.

The sampler is **LINEAR**, declared in `baseline.toml`. Verified: a LINEAR tap
at 1:1 is exact — max difference 0/255 against NEAREST — so it costs nothing
behind a scaler, and in front of one it gives `crt-mini`'s warp a free smooth.

Run standalone, a mini gets whatever the frontend's own upscale produces, which
is a plain bilinear stretch. That is softer than any scaler in this repo and it
is the documented behaviour, not a defect: if you want a sharp scale, put one in
front.

## What it costs

| stack | passes | ops | tex | device ms | frame |
|---|---:|---:|---:|---:|---:|
| `colour-mini` | 1 | 20 | 1 | *2.6* | *16%* |
| `dmg-mini` | 1 | 148 | 2 | *7.2* | *43%* |
| `lcd-mini` | 1 | 218 | 1 | *8.7* | *52%* |
| `crt-mini` | 1 | 264 | 1 | *10.1* | *60%* |
| `pixel-turbo → dmg-mini` | 2 | 201 | 3 | *9.5* | *57%* |
| `pixel-turbo → lcd-mini` | 2 | 271 | 2 | *10.9* | *66%* |
| `pixel-turbo → crt-mini` | 2 | 317 | 2 | *12.4* | *74%* |

All predicted; see `docs/optimized.md`.

**A chain is not cheaper than the turbo shader that does the same thing.**
`pixel-turbo → lcd-mini` is 66% against `lcd-turbo`'s 64%, and `pixel-turbo →
crt-mini` is 74% against `crt-turbo`'s 67%. The split moves the scaler's work
into its own pass; it does not remove it.

What the split buys is choice, and there are three worth naming:

1. **A cheaper or different scaler in front.** `sharp-shimmerless → lcd-mini` is
   65%. So is `pixel-turbo → lcd-mini` at 66% — the two scalers are the same
   function, see `docs/optimized/pixel-turbo.md` — but a user who wants a softer
   or an integer scale can now have one.
2. **No scaler at all.** `lcd-mini` alone is 52% of a frame against
   `lcd-turbo`'s 64%. If the frontend's bilinear is acceptable, that is 12
   points of frame time back.
3. **Grading in the right place.** `colour-mini` at *source* resolution in front
   of the scaler costs 0.2 ms and removes the moiré exception the turbo line
   takes. This is the important one, and it has its own section in
   `docs/optimized.md`.

## `lcd-mini` is the one that gets structurally cheaper

`lcd-turbo` weights its single tap by the mesh aperture rather than by footprint
overlap, because the mesh's dark line and the scaler's soft transition pixel both
sit on the cell boundary and correlate — dropping it measured 1.890 moiré
against 0.118. That machinery (`Alo`, `AB`, the boundary sine) is 70 of its 190
floor ops.

`lcd-mini` has no blend to weight, so all of it goes: **120 ops of floor against
190**. It is the only mini where removing the scaler removes real arithmetic
rather than moving it.

`crt-mini` saves less (252 against 289) because most of `crt`'s floor is
band-limit machinery that the pattern needs regardless. `dmg-mini` saves 20 ops.
`colour-mini` saves 33.

## How they gate

Single-pass, where the harness and the C benchmark agree byte for byte — all
four are checked that way in `tools/tests/device.py`, max delta 0.

They are declared `passthrough` in `baseline.toml`, which does two things:

- the scaler anchor is **skipped**, because a mini is not a scaler and cannot
  equal `pixel-perfect`;
- a replacement anchor is checked instead: **at 1:1, with every pattern off, the
  picture must come through untouched**, at 320x240, 256x224 and 480x272.

A chain is only checked for having drawn something. The Python renderer has no
equivalent of the `TextureSize` quirk, so a two-pass render here would not be
the render the device performs; that comparison belongs on the device, and
`tools/device/pipelines/` carries eight chains for it.

## Presets

`tools/device/pipelines/` has the assemblies as `.cfg` files, which are the same
format a user installs. The one worth copying is the source-resolution grade:

```
minarch_nrofshaders = 2
minarch_shader1 = colour-mini-v2.glsl
minarch_shader1_upscale = 1          # source resolution, not screen
minarch_shader2 = pixel-turbo-v2.glsl
minarch_shader2_upscale = screen
```

`upscale = 1` is the whole trick: pass 1 renders at 320x240 rather than
1024x768, so 20 ops cost a tenth of what they would at the far end.

Two deployment notes from `docs/device-perf.md`, both of which have bitten:

- the host caches compiled programs at `SDCARD_PATH/.shadercache/<filename>.bin`,
  **keyed on filename only, with no content hash**. Delete it on every copy.
- a preset resolves its shader by filename and **returns index 0 on no match**
  rather than erroring, so a preset naming a missing shader silently loads
  whichever sorts first.
