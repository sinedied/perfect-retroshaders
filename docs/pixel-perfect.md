# pixel-perfect

Design record. Why this shader is built the way it is, what was
measured, and what was tried and rejected. AGENTS.md carries only what an agent
needs before touching anything; this is the detail behind it.

> **Tool names in this record are historical.** These notes were written against
> a harness of nine separate scripts, since consolidated into five entry points.
> The measurements are unchanged; only where they live moved. See the table in
> `docs/measurement.md`.


## An affine grade is free after the blend; only the clamp and the gamma cost

`pixel-perfect-v3` drops `pp_sharpness` and spends the space on a colour grade. Both
halves of that took measuring.

**`pp_sharpness` only ever undoes the shader.** It scales the half-footprint, so below
1.00 the footprint stops covering the output pixel and the area average degrades toward
nearest-neighbour — which is the uneven, crawling blocks the shader exists to remove.
`equivalence.py` shows it directly: transition pixels per row at 320x240 → 1024x768 go
256, 256, 128, 128, 0 as it drops 1.00 → 0.20. A knob whose entire range is a slide back
into the fault is not a tuning control, so v3 pins it at 1.00 and removes it.

**Brightness, contrast and saturation may sit after the blend, and this is not an
exception to the design rule — it is the rule's converse.** What the rule forbids is a
*non-linearity* after the blend, because that gives partial-coverage pixels a
coverage-dependent shift. An affine map has no such shift: the scaler's weights sum to
1, so

    A·(Σ wᵢ xᵢ) + B  ==  Σ wᵢ (A·xᵢ + B)

and post-blend is *identical* to per-tap, at a quarter of the cost. Gain is affine,
contrast about mid grey is affine, and saturation is a linear operator (`mix` toward a
luma dot product). Measured on 1px checkerboards, worst over five scales, with the share
of the frame that meets the clamp alongside:

| | mono | chroma | clips |
|---|---|---|---|
| neutral (the defaults) | 0.349 | 0.116 | 0.0% |
| `pp_saturation` 0.00 | 0.349 | 0.244 | 0.0% |
| `pp_contrast` 0.40 | 0.178 | 0.134 | 0.0% |
| `pp_brightness` 0.60 | 0.209 | 0.070 | 0.0% |
| `pp_saturation` 1.80 | 0.349 | 1.042 | 100% |
| `pp_contrast` 1.60 | 3.916 | 1.305 | 100% |
| `pp_brightness` 2.00 | 32.67 | 32.67 | 50% |
| `pp_gamma` 0.70 | 8.031 | 8.009 | 0.0% |
| `pp_gamma` 1.40 | 8.705 | 8.681 | 0.0% |

**Beat tracks the clip column and nothing else.** Every 0% row sits at or *below* the
neutral floor however far from 1 the control is pushed — which is the falsifiable form
of the claim, and the reason `report_grade()` prints the clip share next to the beat
rather than the beat alone. The 0.349 floor is the scaler's own at its worst scale
(480x272 → 640x480); at 320x240 → 1024x768 it is 0.031, the figure recorded for
`pixel-perfect` elsewhere in this file.

Two traps in measuring it:

- **A black-and-white checkerboard cannot exercise a saturation control.** On grey,
  luma equals every channel and the mix is a no-op, so a completely broken saturation
  measures perfect. The chroma row is a red/cyan 1px checker — the same worst case one
  axis over — and it is the only column in which the saturation rows say anything.
- **`pp_gamma` is not a v3 regression.** Its figures are *bit-identical* to
  `pixel-perfect-v2`'s at every scale, because it is the same post-blend placement.
  What is new is measuring it on the same yardstick as everything else, where it turns
  out to be far the most expensive control in the shader — around 20× the visible
  threshold on dense content, against 0.03 with it off. The cheap placement was kept
  deliberately (one `pow`, 6 SFU, against 24 for the four taps); putting it on the taps
  the way `crt-perfect-v5` does would fit the budget and is the obvious next iteration
  if the cost is judged too high.

