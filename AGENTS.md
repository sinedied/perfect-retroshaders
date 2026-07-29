# AGENTS.md — perfect-retroshaders

GLSL retro shaders (CRT scanlines + RGB mask + pixel-perfect scaling) for cheap
handhelds. Target: **Trimui Brick, 1024x768, Mali G31 MP2, GLES 3.2, 60fps** — that is
47 Mfrag/s, and the shader also pays for a final 1:1 blit. Also expected to work down
to a 640x480 output. MIT.

No build, no test suite. Verification is the Python harness in `tools/`.

## Layout

| Path | What |
|---|---|
| `shaders/crt-perfect.glsl` | CRT: scanlines + RGB mask + pixel-perfect scaling. `cp_` params |
| `shaders/lcd-perfect.glsl` | LCD: analytic aperture coverage. `lp_` params |
| `shaders/pixel-perfect.glsl` | scaling only, no effect. `pp_` params |
| `tools/` | the verification harness |
| `tools/vendor/` | **third-party shaders**, benchmark and comparison references only |
| `tools/iterations/` | superseded versions of our own shaders, kept for the record |

`shaders/` holds only the shaders this repo ships. Anything third-party lives in
`tools/vendor/`: not part of the MIT grant, not edited, present purely to measure
against. Currently `pixellate.glsl` (Fes) — **30 SFU slots**, ships on the target
device and holds 60fps there, so it is the budget yardstick every cost figure here is
quoted against.

Tools resolve a bare shader filename against `shaders/`, then `tools/vendor/`, then
`tools/iterations/` via `tools/paths.py`, so a new benchmark shader only needs dropping
into `vendor/`. `list_shaders()` returns only `shaders/` unless asked for more, so the
archive does not pollute a compile report; `spirv_cost.py` asks for all three.

### The archive

`tools/iterations/crt-perfect-v{1..5}.glsl`. They stay **registered in
`tools/shaders.py` and verified on every `gl_check.py` run** — an archive that is not
executed rots, and their tolerances encode real findings.

- **v1–v4 predate the `cp_` prefix.** Their params are `Scanlines`, `Mask_Type` and so
  on. Setting `cp_*` on them silently does nothing.
- v1–v4 headers still document frontend-specific pass settings and their own version
  history. That is deliberate: they record how each step was reached.
- **v5 is not strictly superseded.** It applies `cp_gamma` to the four taps instead of
  to the scaled image, so it holds the moire fix at every gamma (0.13 flat) where the
  shipped shader does not (1.68 at gamma 1.4). It costs 32 SFU slots against 14. The
  shipped shader took the cheaper placement because the two are **bit-identical at the
  default `cp_gamma = 1.00`**, which is the only place the difference is free.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install glslang          # glslangValidator + spirv-dis, not a Python package
