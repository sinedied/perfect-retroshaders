# AGENTS.md — perfect-retroshaders

GLSL retro shaders for cheap handhelds: CRT, LCD, Game Boy DMG, and a plain
pixel scaler. MIT.

**Target: Trimui Brick — 1024x768, PowerVR Rogue GE8300, GLES 3.2, 60fps.** Single pass,
ESSL 1.00, `#pragma parameter` uniforms, loaded by a RetroArch-style frontend
(NextUI/minarch). Expected to work down to a 640x480 output.

The goal is a good retro look that a weak GPU can actually hold: no brightness
loss, no moiré, sensible defaults, tweakable, and comprehensible to someone who
does not read GLSL.

## Layout

| Path | What |
|---|---|
| `shaders/` | **releases only.** Never edit one. Replace only when the owner says so |
| `tools/iterations/` | every version, including the current candidate. Where the work happens |
| `tools/optimized/` | the `*-turbo` line: the same four shaders rebuilt for the device |
| `tools/baseline.toml` | **the one data file** — every shader's role, sampler and limits |
| `tools/{check,measure,perf,test,preview}.py` | the five entry points |
| `tools/common.py` | paths, shader text, GL, sources, reporting |
| `tools/tests/` | per-family behavioural properties, each with its control |
| `tools/vendor/` | third-party shaders, comparison only, not ours and not edited |
| `tools/device/` | the on-device benchmark, in C. Cross-built, run on the Brick |
| `tools/report.py` | a device run's TSV as the README's performance table |
| `docs/<shader>.md` | design record: what was measured, what was rejected, why |
| `docs/optimized/overview.md`, `docs/optimized/` | the same, for the `*-turbo` line. Kept separate on purpose |

### Release and iteration

A release is a **copy** of an iteration the owner has approved, and nothing else
puts a file in `shaders/`. Iterate in `tools/iterations/`; a superseded version
stays there and keeps compiling, because the per-family tests use them as
negative controls.

- `shaders/<family>.glsl` — **no version in the filename**
- `tools/iterations/<family>-v<N>.glsl` — version in the filename
- **the version lives in the header of both**, and `check.py` asserts a release
  is byte-identical to the iteration its header names

`baseline.toml` declares family, role (`released`, `current`, `archive`,
`vendor`), sampler and thresholds. `released` is optional — a family being
worked on has nothing in `shaders/` at all. **Never work out the current version
from a filename**: `max(names)` returns `v8` over `v10`, which silently froze a
gate two versions behind. A shader on disk that nobody declares fails the check,
because dropping out of the matrix silently is the same defect wearing different
clothes.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install glslang          # glslangValidator + spirv-dis, not a Python package
```

Versions are pinned. Several gates are exact byte comparisons between two GPU
renders, and the golden hashes are only meaningful against a fixed stack.

## Workflow

```sh
.venv/bin/python tools/test.py                 # the gate: everything shipping
.venv/bin/python tools/test.py crt-perfect     # one family
.venv/bin/python tools/test.py --all           # golden the archive too
.venv/bin/python tools/test.py --record        # accept a deliberate change

.venv/bin/python tools/preview.py --diff       # look at it
.venv/bin/python tools/preview.py --moire      # show only the beat band
.venv/bin/python tools/preview.py --as-shipped # without the preview overrides

.venv/bin/python tools/perf.py                 # timings, when comparing
.venv/bin/python tools/perf.py --static        # ops and SFU, one second
.venv/bin/python tools/measure.py --self-test  # check the metric, not the shader
```

`test.py` runs `check.py`, the contracts, the per-family properties, `measure.py`
and the goldens. Run the others directly when you want one of them on its own.

To add or change a shader:

1. Copy the current version to `tools/iterations/<family>-v<N+1>.glsl` and edit
   that. **Never edit a file in `shaders/`**, and never edit a superseded
   iteration — both are somebody's fixed reference.
2. Set its header title line to `// <family> v<N+1> - <description>.`
3. Declare it in `tools/baseline.toml`: move `current` onto it, demote the old
   one to `archive`, and add anything it needs a limit or a preview override for.
4. `tools/test.py <family>`.
5. `tools/preview.py` **if the change moves geometry.** Not optional:
   `crt-perfect-v7` passed every number in the harness while having cropped its
   entire image border off-screen, and was caught by a person looking at a
   screenshot.
6. If the goldens moved and you meant it, `--record`.

**When the owner says they tweaked something**, they mean a value or a comment
they changed by hand in the working tree. `git diff` it, read what actually
changed, and run `tools/test.py`. Goldens moving is the expected outcome of a
parameter tweak, not a failure — confirm the change was intended, then
`--record`. See *Never revert* below.

New behaviour that can be stated as a property belongs in
`tools/tests/<family>.py`, with the version that got it wrong kept as a negative
control. A property nobody can regress into is a property with no proof.

