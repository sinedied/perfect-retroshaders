# AGENTS.md — perfect-retroshaders

GLSL retro shaders (CRT scanlines + RGB mask + pixel-perfect scaling) for cheap
handhelds. Target: **Trimui Brick, 1024x768, Mali G31 MP2, GLES 3.2, 60fps** — that is
47 Mfrag/s, and the shader also pays for a final 1:1 blit. Also expected to work down
to a 640x480 output. MIT.

No build, no test suite. Verification is the Python harness in `tools/`.

## Layout

| Path | What |
|---|---|
| `shaders/crt-perfect-v5.glsl` | current version. Host-neutral header, `cp_`-prefixed params |
| `shaders/crt-perfect-v5b.glsl` | v5 with gamma applied after scaling instead of per-tap |
| `shaders/crt-perfect{,-v2,-v3,-v4}.glsl` | historical iterations, kept for comparison |
| `shaders/pixel-perfect.glsl` | scaling only, no CRT effect. `pp_`-prefixed params |
| `tools/` | the verification harness |
| `tools/vendor/` | **third-party shaders**, benchmark and comparison references only |

`shaders/` holds only shaders this repo owns and licenses. Anything third-party lives
in `tools/vendor/`: not part of the MIT grant, not edited, present purely to measure
against. Currently `pixellate.glsl` (Fes) — **30 SFU slots**, ships on the target
device and holds 60fps there, so it is the budget yardstick every cost figure here is
quoted against.

Tools resolve a bare shader filename against `shaders/` then `tools/vendor/` via
`tools/paths.py`, so a new benchmark shader only needs dropping into `vendor/`.
`spirv_cost.py` discovers both automatically.