**Fold the three affine controls into one map; do not write them as three steps.**
The composition is `col*(ga*s) + dot(col, LUMA)*(ga*(1-s)) + gb`, where `ga =
brightness*contrast` and `gb = 0.5*(1-contrast)`, using the fact that the luma weights
sum to 1. It is one dot and one fma — but the reason it matters is exactness, not cost:
at the defaults it is `col*1.0 + 0.0`, which is bit-exact, where the literal chain is
not. `(x - 0.5)` rounds for small x so the contrast round trip does not return x, and
`mix(l, col, 1.0)` is only exactly `col` if the driver spells `mix` as `x*(1-a) + y*a`
rather than as `x + a*(y-x)`. GLSL guarantees the former; drivers ship the latter.

That exactness is worth having because it makes "off" checkable: **v3 at its defaults is
bit-identical (0/255) to `pixel-perfect.glsl` at every scale in `equivalence.py`'s
matrix**, on noise, checkerboard, grid and ramp sources. A grade that claims to be
neutral at unity should be provably neutral, not nearly.

Note the declaration order (`pp_saturation`, `pp_contrast`, `pp_brightness`, `pp_gamma`,
per the "brightness then gamma last" rule) deliberately differs from the evaluation
order (brightness → contrast → saturation → gamma). The fold makes the evaluation order
invisible in the code, so it is stated in the comment there.

### Making it free when it is off, and what that cost to measure

`pixel-perfect-v4` is v3 with the affine block and its clamp behind one uniform guard,
the way `pp_gamma` already was. Measured by removing each block and recompiling: the
affine block is **32 instructions**, the gamma block 16 plus 6 SFU lanes.

**Compare the three controls separately and exactly.** Two forms were rejected:

- `abs(b + k + s - 3.0) > eps` is **wrong**, not merely worse — brightness 1.1 with
  contrast 0.9 sums to exactly 3.0, so a real grade is dropped without a trace.
- summing the absolute deviations is correct but costs 17 instructions against 13 for
  three exact comparisons, *and* it opens a dead band in which v4 and v3 disagree.

**An epsilon here would have been cargo-culted from the gamma guard.** That one needs a
dead band for an accuracy reason: `pow(x, 1.0)` is `exp2(log2(x))` on a GPU and rounds,
so a gamma of 1.0 is not otherwise a no-op. The affine block at 1.00 is `col*1.0 + 0.0`,
which is exact — nothing to protect against, so exact comparison is both cheaper and
strictly equivalent. Check which of those two situations applies before copying a guard.

### `spirv_cost.py` counts both arms of a branch, so it reported v4 as a regression

The static count walks every instruction regardless of control flow. v4 reads **174**
against v3's 161 while executing far less, which is exactly backwards, and quoting it
would have buried the change. The tool now also compiles each shader through
`spirv-opt` twice — once with the parameters live, once with `PARAMETER_UNIFORM`
undefined so each resolves to its `#define` fallback and the guards fold away:

| | ops | live | at defaults | SFU at defaults |
|---|---|---|---|---|
| `pixel-perfect.glsl` | 112 | 106 | 104 | 0 |
| `pixel-perfect-v2.glsl` | 131 | 124 | 109 | 0 |
| `pixel-perfect-v3.glsl` | 161 | 152 | 123 | 0 |
| **`pixel-perfect-v4.glsl`** | 174 | 165 | **111** | 0 |
| `crt-perfect.glsl` | 501 | 459 | 403 | **8**, from 14 |
| `lcd-perfect.glsl` | 434 | 397 | 343 | **15**, from 39 |
| `dmg-perfect-v3.glsl` | 459 | 445 | **265** | 0 |
| `pixellate.glsl` | 292 | 254 | 240 | 30 |

**The `at defaults` column understates an explicit guard, and that is the trap in it.**
With the parameters as literals the optimiser also folds arithmetic that is merely
neutral — v3's `col*1.0 + 0.0` collapses although v3 has no guard at all — and no
runtime can do that with live uniforms. So it is a *lower* bound on what a guard buys:
v4 reads 12 ops better than v3 there, where the runtime gap is nearer 19. Safe direction
to be wrong in, but do not quote it as the saving.