**A numpy twin of a shader is a scratch tool, not a repo artifact.** Writing the
same arithmetic twice is genuinely useful while working out what a shader should
do — it caught the anisotropic footprint correction in v6 and a `float32`
`floor()` knife edge twice. It stops earning its keep the moment the version
freezes: over this repo's whole history, every twin-versus-shader disagreement
that reached a commit was resolved by fixing the twin. Write one in `/tmp` while
iterating. Do not commit it.

## Verification, and what it does not cover

Four layers, deliberately:

- **The scaler anchor** — every family, with its effects set to the `neutral`
  values in `baseline.toml`, must equal `pixel-perfect` within 1/255, and
  `pixel-perfect` must equal the vendored `pixellate`. That chains all four
  families to a third-party implementation, for one render each.
- **Properties** — measured from the render, never computed from the formula
  under test. Two of them are worth naming because nothing else can see what
  they see: `moire` is one still frame, and `crawl` is what changes when the
  picture scrolls. Every metric here was single-frame and luminance-only until a
  scrolling colour band was reported from a device that none of them could
  detect. See `docs/measurement.md`.
- **Negative controls** — each property must *fail* on the archived version that
  had the defect.
- **Goldens** — a hash per shader per case. Proves nothing about correctness,
  only that nothing moved since somebody last looked at it. A mismatch is a
  question, not a verdict.

**Now covered: the device.** `tools/device` runs on the Brick, and the answer to
the question this section used to leave open is in `docs/device-perf.md` and the
README table. Two things it settled:

- **Ops AND SFU both cost, and a transcendental costs about ten ordinary ops.**
  Measured by controlled pair, 1024x768: flipping one guarded `vec3 pow()` from
  live to dead removes 6 SFU and **1.34 ms — 8% of a frame** — reproduced on
  four shaders at 0.222 to 0.225 ms per SFU op, against ~0.023 ms for an
  ordinary op. The control is `dmg-turbo` and `dmg-mini`, which ship gamma at
  1.20 so the `pow` runs either way: they moved 0.000 and 0.005 ms.
  **This file twice said the opposite** - first that SFU was the device signal
  (a guess about a Mali), then that time was unrelated to SFU (inferred from six
  rows where ops and SFU were correlated). Both were wrong. Fitted on 47 rows:
  `frag_ms = 0.0278*ops + 0.409*tex + 0.098*sfu + 0.64`, r2 0.961.
  **So: guard every `pow` on the parameter that disables it, and ship that
  parameter neutral if you can.**
- **A uniform-guarded feature is free only if nothing outside the guard depends
  on what it wrote.** Measured by deleting one guarded block at a time from
  `crt-turbo-v3`, each probe byte-identical at the shipped defaults: the slot
  mask costs **0.14 ms** unselected (noise), and curvature costs **3.26 ms with
  `cp_curvature` at 0.00** - 20% of a frame, paid by everyone who never turns it
  on. The difference is that the curvature block writes `uv`, which is the
  texture coordinate, so its presence makes the fetch dependent. Cheap: a term
  added into a pattern. Expensive: anything that moves the sampling position -
  and for those the only fix is a second shader file, not a branch.
- **`perf.py --static`'s `@def` column cannot price an option.** It moved by 2
  ops across that 3.26 ms, because it folds the parameters to literals and then
  deletes the branch a live uniform keeps. Read `live` for a guarded feature.
- **A pass is nearly free.** Frame overhead is 1.46 ms at one pass, 1.64 at two
  and 1.50 at three - flat inside the spread. A pass rendered at source
  resolution costs 0.16 ms, so grading belongs in front of the scaler, where it
  is also the only legal place for it.
- **Desktop ratios did predict the device ordering**, and understated the
  spread. Both rank the six the same way bar `lcd-perfect` and `crt-perfect`,
  which are within 6% of each other on the device.

`perf.py --static` is still the fast signal while iterating; read the `ops` AND
`SFU@def` columns, weight SFU about ten to one, and re-measure on the device
before believing anything close.

**The target GPU was misidentified here as a Mali G31 MP2** until it was
checked. It is an Imagination PowerVR Rogue GE8300 on an Allwinner A133 Plus,
now confirmed by the device itself: `GL_RENDERER: PowerVR Rogue GE8300`,
`OpenGL ES 3.2 build 1.19@6345021`. It matters — that architecture removes
opaque overdraw entirely (measured: 0.019ms against 10.3ms for the same draw
blended) and exposes no GPU timer query at all. See `docs/device-perf.md`.

**Perf is not a gate**, deliberately: GPU timing moves a few percent with laptop
thermals, so it would fail for reasons that have nothing to do with the shader.
`perf.py --static` prints the deterministic half (ops, texture taps, SFU) in a
second, and nothing enforces it.