v1–v4 headers still document frontend-specific pass settings and their own version
history; that is deliberate, they are the record of how each step was reached. v5 and
v5b are the host-neutral ones.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install glslang          # glslangValidator + spirv-dis, not a Python package
```

## Workflow

Run the tools from `tools/` with `PYTHONPATH=.` (they import each other):

```sh
.venv/bin/python tools/validate_glsl.py shaders/*.glsl      # 1. does it compile?
cd tools && PYTHONPATH=. ../.venv/bin/python spirv_cost.py  # 2. what does it cost?
cd tools && PYTHONPATH=. ../.venv/bin/python gl_check.py    # 3. does it do what you think?
cd tools && PYTHONPATH=. ../.venv/bin/python equivalence.py # 4. pixel-perfect vs pixellate
```

To iterate on a shader:

1. Edit the `.glsl`.
2. **Mirror the change in `tools/crt_preview.py`.** It is an independent numpy
   implementation of the same maths. `gl_check.py` runs the real shipped `.glsl` on a
   GPU and diffs it against that model; a mismatch means one of the two is wrong.
   Target is worst ≤ 1/255 (pure float32-vs-float64 rounding).
3. `spirv_cost.py` for cost. It is call-graph aware and counts scalar-expanded
   transcendentals (`pow` = log2+exp2 = 2 slots). **This is the cost metric to trust.**
4. `measure.py` for pattern geometry (period, contrast, mask swing) when matching a
   reference look.

`bench_glsl.py` exists but **GPU wall-clock timing on a dev Mac is not trustworthy** —
`pixellate` swapped between slowest and fastest across runs with ~25% spread. Use the
static SFU count and compare against `pixellate.glsl`'s 30.

The two independent implementations are the whole point of this setup: an error has to
be made identically in GLSL and in numpy to slip through. It has happened once (see
`pow(0,k)` below), so also sanity-check on a real GPU rather than the model alone.

## The one design rule

**Nothing non-linear may be applied after the scaler's blend.**

The scaler area-averages four taps. At a non-integer scale a source pixel covers three
or four output pixels, so the count of partial-coverage pixels varies block to block.
Any non-linearity applied after the blend gives those pixels a coverage-dependent
shift, and that shift beats against the pixel grid as visible moire.

Three separate, individually reasonable ideas each broke this and each brought the
moire back. Measured as low-frequency energy on a checkerboard at 320x240 → 1024x768,
where anything above ~0.2 is visible:

| What | Beat | Note |
|---|---|---|
| baseline, nothing non-linear after the blend | **0.02** | |
| linearise taps → blend → re-encode (v1/v2) | 3.35 | the original bug |
| output gamma after the blend | 1.53 at γ=1.4, 3.06 at γ=2.0 | how `dmg_dot_matrix` does it |
| `clamp(x,0,1)` from `cp_brightness > 1` | 0.13 at 1.25, 4.84 at 4.0 | the clamp *is* a non-linearity |

The fixes: blend in the encoded domain and modulate with a single `sqrt` (gamma 2.0
makes `sqrt(linear*m) == encoded*sqrt(m)`); apply `cp_gamma` to the four taps *before*
the blend; and treat `cp_brightness` above ~1.5 as a look, not a correction —
`cp_gamma < 1` brightens more, with zero clipping and zero added beat.

A soft shoulder does **not** rescue a post-blend curve. Reinhard measured 2.48 where
the hard clamp measured 0.26, because it curves the whole range instead of just the
top. Do not re-try this.

## GLSL traps that actually bit

- **`pow(0.0, k)` is undefined** and returned NaN on a real driver, rendering whole
  scanline rows black. Black texels are everywhere. Always clamp the base:
  `pow(max(x, 1e-8), g)`. Use 1e-8, not 1e-5 — the latter lifts pure black to 1/255 at
  γ=0.5.
- **Never branch on an exact comparison of a division result.** GPUs evaluate `a/b` as
  `a*rcp(b)`, so `720.0/240.0` can land a few ULP off 3.0 while the numpy model gets
  exactly 3.0. A `step()` on that flipped a whole rendering regime and ~30% of
  contrast. Use a narrow, biased `smoothstep` instead.
- **`floor()` used for row parity** has its argument cross whole numbers once per line;
  a few ULP flips an entire row's mask stagger. Add an epsilon: `floor(x + 1e-3)`.
- **`sqrt()` of an analytically-non-negative value** can still see a small negative in
  float. Clamp with `max(..., 0.0)`.
- `#pragma parameter` menus display the **identifier**, not the quoted label. Name
  parameters so they read correctly on their own.
- **A uniform the host never sets is 0.** If a parameter appears in a divisor, an
  unset uniform makes every pixel NaN — a black screen, not a subtle error. Guard it:
  `max(0.4995 * pp_sharpness * InputSize / OutputSize, 1e-6)`. This matters whenever a
  host does not parse `#pragma parameter`.
- **`mix(x, y, w)` returns `y` at `w == 1`.** When `w` means "weight on the low side",
  the low-side value must be the *second* argument. Getting it wrong on one axis only
  is invisible by eye and obvious against a reference model.

## pixel-perfect vs pixellate

`pixel-perfect.glsl` reproduces the widely used `pixellate.glsl` exactly, at a
fraction of the cost. Two things in the original are redundant:

- The four corner-area products and the divide by `totalArea` factor into one
  horizontal and one vertical weight. Verified over 200k random configurations: max
  difference **2.5e-15**.
- The 15 `pow()` calls implement `INTERPOLATE_IN_LINEAR_GAMMA`, which linearises each
  tap, blends, then re-encodes — the same gamma round-trip that breaks the design rule
  above. It is `pixellate`'s **default**, and it measures 3.5–5.7 beat where the
  encoded-domain path measures 0.000.

| | ops | tex | SFU |
|---|---|---|---|
| `pixellate.glsl` | 292 | 4 | 30 |
| `pixel-perfect.glsl` | 112 | 4 | **0** |

Four taps stay: an output footprint spans up to two texels per axis, so four is the
minimum without delegating the blend to the texture unit. A one-tap LINEAR variant was
prototyped and is exactly equivalent (1/255, identical block widths and shimmer), but
was rejected — it makes correctness depend on the GPU's subtexel bilinear precision and
needs the opposite sampler setting to everything else here.

`tools/equivalence.py` proves the match: output diff, block-width distribution,
transition-pixel counts, moire, and the `pp_sharpness` response.

## Measurement traps

Three tooling bugs produced confident, wrong numbers before being caught. Sanity-check
a metric before trusting it — verify it returns ~0 for a known-good case and that its
numbers scale sensibly.

- **Benchmark loop**: timing N draws with one `glFinish` at the end lets the driver
  coalesce them; cost per draw fell 8.6 → 4.8 µs as N grew from 100 to 1600. Per-draw
  GPU timer queries are required.
- **SPIR-V parser**: splitting on the *last* `OpFunction` reported "7 ops, 0 SFU" for a
  shader with helper functions. It must walk the call graph and expand helpers by call
  count.
- **Beat metric**: a fixed "periods 6–64px = moire" band counts the *pattern itself* as
  moire once its pitch or repeat length enters that band. Measure above each pattern's
  own repeat length (a pitch of k/4 repeats every k pixels).

Also: the desktop GL context is 4.1 Core, so ESSL-1.00 shaders do not run there. The
harness compiles them as `#version 410 core` via the compat macros; the device is the
only true target.

## Assumptions this session got wrong

Do not re-derive these.

- *"An RGB triad needs ≥3 output pixels."* False. 2.67px works because `8/3` is exactly
  periodic — 3 cycles span 8 pixels. The criterion is **exact periodicity on the pixel
  grid**, not absolute pitch. Any pitch of k/4 repeats every k pixels.
- *"A 2.0px pitch is unusable."* Only because of sample phase: centres land at 0.25 and
  0.75, symmetric about the beam peak, returning identical values. A half-pixel shift
  gives full contrast, and fixes every even-integer pitch.
- *"`pow(cos, k)` is a single frequency."* Only when `k == 1`. Other exponents add
  harmonics, and harmonics alias before the fundamental does.
- *"Fading a pattern out near Nyquist is enough."* The fade must reach zero **at** 2
  output pixels per cycle, not at 1. Between 1 and 2 the pattern folds to a wrong,
  coarser pitch at near-full amplitude.
- *"The reference CRT overlays lock their pattern to the source pixels."* They do not.
  They use a fixed output-space pitch regardless of content resolution.

## Reference measurements

The overlays these shaders were matched against are not redistributed here. Their
measured properties, on a white field:

| Overlay | Native | Pitch | Mean level | Scanline swing | Mask swing |
|---|---|---|---|---|---|
| "crt" | 640x480 | 3.00px → 160 lines, 213 triads | 88.8% | 66.5 | 13.3 |
| "240p" | 640x480 | 2.67px → 180 lines, 240 triads | 80.4% | 65.0 | 38.8 |
| crt-perfect v5 defaults | — | — | 83.9% | 63.8 | 40.9 |

Both masks are luminance-neutral, which three primaries 120° apart reproduce exactly.

## Deployment gotchas (NextUI / minarch targets)

- The host caches compiled programs at `SDCARD_PATH/.shadercache/<filename>.bin`, keyed
  on **filename only, no content hash**. A stale binary keeps running silently after an
  edit. Delete it on every copy.
- A preset resolves its shader by filename and **returns index 0 on no match** rather
  than erroring — so a preset naming a missing shader silently loads whichever shader
  sorts first. Copy the `.glsl` before selecting a preset that references it.
- Presets are not kept in this repo; each shader header documents the pass settings a
  host must provide.

## Related

- [RetroShader Lab](https://github.com/sinedied/retroshader-lab) — browser bench that
  ports the NextUI pipeline exactly (same pass sizing, uniforms, GLSL preprocessing).
  Much faster than a device for visual iteration.
  **Note:** its `AGENTS.md` still documents syncing shaders from `~/projects/NextUI`.
  Since crt-perfect now lives here, that path needs repointing to this repo.
- [NextUI](https://github.com/LoveRetro/NextUI) — the firmware these target. Pipeline
  semantics live in `workspace/all/common/generic_video.c` and
  `workspace/all/minarch/ma_config.c`.

## Commits

Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `perf:`. 