The unoptimised `ops` column is deliberately left alone: every cost figure recorded in
this file is in those units, and re-basing them would invalidate the lot.

### A branch after the blend perturbs the blend, and it is not a bug

v4 is **1/255 from v3 on 0.02% of pixels**, not bit-identical, and the reason is worth
knowing because any future guard added after the scaler will do the same.

The cause is not the grade. `equivalence.py` compiles a control: the same shader with
its condition replaced by `OutputSize.x < 0.0`, which can never be true and which the
driver cannot fold away. That control **reproduces v4's divergence exactly**, and every
differing pixel is a transition pixel — one whose blend weights are strictly between 0
and 1, which is the only place the blend does arithmetic at all. Putting any branch
after the blend changes which floating-point contractions the driver picks for the
blend itself.

So v3 and v4 are the same computation rounded two ways, and `gl_check` scores both at
1/255 against the float64 model — neither is the more correct one. The gate is
`<= 1` **plus** the control agreeing and the divergence staying on transition pixels;
a bare tolerance of 1 would have hidden a real logic error of the same size.

**Three claims, three different bars, and they are not interchangeable:**

| | bar | why |
|---|---|---|
| `pixel-perfect` vs `pixellate` | 1/255 | a different formulation of the same maths |
| v3 at defaults vs `pixel-perfect` | **0/255** | the same code path; the grade folds exactly |
| v4 vs v3 | 1/255 + control | same computation, different contraction |

The middle one was asserted at `== 0` for `pixellate` too when the gate was first
written, which is simply not true of it, and `equivalence.py` shipped exiting 1 for a
commit before anyone noticed — because the exit code was being read through a pipe, so
`$?` was `tail`'s status and not the tool's. **Read `PIPESTATUS`, or do not pipe.**

### `#define` fallbacks can disagree with `#pragma` defaults

The `at defaults` column trusts each parameter's `#define` fallback, so `check_headers.py`
now verifies it matches that parameter's `#pragma` default. Three shaders failed when
the check was added, and the first was shipped:

| shader | parameter | `#pragma` | stale `#define` |
|---|---|---|---|
| `lcd-perfect.glsl` — **fixed** | `lp_grid` | 0.30 | 0.34 |
| `lcd-perfect.glsl` — **fixed** | `lp_balance` | 0.50 | 0.79 |
| `lcd-perfect.glsl` — **fixed** | `lp_brightness` | 1.20 | 1.00 |
| `crt-perfect-v8/v9.glsl` | `cp_scanlines` | 0.60 | 0.55 |
| `crt-perfect-v8/v9.glsl` | `cp_rgb_mask` | 0.20 | 0.40 |

`lcd-perfect`'s were the **pre-retune values**, left behind when the defaults were tuned
in the `#pragma` block and nowhere else — 0.79 is exactly the balance that matched
lcd1x's white-field figures before the render showed 0.50 read better. A host that does
not parse `#pragma parameter` renders the `#define` values, so the shader shipped one
look and documented another, and that class of host is already on the record elsewhere
in this file.

**A default lives in three places here and nothing used to tie them together**: the
`#pragma` line, the `#define` fallback, and the model's `DEFAULTS_*` dict. The model
had been retuned along with the `#pragma`, which is why `gl_check` stayed green
throughout — it passes the registry's defaults explicitly and compiles with
`PARAMETER_UNIFORM` defined, so it never reads the fallback at all. **No existing gate
could see this.** That is the argument for the check, not the two levels of grid it cost.

It is a **warning, not a failure**, because two shaders still fail and both are
in-flight. Fix `crt-perfect-v8/v9`, then move it into `check()` — a warning nobody
promotes is a warning that rots.

### A diagonal trim does not want to be folded into the affine map

`pixel-perfect-v5` adds `pp_red`, `pp_green` and `pp_blue`, matching
`dmg-perfect-v7`'s names and ranges. They are plain gains, and a diagonal gain is
affine, so they inherit the whole argument above: they commute with the blend, they
paint no pattern, and what they cost is clipping. Measured, worst over five scales:

| | mono | chroma | clips |
|---|---|---|---|
| neutral | 0.349 | 0.116 | 0.0% |
| warm — blue 0.85, green 0.95 | 0.346 | 0.135 | 0.0% |
| cool — red 0.85, green 0.95 | 0.346 | 0.145 | 0.0% |
| `pp_red` 0.00 | 0.233 | 0.233 | 0.0% |
| `pp_red` 1.40 | 5.326 | 5.277 | 16.7% |

Pulling channels down — which is how you actually warm or cool a picture — sits *at or
below* the neutral floor. Only pushing a channel above 1 costs anything, and it costs
it through the clamp, exactly like `pp_brightness`.

**The trim can be folded into the grade's coefficients, and it should not be.** A
diagonal matrix composes with an affine map, so `t·(col·(ga·s) + luma·(ga·(1-s)) + gb)`
collapses to the same one dot and one fma with `t·ga·s`, `t·ga·(1-s)` and `t·gb` as
coefficients — all uniform-derived, so they hoist. That looks free and is not:

| | live | with the coefficients constant-folded |
|---|---|---|
| folded into the coefficients | 185 | 141 |
| **separate `col *= vec3(...)`** | **181** | **137** |

**Folding is 4 instructions worse, both ways round.** Making the coefficients `vec3`
widens the luma term from scalar to vector, and that costs precisely what the separate
multiply would have. The second column constant-folds the parameters, which models a
driver hoisting uniform expressions perfectly — so hoisting cannot rescue it either.
Desktop timings cannot separate the two at all (101.2% against 100.1%, IQR up to 1.5%),
which is the expected answer for a shader whose four texture taps dominate; the
instruction count is what decides, and it decides against the clever form.

There is still one ordering constraint: **the trim has to come after the saturation
mix.** `dot(col·t, LUMA)` is not `t·dot(col, LUMA)`, so a trim applied earlier could not
share the dot. Last is also what it should mean — a channel trim is a property of the
panel, so it belongs on the finished picture, which is where `dmg-perfect` puts it too.

At its defaults v5 is **111 ops, identical to v4**, because the trim joins v4's existing
uniform guard rather than adding one. With the trim neutral it is **0/255 from v4** at
every other setting — `col *= 1.0` is exact — so it is a strict superset rather than a
new look. Its 1/255 against the bare scaler is v4's branch-contraction effect, and
`equivalence.py` checks it lands on *the same pixels* as v4's rather than merely the
same count.

### Three channel gains are two controls wearing a third

`pixel-perfect-v6` replaces v5's `pp_red/green/blue` with `pp_temperature` and
`pp_tint`. That is not a simplification that gives something up: three gains carry
3 DOF, but one of them **is** overall level, which `pp_brightness` already provides.
The genuinely chromatic content is 2 DOF — the two axes every camera exposes.

```glsl
col *= 1.0 + pp_temperature * vec3(1.0, 0.0, -1.0)
           + pp_tint        * vec3(-0.5, 1.0, -0.5);
```

Solving `rgb = brightness · (1 + temp·warm + tint·tint)` reproduces every v5 setting
exactly — warm (0.85/0.95) is brightness 0.933, temp +0.080, tint +0.018; even "red
killed" is reachable at temp −0.75, tint +0.50, brightness 0.667. `equivalence.py`
gates the round trip on the GPU: **0/255 against v5** both with the balance neutral
and at five settings where the two axes hit an exact `r/g/b` triple. It is a
reparameterisation, not an approximation.

Cost is unchanged — same single multiply, 190 static and **111 at defaults, equal to
v4 and v5** — and the guard is one comparison shorter.

**Not normalised on luma, by decision.** Dividing by `dot(wb, LUMA)` would make
temperature purely chromatic (white luma stays 1.0000 instead of drifting to 1.0281 at
temp 0.20), but it costs a divide and pushes the up-channel to 1.167, so it clips where
the raw form merely dims. The owner's call: this is a retro shader, not a photo editor,
and `pp_brightness` takes the level back out.