## Hard contracts

Break one of these and the output is wrong, not merely different:

- **NEAREST sampling.** Each shader computes its own area average from four
  taps; a LINEAR sampler filters underneath it and the result is filtered twice.
  The sampler is declared per shader in `baseline.toml` — read it, don't assume.
- **Render at the output resolution, 1:1 with the display.** Masks, scanlines
  and grids are defined in output pixels; anything that rescales the result
  aliases them.
- **Upscaling only.** Below 1:1 a footprint spans more than two texels per axis
  and four taps cannot average it. Out of scope, not merely untested.

### The one design rule

**Nothing non-linear may be applied after the scaler's blend.** At a non-integer
scale a source pixel covers three or four output pixels, so the count of
partial-coverage pixels varies block to block; any non-linearity applied after
the blend shifts those pixels by an amount that depends on their coverage, and
that beats against the pixel grid as moiré. Gamma round-trips, output gamma and
even a plain `clamp()` from a gain above 1 have each done it. A soft shoulder
does not rescue it — measured worse than the hard clamp. See
`docs/crt-perfect.md`.

**The clamp is the one that keeps being missed.** `lcd-perfect` and
`crt-perfect` both multiplied brightness into the blended colour *and* the
pattern and then clamped the product, which is a non-linearity after the blend
and beats exactly as this rule says. It is invisible at brightness 1.0, worse
with every step above it, and **absent at an integer scale at any brightness** —
that last one being the signature to look for, since at an integer scale every
output pixel has full coverage and there is nothing to beat against. The fix is
to apply brightness to the taps and clamp it there, where a clamp is per source
pixel and cannot vary with coverage. See `docs/lcd-perfect.md`.

**The invariant, stated once:** nothing may exceed 1 by the time the blend is
done. That needs the content clamped before the blend AND every pattern
multiplied in afterwards peak-normalised to 1. `lcd-perfect`'s RGB stripe was the
one pattern in the repo that was not, peaking near 2.

**And nothing spatially varying either.** A multiply is linear, so a pattern
applied after the blend looks legal. It is not: the blend has already collapsed
the footprint to one number, so multiplying by a pattern that varies *inside*
that footprint computes `average(content) × average(pattern)` where the answer is
`average(content × pattern)`. This is a real but much smaller term than the
clamp - it is what `lcd-perfect-v7` was written to fix, at +40% ops, and was
rejected. Recorded so the next person does not re-derive it.

**One tap changes what is possible here.** The `*-turbo` line replaces the four
NEAREST taps with one LINEAR tap — the texture unit computes the same weighted
sum, for any separable weight pair, at `(B + 0.5 - w) / TextureSize`. The
consequence is that *nothing non-linear can be applied per source pixel any
more*, because the blend has already happened inside the sampler. So the fix
above — brightness on the taps, clamped there — is unavailable, and every form
that puts the clamp after the blend was measured and rejected. What works is
shallowing the pattern instead of gaining the picture: both patterns are
peak-normalised to 1, so reducing their depth gives back the light they cost
with no knee and nothing to clip. See `docs/optimized/overview.md`.

## Shader header and comments

Line comments, hard 80 columns, separator `// ` + 77 dashes. Order: title,
licence, `PARAMETERS`, one short paragraph, `Notes:` of one or two phrases each.
Then a blank line and the column-aligned `#pragma parameter` lines.

The title line carries the version, and it is the only place the version is
written down for a release:

```
// dmg-perfect v9 - a Game Boy dot matrix over a pixel-perfect scale.
```

- **In `tools/iterations/` the header version must match the filename.**
  `check.py` gates it. `pixel-perfect-v6` shipped with a header reading `v5` for
  exactly as long as nothing checked.
- Parameter identifiers are prefixed per shader (`cp_`, `lp_`, `pp_`, `dp_`),
  lowercase, **geometry first and colour last**, ending `*_brightness` then
  `*_gamma`, so the same two controls sit in the same place in every shader.
- **The `#pragma` label and the identifier are both user-visible, on different
  hosts.** RetroArch and RetroShader Lab render the label; minarch renders the
  identifier. Both have to read well.
- **Write the block out whole; never patch it incrementally.** Regex-editing
  these headers has produced stray fragments and a duplicated licence block.
- The `#ifdef` fallback `#define`s must equal the `#pragma` defaults. A host
  that does not parse pragmas renders the fallbacks. `check.py` gates this.
- A `PARAMETERS` entry reads `<what it does>. <value> disables it.` That value
  is the **neutral** one, which is not always the default — a visibility control
  is off at 0 and ships at 0.30. `check.py` gates that it is at least inside the
  declared range.