```

## Workflow

Run the tools from `tools/` with `PYTHONPATH=.` (they import each other):

```sh
.venv/bin/python tools/validate_glsl.py shaders/*.glsl        # 1. does it compile?
cd tools && PYTHONPATH=. ../.venv/bin/python spirv_cost.py    # 2. what does it cost?
cd tools && PYTHONPATH=. ../.venv/bin/python gl_check.py      # 3. does it do what you think?
cd tools && PYTHONPATH=. ../.venv/bin/python equivalence.py   # 4. pixel-perfect vs pixellate
cd tools && PYTHONPATH=. ../.venv/bin/python beat.py          # 5. does it paint moire?
cd tools && PYTHONPATH=. ../.venv/bin/python check_headers.py # 6. does the header still match?
```

`gl_check.py` walks the registry in `tools/shaders.py`; add a shader there and it is
checked with no further wiring. A `Model` may raise its `tolerance` above 1 only with
a `reason` naming a mechanism that has been measured — the reason is printed next to
the result, so a tolerated divergence stays visible rather than silently accepted.

To iterate on a shader:

1. Edit the `.glsl`.
2. **Mirror the change in `tools/crt_preview.py` or `tools/lcd_preview.py`.** It is an independent numpy
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

## Shader header format

Every shipped shader opens with this block. **Line comments, hard 80-column limit**
(the separator is `// ` + 77 dashes, exactly 80). Order is fixed: name, licence,
parameters, description, notes.

```glsl
// <name> - <one-line description, lowercase, ending in a period.>
// -----------------------------------------------------------------------------
// Author:  sinedied
// Licence: MIT - Copyright (c) 2026 sinedied
//
// <the MIT paragraph, wrapped to 80, identical in every file>
// -----------------------------------------------------------------------------
// PARAMETERS
//
//   <xx_name>  <range>  <Sentence. What 0 or 1.00 does.>
// -----------------------------------------------------------------------------
// <What it does, in one short paragraph. Five or six lines is plenty.>
//
// Notes:
// - <One or two phrases. Two or three notes. Omit the section if there is
//   nothing worth warning about.>
```

Then one blank line, then the `#pragma parameter` lines, column-aligned.

- **One paragraph, then `Notes:`.** Each note is one or two phrases, not a paragraph.
  The header is a user-facing reference; rationale, measurements and rejected
  approaches belong in this file or in a commit message. Both earlier drafts erred
  long and had to be cut twice.
- Ranges are written `0.00 - 1.00`, or `0 / 1 / 2` for enum-like parameters.
  Descriptions that do not fit wrap aligned under the description column.
- **Write the block out whole; never patch it incrementally.** Regex-editing these
  headers during the repo extraction produced stray `..` fragments and a duplicated
  copyright block, and took three attempts. Build the lines, assert none exceeds 80,
  splice on the first delimiter, then diff.
- Parameter identifiers are prefixed per shader (`cp_`, `lp_`, `pp_`) and lowercase.
- **The `#pragma parameter` label and the identifier are both user-visible, on
  different hosts.** RetroArch and RetroShader Lab render the quoted label; **minarch
  renders the identifier** (`ma_config.c` uses `params[j].name`). So the identifier
  has to read acceptably on its own *and* the label has to be worth reading. Do not
  flatten the label into a copy of the identifier — that happened between v4 and v5,
  and again in `pixel-perfect`, losing the descriptions on every host that shows them.
- The 80-column rule covers the header and the `#pragma` lines. The shader bodies
  predate it and are **not** being reflowed — that would churn the diff against
  upstream for no gain.

`tools/check_headers.py` enforces all of the above, including that the PARAMETERS
block and the `#pragma` lines agree on identifiers, order and ranges, and that every
default sits inside its own range. Run it after editing a header; it exits non-zero,
so it can gate a commit.

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

**The rule has a second half, found while building `lcd-perfect`:** multiplying a
scaled image by a pattern is *itself* a violation whenever the pattern's dark part
lands where the scaler's soft transition pixel lands. That construction computes
`mean(source) * mean(pattern)` where it owes `mean(source * pattern)`; the two differ
by their covariance inside the pixel, and if pattern and transition are locked to the
same cell boundary that covariance is large and varies cell to cell. It measured 2.5,
twelve times the visible threshold, with no non-linearity anywhere. The fix is to
weight the blend by how much *aperture* falls each side of the boundary rather than
how much area — exact, and free when the aperture's integral is exactly `x` at an
integer boundary. crt-perfect gets away with the naive form only because its pattern
peaks at the cell *centre*.

**Normalise a modulation on its peak, not its mean.** Mean-normalising is tempting —
the pattern then costs no brightness at all — but it puts the pattern's top above 1,
so every bright pixel meets the output clamp, which is the post-blend non-linearity
the table above already convicts. Measured on `lcd-perfect`: mean-normalised, beat
0.60 and grid contrast 37; peak-normalised, beat **0.22** and contrast **58**. Better
on both axes at once. Give the level back with gamma below 1, never with gain.

## LCD apertures, and why they are not sinusoids

An LCD cell is a rectangle in a black matrix, and the mean of a rectangular pulse
train over an output pixel has a closed form. So `lcd-perfect` differences an
antiderivative instead of band-limiting a sinusoid: `floor`, `clamp`, one divide,
**zero transcendentals**, and it is the true box filter rather than an approximation
of one. libretro's `coverage.inc` (`intersect_rect_area`, used by `authentic_gbc`) is
the same idea in 2D; the separable 1D form is cheaper.

Three things that took measuring:

- **Put the aperture at the leading edge of the cell, not centred.** Centring splits
  the matrix line across a cell boundary, so at *every* integer scale factor it lands
  half in one output pixel and half in the next and contrast halves — at exactly 2.0
  output pixels per cell the halves are symmetric and the grid vanishes entirely.
  Edge-alignment fixes all of them and needs no phase-shift term. Dense sweep 2.0–8.0:
  centred min 0.000 / median 1.21, edge min 0.500 / median 1.25.
- **A hard-edged aperture aliases.** A rectangle carries every harmonic of the cell
  frequency; those above Nyquist fold back, and at 3.2 output pixels per cell the
  third harmonic lands on a 16-pixel period, squarely visible. A one-pixel box
  prefilter only attenuates it ~15×, nowhere near enough. Widening the edge into a
  ramp of **twice the matrix width** took the worst measured beat from 2.52 to 0.23.
  Note this is invisible unless you compare **at matched contrast** — softening also
  raises contrast, so at fixed visibility it looks useless or worse. It was nearly
  discarded for exactly that reason.
- **Subpixel stripes do not band-limit themselves.** Their pattern repeats once per
  cell however thin the stripes are, so unlike the cell grid they never flatten; below
  ~3 output pixels per cell they become colour speckle at full strength. They need an
  explicit fade. They also cost beat far faster than the grid (0.24 at 0.20, 0.56 at
  0.35, 1.18 at 0.50) and, unlike the grid, want **mean** normalisation — a stripe
  concentrates one channel's light into a third of the cell, so its mean is what must
  stay at 1 for white to stay white, which inherently puts its peak near 3. Faking
  subpixels either darkens or clips; there is no third option.

`simpletex_lcd`'s luma-biased grid (`lineWeight *= luma + (1-luma)*(1-BIAS)`, "hide
the grid on dark pixels") is **not** safe here: it computes the gain from the blended
colour and multiplies it back, which is a non-linearity after the blend. Measure
before adopting.

**Out of scope for `lcd-perfect`, decided deliberately** (this used to live in the
shader header; it is here so it is not re-litigated):

- **Response-time ghosting.** Needs the previous frame, so it needs a feedback pass,
  and the intended hosts run single-pass GLSL only.
- **Backlit versus reflective response, and panel colour casts.** Those belong to a
  colour pass, not to a geometry one.
- **Non-square pixels.** Every panel in scope is square-pixel.

One measured wrinkle to know about: the stripes leave a tint of about one 8-bit level
on a white field, because the `sqrt` is applied per channel and the three stripes do
not sample the same phases.

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
- **Beat metric, second attempt**: low-passing with a box exactly one pattern repeat
  wide removes the beat *along with* the pattern — at a rational scale factor the whole
  image is periodic at that length, so nothing survives and everything reads 0.00,
  known-bad constructions included. `tools/beat.py` now bands explicitly: keep only
  what is slower than **half a cycle per source pixel**, which is below both the 1px
  checkerboard's own impulse and the pattern's fundamental, so whatever is left was
  manufactured by the shader.
- **Beat metric, colour space**: measuring in linear light instead of code values
  *inverts* the ranking — 4.74 for the known-good baseline against 1.07 for the known-
  bad one. Measure encoded. This was checked rather than assumed, and the assumption
  would have been wrong.

`beat.py` self-tests against the table in *The one design rule* on every run. It
reproduces the ordering exactly at a consistent ~1.9× scale (spread 1.33×), so its
threshold is 0.4 rather than 0.2; the original tool was not in the repo and had to be
rebuilt from its description. A metric whose ratio to the record *drifts* per
construction is measuring something else and must not be trusted.

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
- *"Only even-integer pitches lose contrast to sample phase."* False, and it cost a
  detour. **Every** integer pitch does, for a pattern whose dark part straddles the
  cell boundary — 3.0 measured 0.375 against a possible 0.75, 4.0 measured 0.500
  against 1.000. Moving the dark part wholly inside the cell fixes all of them and is
  cheaper than the shift.
- *"An exact box filter means nothing can alias."* False. A box filter is exact for the
  pixel it covers, but it is a weak *prefilter*: its response only falls as 1/f, so a
  hard-edged pattern's harmonics survive it and fold back. Exactness per pixel and
  band-limiting are different properties.
- *"The float32-vs-float64 gap between GPU and model can be engineered away."*
  Reducing coordinates to their cell before differencing, so rounding cancels, changed
  **not one pixel** — the error arrives in the interpolated texcoord, it is not created
  by the arithmetic. Two `floor`s for nothing; measure before optimising.
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
| crt-perfect defaults | — | — | 83.9% | 63.8 | 40.9 |

Both masks are luminance-neutral, which three primaries 120° apart reproduce exactly.

### LCD panels

Measured off a Game Boy Color, by `authentic_gbc/shared.inc` (pixel-counted from a
macro photograph) and independently by [gbcc.dev](https://gbcc.dev/technology/) under a
microscope. This is the only handheld panel either libretro repo has real numbers for
— GBA, DS and PSP geometry is assumed, not measured.

| | |
|---|---|
| subpixel width | 0.296 of the cell → **~3.7% column matrix** |
| subpixel height | 0.910 of the cell → **~9% row matrix** |
| net fill factor | ~75% |
| stripe order | RGB, left → right |
| pixel aspect | square — GBC, GBA, DS and PSP all are |

So the row matrix is ~2.4× the column matrix, which is why `lp_gap` drives the row gap
and scales the column gap by 0.4 rather than exposing two knobs. Cross-shader consensus
for defaults is 8–12% row matrix, 0–5% column, 25–35% edge darkening.

Note the GBC's primaries are nowhere near pure — pure red reads about `#FF7145` on
sRGB. A white-subpixel shader stacked on already colour-corrected output will look
wrong; that belongs in a colour pass, not here.

### What the LCD shaders being replaced measure

On a 1px checkerboard, 320x240 → 1024x768, white field for the swings:

| Shader | Beat | Mean level | Row swing | Col swing |
|---|---|---|---|---|
| `lcd1x` defaults | 1.87 | 75.3% | 24.0 | 96.0 |
| `lcd3x` | 2.93 | 82.3% | 68.6 | 5.8 |
| `sharp-shimmerless-grid` | 3.14 | 82.8% | 66.6 | 66.6 |
| `lcd-perfect` defaults | **0.24** | 82.5% | 57.6 | 36.2 |
| `crt-perfect` defaults | 0.26 | 83.9% | 63.8 | 40.9 |
| `pixel-perfect` | 0.03 | 100% | 0 | 0 |

`lcd-perfect` sits below crt-perfect's own beat. `lcd-grid-v2` was researched and not
vendored: ~48 SFU slots against `pixellate`'s 30, so it is out of budget before any
discussion of how it looks.

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