**Reading the beat table for these needs care.** Every balance row clips on a 1px
checkerboard — 16.7% at temperature 0.10 — and that is the *source*, not the axis: a
full-range checkerboard reaches white, so raising any channel leaves the range at once.
Trimming the level so the peak lands on 1 (`pp_temperature` 0.10 with `pp_brightness`
1/1.1) reads **0.320 / 0.097 at 0% clip, below the neutral floor of 0.349 / 0.116**.
The axis is affine and clean; all the beat is the clamp. This is the same test-source
trap recorded for `dmg_checkerboard`, hit again by a different control.

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
| `pixel-perfect-v2.glsl` | 131 | 4 | 6 |
| `pixel-perfect-v3.glsl` | 161 | 4 | 6 |
| `pixel-perfect-v4.glsl` | 174 | 4 | 6 |
| `pixel-perfect-v5.glsl` | 190 | 4 | 6 |
| `pixel-perfect-v6.glsl` | 190 | 4 | 6 |

Four taps stay: an output footprint spans up to two texels per axis, so four is the
minimum without delegating the blend to the texture unit. A one-tap LINEAR variant was
prototyped and is exactly equivalent (1/255, identical block widths and shimmer), but
was rejected — it makes correctness depend on the GPU's subtexel bilinear precision and
needs the opposite sampler setting to everything else here.

`tools/equivalence.py` proves the match: output diff, block-width distribution,
transition-pixel counts, moire, the `pp_sharpness` response, and v3's bit-identity
against the canonical shader at its defaults.

### The one-tap scaler is not hypothetical — it ships, and it is vendored

`sharp-shimmerless.glsl` (zadpos, public domain) **is** that rejected variant, shipped
by someone else and running on NextUI, spruceOS, MustardOS and CrossMix today. It is
now in `tools/vendor/`, so the trade is measured rather than remembered. It computes
the same box footprint, then instead of weighting four NEAREST taps it solves for the
one texcoord whose bilinear fetch already **is** that weighted sum.

| | ops | tex | SFU | sampler | vs `pixellate` |
|---|---|---|---|---|---|
| `pixellate` | 292 | 4 | 30 | NEAREST | 100.0% |
| **`sharp-shimmerless`** | **50** | **1** | **0** | **LINEAR** | **65.9%** |
| `sharp-shimmerless-grid` | 161 | 1 | 0 | LINEAR | 83.0% |
| `pixel-perfect` | 112 | 4 | 0 | NEAREST | 74.8% |

1024x768 from 320x240, worst per-case IQR 0.5%. It is the cheapest thing in the repo
on every axis at once, and **the output is the same picture**: 1/255 against both
`pixellate` (g=0) and `pixel-perfect` over twelve scales and four sources, byte-equal
block-width histograms (`{2: 95, 3: 63, 4: 159}` at 3.2x), the same 256 transition
pixels per row, and the same beat.

So the rejection stands on two things, and neither is speed:

- **It leans on the texture unit's subtexel precision, which is a fixed-point ladder
  with no GL query.** `equivalence.py:subtexel_bits()` measures it directly — sweep one
  texel spacing of a two-texel LINEAR texture holding 0 and 1, into a **float32**
  target, and count distinct values. This Apple GPU: **257 = exactly 8 bits**, which an
  8-bit output cannot distinguish from exact. A coarser interpolator bands every soft
  transition pixel and nothing here would see it; only the Mali settles it. Render the
  probe to 8-bit and it reports every GPU as perfect, which is why it does not.
- **It fails silently under the wrong sampler.** A four-tap shader under LINEAR is
  merely filtered twice; a one-tap shader under NEAREST snaps its carefully placed tap
  back to a texel centre and becomes **nearest-neighbour** — 256 transition pixels per
  row to **0**, 102/255 against the correct output, with nothing in the frame to say
  so. Beat goes 0.05 → 3.56 at 3.2x and 0.35 → 17.7 at 480x272 → 640x480.

One thing the comparison settles that the SFU/ops argument does not: **taps and
transcendentals do not decide moire, the gamma round-trip does.** One tap and four tap
measure identically; `pixellate`'s own default mode is 3.5–5.7 against their 0.000.
`sharp-shimmerless` has no knob to get that wrong because it has **no parameters at
all** — which is also why it cannot be the shader this repo ships.