**The description says what the shader draws and what it looks like.** Not how
it works. It is read by someone deciding whether they want this shader, who does
not read GLSL and does not care about Nyquist. No mechanism, no measurements, no
comparisons to other shaders — all of that belongs in `docs/<family>.md`. Six
lines, gated; `lcd-perfect` reached 22 before anything stopped it.

Then `Notes:`, for the handful of things a *user* needs: how to run it, and any
setting that behaves surprisingly.

**Body comments: short, local, 3 lines maximum.** Keep one only if it stops a
misreading of *that line*. "`mix()` returns y at t == 1, so the low-side tap
goes second" earns its place; the reasoning behind the design does not — that
goes in `docs/<family>.md`, along with history, measurements, rejected
approaches and comparisons to other versions.

Two tells that a comment has become a story: it runs past 3 lines, or it
contains a blank `//` separator. Both mean move it to the docs. Diff a new
iteration against its predecessor and read what you added before committing —
this is the single most-repeated correction in this repo.

## GLSL traps that actually bit

- **`pow(0.0, k)` is undefined** and returned NaN on a real driver — whole
  scanline rows black. Clamp the base: `pow(max(x, 1e-8), g)`. Use `1e-8`, not
  `1e-5`, which lifts pure black to 1/255 at γ=0.5.
- **Never branch on an exact comparison of a division result.** GPUs evaluate
  `a/b` as `a*rcp(b)`, so `720.0/240.0` can land ULPs off 3.0 while numpy gets
  exactly 3.0. Use a narrow biased `smoothstep`.
- **`floor()` for row parity** has its argument cross whole numbers once per
  line; a few ULP flip a whole row. `floor(x + 1e-3)`. Under a warp no epsilon
  helps — the argument must cross an integer somewhere.
- **`sqrt()` of an analytically-non-negative value** can still see a small
  negative. `max(..., 0.0)`.
- **A uniform the host never sets is 0** — and 0 is a legal-looking value for
  most of these, so it renders something else rather than failing.
- **`mix(x, y, w)` returns `y` at `w == 1`.** If `w` means "weight on the low
  side", the low value must be the *second* argument.
- **Reserved words that are not obvious**: `flat`, `smooth`, `sample`, `cast`,
  `input`, `output`, `filter`. `check.py` catches these; a desktop-only compile
  may not.
- **Making a uniform-derived expression per-fragment is expensive.** The driver
  hoists `sin`/`smoothstep` out of the fragment shader while their argument is
  uniform-only. Multiplying that argument by anything varying cost 16.5% of
  frame time, paid whether the feature was on or off.

## Measurement traps

Every one of these produced a confident, wrong number. Details in
`docs/measurement.md`.

- **A band that does not exclude the effect under test measures the effect.** A
  fixed "periods 6–64px are moiré" window scores the shader's own pattern once
  its pitch enters the window. Derive the band from the source and output sizes.
- **A sampled reference is itself a measurement.** Point-sampled ground truth
  quantises to `1/n`; on a checkerboard that read 16.2 at 2×2 falling to 0.9 at
  32×32 — halving per doubling, which is the signature of reference noise, not
  shader error. Extrapolate it away and show the convergence.
- **A metric that assumes an axis-aligned pattern is invalid on a warped image.**
  A row-mean profile reported a healthy corner collapsing 10×.
- **Aliasing relocates pattern energy, it does not remove it.** A strength or
  uniformity metric reads an aliased pattern as perfectly healthy — the naive
  implementation measured *more* uniform than the correct one. Check the
  geometry.
- **GPU timing needs interleaving and a discarded run-in.** Measuring each case
  to completion in turn let clock drift land on whichever ran first; the opening
  passes are erratic regardless of content. Report the IQR, not min-to-max.

## Deployment (NextUI / minarch)

- The host caches compiled programs at `SDCARD_PATH/.shadercache/<filename>.bin`,
  keyed on **filename only, no content hash**. Delete it on every copy.
- A preset resolves its shader by filename and **returns index 0 on no match**
  rather than erroring, so a preset naming a missing shader silently loads
  whichever sorts first.

## Never revert an unexplained change — ask

**The project owner tweaks values directly in the working tree.** A constant
that disagrees with a model or looks like a typo is deliberate until told
otherwise. `SHADOW_OFFSET` was hand-tuned to 0.50 and "corrected" back to 0.60
in three shaders at once while chasing an unrelated bug.

- Do not revert it and do not fix it to match something else. Ask.
- When a shader disagrees with anything written down about it, **the shader is
  the thing that was looked at and judged** — change what is written down.
- `git diff` before touching anything anomalous. A working tree that differs
  from HEAD is somebody's work, possibly another agent's mid-edit.
- **Answer the question that was asked.** A question about the code is not
  permission to change it. If the answer suggests a fix, say so and stop.

## Commits

Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `perf:`,
`test:`.
