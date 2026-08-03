# lcd-perfect

Design record. Why this shader is built the way it is, what was
measured, and what was tried and rejected. AGENTS.md carries only what an agent
needs before touching anything; this is the detail behind it.

> **Tool names in this record are historical.** These notes were written against
> a harness of nine separate scripts, since consolidated into five entry points.
> The measurements are unchanged; only where they live moved. See the table in
> `docs/measurement.md`.


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

### Aperture shape decides how strong a grid you can afford

Matching `lcd1x`'s look means a **column-dominant** grid at a 4:1 column-to-row swing
ratio. Measured, at 320x240 -> 1024x768 on white:

| | mean | row | col | col/row | beat |
|---|---|---|---|---|---|
| `lcd1x`, the target | 75.3% | 24.0 | 96.0 | 4.00 | 1.865 |
| `lcd-perfect` v1 | 85.0% | 57.6 | 25.4 | 0.44 | 0.244 |
| v2b, hard matrix + balance | 80.7% | 15.2 | 71.0 | 4.65 | 0.385 |
| v2a, sinusoid + balance | 72.6% | 24.4 | 96.2 | 3.94 | **0.144** |

**The sinusoid reaches it and the hard matrix cannot.** Every v2b configuration at a
4:1 ratio with a column swing near 96 measures past 0.4; its best inside the budget is
71, a quarter short. A hard-edged aperture is mostly harmonics, they fold back, and
the stronger you make it the worse that gets — which is the same thing v1's ramp was
compensating for, arriving structurally instead of empirically. **Want a strong grid,
use a smooth profile.**

The sinusoid is also *cheaper*, 515 ops against 646, because it needs no `floor`, no
`clamp` and no ramp integral. It costs 6 more SFU lanes, which is a good trade.

Two things it does not get for free:

- **Even-integer scales lose all contrast.** The edge-aligned trapezoid fixed those by
  construction; a sinusoid puts both samples of a cell on symmetric points of the
  cosine and reads the same value from each, so at 2.0 output pixels per cell the grid
  vanishes. An **unconditional** half-output-pixel shift removes every dropout over a
  dense 2.0-8.0 sweep and is never worse than not shifting (min contrast 0 -> 60,
  median unchanged). Do not ramp it in; there is nothing to trade.
- **But the shift is worth more than it costs.** At 320x240 -> 640x480, exactly 2.0
  output pixels per cell, v2a keeps a column swing of 71.5 against its own 96.2 at
  1024x768 - 74% retained. `lcd1x`, an unshifted sinusoid, keeps 19.1 of 96.0, so 20%.
  The minimum supported resolution is where this decision is worth the most.
- **The blend identity needs re-checking, not assuming.** The aperture-weighted blend
  is free only because `A(n) == n` at integers. For `A(x) = x - m*sin(TAU*x)/TAU` it
  holds exactly, and once phase-shifted `A(n) - n` is a constant across the draw, so
  it stays free. Verified numerically to 6e-14 before any shader was written.

### Do not hardcode a geometry ratio

v1 hardcoded `GAP_ASPECT = 0.4` from the Game Boy Color panel measurement, which is
physically right - real panels are row-dominant. It also made the `lcd1x` look
*unreachable*: the constant caps the column gap at 40% of the row gap, so the ratio
tops out at 0.61 no matter how far `lp_gap` is pushed. Authenticity and the look
people actually want are different targets; the ratio is a parameter (`lp_balance`),
not a constant.

Same shape of mistake in the stripe fade: `smoothstep(3, 6, px_per_cell)` leaves the
stripes at 1.3% strength at 3.2 px/cell, which is 320x240 into 1024x768 - the most
common scale there is. A threshold chosen against one failure mode was silently
disabling the feature everywhere else. Measure a fade window across the scales that
actually occur.

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

## LCD meshes: what v3 had to fix

- **A sinusoid does not band-limit itself.** The trapezoid aperture v1 used did -
  its coverage flattens on its own as cells shrink - so v2a dropped the Nyquist
  fade and the minimum pitch along with the trapezoid and nobody re-checked. A
  480x272 source then folded: 1.33 output pixels per cell at 640x480, below the
  two per cycle a pattern needs, measuring 5.9 against a threshold of 0.4. When
  the shape of a pattern changes, re-derive what band-limits it.
- **Grow the period, do not pin it.** crt-perfect pins its pattern to a fixed
  output-space pitch below `cp_min_pitch`. Copying that into a mesh made things
  worse, not better: a pattern that has stopped tracking the source interferes
  with the pixel blocks in *both* axes, and a 3px mesh over 2px blocks measured a
  real 12px beat. crt-perfect gets away with it because its horizontal pattern is
  a colour mask carrying no luminance, so its luminance pattern is
  one-dimensional and has nothing to interfere with in the other axis. Growing
  the period to a whole number of *cells* keeps the pattern exactly periodic on
  the source grid, so it cannot beat against it at all, and it kept the
  aperture-weighted blend working unchanged.
- **A column mesh and a stripe mask at the same pitch make a colour cast.**
  Whichever stripe lands on the mesh's dark line is dimmed, and swapping the
  stripe order swaps which one, so RGB and BGR cast in opposite directions -
  measured at 3.5 to 4.2 levels with a 3.5 to 5.3 flip between the two. It is
  divisible out in closed form, and two things have to be right or it overshoots
  to the opposite sign: the phase **cancels** between mesh and stripe and must
  not be subtracted a second time, and the correction must be **square-rooted**,
  because the `sqrt` that encodes the output halves any relative deviation on the
  way there. Applying it whole took green from 3 levels bright to 3.4 dark.
  crt-perfect never had this because a CRT mask has no column mesh to correlate
  with.
- **Aggregate swing figures and the look can disagree.** `lp_balance` 0.79 matches
  lcd1x on every white-field figure - column swing 90.2 against 90.0, ratio 4.00
  against 3.89 - while about 0.65 looks closer to its weave on a real frame,
  because lcd1x point-samples and its horizontal lines are sharper than a
  box-filtered one of the same measured swing. Render the frame before calling a
  look matched.

## v4: one angle instead of four

v4 is v3's picture computed differently. Not a retune - no parameter, default or
range changed, and the `#pragma` block is byte-identical. The gate is equality
with v3 within 1/255 across all ten cases and a thirteen-setting sweep, with v1
and v2a kept as negative controls (they fail it at 146/255 and 95/255).

**434 ops to 414, and 0.1512 ms to 0.1338 ms - 11.5% off frame time.**

v3 spent eight per-fragment transcendentals building things that are all the
same angle. With `X = TAU*(t - phase)` and `Y = TAU*hh`, where **`Y` is
uniform-derived**, three identities collapse them onto one `sin(X)`/`cos(X)`
pair:

- `sin(X+Y) - sin(X-Y) = 2*cos(X)*sin(Y)`, so the aperture integral's difference
  needs one angle, not two evaluations. One whole `apertureIntegral` call goes.
- Substituting `k*cos(X)*sin(Y) = hh - I/2` back into the lower bound gives
  `Alo = t - 0.5*Iraw - (k*cosY)*sinX`, reusing what the integral already
  produced. This must use the **unclamped** `Iraw`: v3 computed `Alo`
  independently, so feeding it the clamped `I` would make the two disagree
  exactly where `max(..., 1e-6)` bites.
- The stripe angles are `X.x` offset by compile-time constants, so
  `cos(X.x - K) = cos(X.x)*cos(K) + sin(X.x)*sin(K)` turns both stripe cosines
  into multiply-adds. `K1 = TAU/2` makes green simply `-cos(X.x)`.

Also folded: the `corr` cosines are exact literals `vec3(0.5, -1.0, 0.5)`,
`nyquistFade(f)` was being evaluated twice, `g`'s uniform divisor became a
reciprocal-multiply, and `vec2 h = 0.4995 * d;` was dead code.

All three identities were checked in float64 over 100k samples before any GLSL
was written - max error 1e-13.

### SFU went 39 to 41, and that number is wrong

`perf.py --static` counts every SFU lane in the disassembly, including the ones
the driver hoists out of the fragment shader. The split matters more than the
total:

| | varying SFU | uniform SFU | reported |
|---|---|---|---|
| v3 | 8 | 1 | 39 |
| v4 | **6** | 5 | 41 |

Per-fragment cost fell by a quarter while the reported figure rose. **This was
proven, not assumed**: a probe multiplying `Y` by `step(-1.0, p.x)` - exactly
1.0, but not constant-foldable - keeps the same 41 SFU and adds only 7 ops, yet
runs **9.7% slower** (0.1472 against 0.1342). That is the hoist, measured.

The useful part for a device nobody here can test: even that forced worst case,
where nothing hoists at all, still beats v3 (0.1472 against 0.1506). v4 is ahead
whether or not a Mali G31 hoists uniform trig.

`sinY`/`cosY` cannot be removed - `I` needs one and `Alo` the other. Recovering
`cos(X)` from the sines as `diff/(2*sin(Y))` blows up as `f -> 0`, which is the
extreme-upscale case this shader exists for. `cosY = sqrt(1 - sinY*sinY)` trades
one SFU class for another and needs a sign fix past `f > 0.5`. Hoisting them to
a vertex output is blocked because `flat` is a reserved word in ESSL 1.00.

### Rejected: the N == 1 fast path

At `N == 1`, `Bt` is an integer, so the blend weight's `sin(TAU*(Bt - phase))`
folds to the constant `-sin(TAU*phase)` and the last varying `sin` disappears.
Branching on `N.x + N.y < 2.5` is safe - `N` comes from `ceil()`, so the values
are exact small integers and the threshold sits between 2 and 3, which is not an
exact comparison of a division result.

It works: within 1/255, and **7% faster again** (0.1246 ms, 17.5% under v3). The
precision hazard that was expected did not appear - `sin` at B around 320, near
2010 radians where float32 argument reduction is lossy, still agreed within
1/255.

It was dropped anyway, because both branches stay in the binary: static ops go
to 435 and SFU to 43. The rule for this rewrite was "only changes that cut both
signals", and a branch that a weaker driver might scalarise is exactly the kind
of guess that rule exists to refuse. Recorded here because the measurement stands
and the decision could reasonably go the other way on evidence from the device.

## The scrolling colour band, and why v7 was not it

Reported from a device: scrolling horizontally in GBC and GBA, aspect-scaled to
1024x768, paints a large colour moiré that is invisible in a still frame and
walks with the movement. lcd1x and lcd3x do not do it.

Measured, at `lp_subpixels` maximum, as low-frequency chroma that a compensated
scroll changes — `crawl()` in `measure.py`, which is new, because nothing here
could see this: every other metric in that file takes one frame and converts it
to luminance, and this artifact is neither.

| | chroma crawl |
|---|---|
| plain scaler (the floor) | 0.00 |
| `lp_grid` at maximum, stripes off | 0.54 |
| `lp_subpixels` at maximum, mesh off | **3.68** |
| both at maximum | **5.31** |

The stripes, not the mesh. The mesh is aperture-weighted into the blend; the
stripes are multiplied on after it. So the shader computes
`average(content) x average(stripe)` where it wants `average(content x stripe)`,
and the covariance it drops depends on where the cell boundary falls inside an
output pixel. That phase repeats once per denominator of the scale — 15 cells at
1024/240, 160 at 853/160 — so the error is a very slow band rather than noise.
Held still it reads as texture. Scroll, and each cell holds different content, so
the band changes and walks.

**It is a bug, not a limit of the design.** The same shader rendered at 4x and
averaged down — which is what the 1x path is approximating — reads **0.319**,
against 1.606 as shipped. Five times better is available.

### v7: right shape, wrong price

v7 pulls the stripes inside the blend: it integrates `mesh x stripe` per channel
across the column and uses the result as both the blend weight and the gain, so
one formula replaces the point-sampled stripe and its `boxSinc` amplitude
correction. The mesh is a trough (`1 - amp*cos`), so it enters the product with a
negative amplitude; getting that sign wrong puts the colour cast correction on
the wrong side of white. The second harmonic the product carries comes free from
double-angle, and the only new transcendental is the boundary cosine.

It works, and it is not worth it:

| | chroma | luma | ops | SFU |
|---|---|---|---|---|
| v6 | 1.606 | 0.276 | 396 | 23 |
| v7 | 1.504 | 0.000 | 556 | 20 |

Luma is fixed outright. Chroma moves 6%, for **+40% ops**. The device says time
tracks ops and not SFU, and lcd-perfect already uses 90% of a 60fps frame there,
so v7 is unaffordable for what it buys. Kept as an archive rather than deleted,
because the approach is sound and the measurement is the point.

### What is actually left

Two candidates were tested and eliminated first, which is why they are written
down rather than tried again:

- **The `sqrt` encode.** Applying the stripe linearly on the encoded value
  instead made it worse: 1.828 against 1.623.
- **Clipping.** At maximum visibility the stripe peaks near 2x, so bright content
  clamps and the clamping is phase-dependent. Real, and partial: dimming the
  content from 240 to 100 takes v6 from 1.519 to 0.570, so roughly a third of the
  figure at maximum is clipping and the rest is not.

What v7 removed is the error in linear space. What remains is in the encoded
domain: the ideal averages `sqrt(pattern)` over the footprint while the shader
takes `sqrt` of the average, and those differ by a term in the variance of the
pattern across the pixel. That has a closed form to second order —
`avg(sqrt(P)) ~ sqrt(Pbar)(1 - var(P)/(8 Pbar^2))` — and the variance of a
product of two sinusoids at one pitch is reachable from the same sin/cos pairs
by multiple-angle, so it need not cost another transcendental. Untried.

Until then the figures are recorded as `crawl_allow` in `baseline.toml`: not
approval, a ceiling, so the number cannot get worse while the fix is worked out.

## v8: the clamp was the artifact, not the covariance

The section above is wrong about which term the owner was seeing, and it is left
standing because the reasoning is sound and the measurement stands — it just was
not the dominant thing. Device testing settled it:

| observed on a Brick | measured here |
|---|---|
| absent at `lp_brightness` 1.0 | crawl 0.128 |
| worse with every step above it | 1.4 → 0.312, 1.7 → 0.483, 2.0 → 0.702 |
| **absent at an integer scale at any brightness** | **0.006–0.008, flat** |
| X grid beats vertical scrolling, Y grid horizontal | the modulated axis is the one that beats |
| `pixellate → lcd1x → image-adjustment` does it too | it is not this shader; it is boost-then-clamp |

The integer-scale result is decisive, and it is the design rule in `AGENTS.md`
naming its own cause. At a non-integer scale the count of partial-coverage
pixels varies block to block, so **any non-linearity after the blend** shifts
them by an amount that depends on their coverage. At an integer scale every
output pixel has full coverage and there is nothing to beat against — which is
why brightness can be pushed as far as you like there.

**The non-linearity is `clamp()`.** `lp_brightness` multiplied the blended colour
*and* the pattern, and the product was clipped at the end.

### The fix

Brightness moves to the four taps and is clamped there:

```glsl
float sb = pow(max(lp_brightness, 1e-4), 0.5 / max(lp_gamma, 1e-3));
vec3 a = min(COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb * sb, 1.0);
```

A clamp per tap is a clamp per *source pixel*: identical for every output pixel
covering it, so it cannot vary with coverage and cannot beat. The blend of four
clamped taps is a linear interpolation, and a linear operation after the blend is
safe. The exponent carries brightness through both the encoding and the gamma, so
the look is unchanged wherever nothing clips; its argument is uniform-only, so
the driver hoists it out of the fragment shader.

The peak-normalised stripe is the other half of the same invariant — **nothing
may exceed 1 by the time the blend is done**, which needs the content ≤ 1 *and*
the pattern ≤ 1. The stripe was `1 + ac·cos`, peaking near 2, and was the only
pattern in either shader not already peak-normalised.

Measured, GBA aspect, on bright content:

| | v6 | v8 |
|---|---|---|
| stripes off, brightness 2.0 — the clamp alone | 0.302 | **0.000** |
| owner's settings, brightness 1.7 | 0.483 | **0.048** |
| shipped stripe 0.20, brightness 2.0 | 0.541 | **0.023** |
| stripe at maximum 1.0, brightness 2.0 | 2.811 | 1.540 |

The last row is the covariance term from the section above, which v8 does not
address and v7 does at +40% ops. Everywhere a user actually goes, the clamp was
the whole story.

Cost: 396 → 422 ops, +6.6%.

### What it costs in brightness, and why that is the point

Brightness can no longer be bought by clipping the product, so it buys less: the
image saturates around 170 mean where v6 reached 228. That gap is not brightness
the fix destroys, it is brightness v6 was manufacturing by clipping — which is
the rainbow. Read by artifact instead: v6 needs about 1.35 to reach 168 and pays
0.3 for it; v8 reaches 170 and pays nothing.

**The ceiling is the pattern's own light loss.** A grid removing 16% of the light
caps a clean image at 84% of source brightness. Going brighter means removing
less light — a shallower `lp_grid` or a shallower stripe — not a bigger
multiplier.

And it is not only a loss. Under v6 a bright area clips to flat white and the
grid vanishes with it; under v8 the content clips at the source and the pattern
is applied afterwards, so **the LCD structure survives in highlights** instead of
being washed out. That is visible in a still, not just in a number.

## v9: brightness back, and three answers to "why is the grid not a grid"

### The brightness half, as in crt-perfect v10

v8 clamps brightness on each tap, which is flat on every metric and is the best
formulation this repository has tried:

| form | crawl @1.25 | crawl @2.0 | moiré @1.25 | moiré @2.0 |
|---|---:|---:|---:|---:|
| v6, gain on the pattern, one end clamp | 0.222 | **0.541** | 0.432 | 3.291 |
| v8, gain per tap, clamped there | 0.065 | 0.062 | 0.158 | 0.158 |

It was still reported as the slider washing the picture out, and the mechanism
is the same one written up in `docs/crt-perfect.md`: the per-tap clamp lands on
the *content*, before the mesh and stripes, so every highlight above
`1/brightness` flattens to white and the pattern can no longer shape it.

All three v9 arms put v6's form back — `m = sqrt(stripe * (gain * lp_brightness))`
with the single clamp at the end — while **keeping v8's peak-normalised RGB
stripe**, which was the other half of that commit and is not in question.

### The grid half: it is phase, and phase cannot fix it

Reported from the device: against `lcd1x` at an integer scale the mesh looks
offset, and does not read as an exact grid. It does, and the cause is worth
recording because it is not what either of us guessed.

Flat white, integer ×4, one 4-pixel cell, as a percentage of each shader's own
peak:

| shader | px 0 | px 1 | px 2 | px 3 |
|---|---:|---:|---:|---:|
| `lcd1x` | **70** | 100 | 100 | **70** |
| v9a — the current phase | **73** | 89 | 100 | 89 |
| v9b — `lcd1x`'s phase | **80** | 100 | 100 | **80** |
| v9c — a gap aperture | **91** | 100 | 100 | **91** |

Both `lcd1x` and this family draw a sinusoid of period one source pixel. They
differ **only in phase**:

- `lcd1x` uses `angle = 2π(p − 0.25)`, putting the trough on the source-pixel
  boundary. Two samples land either side of it, so the line reads as a symmetric
  two-pixel band *between* cells — and it never reaches deeper than
  cos(45°) = 0.707 of the sinusoid.
- This family shifts the phase by **half an output pixel**, landing one sample
  exactly on the trough. Full depth, one pixel wide, and wholly inside the cell
  at its leading edge, which is what reads as offset. The shift is deliberate:
  without it every integer pitch loses contrast to sample phase, 3.0px measuring
  0.375 against a possible 0.75.

**And it is a red herring, because a sinusoid cannot draw a thin line at any
phase.** It is below its peak for three quarters of its cycle by construction.
At GBA native into 1024x768 the cycle is 4.267 output pixels, so v9a puts one
pixel at the peak and three below it, drifting cycle to cycle:

| | cycle 1 | cycle 2 | cycle 3 | cycle 4 |
|---|---|---|---|---|
| v9a | `73 88 100 94` | `75 82 99 97` | `78 77 97 99` | `84 74 92 100` |
| v9c | `91 100 100 96` | `85 100 100 100` | `81 99 100 100` | `87 94 100 100` |

v9c is the only one whose lit cells are flat.

### v9c: a black matrix instead of a mesh

The aperture becomes a duty-cycle train rather than a sinusoid:

```
A(u) = 1 - amp * rect(fract(u + w/2) < w)
```

centred on the cell boundary, with `w = lp_gap * f` — the new `lp_gap` is a
thickness in **output pixels**, converted to a share of a period, so the line is
the same width whatever the game's resolution while the pattern stays periodic
on the source grid and cannot beat.

Its box integral has a closed form, which is what keeps it band-limited:

```
F(x) = floor(x) * w + min(fract(x), w)      ∫A over [a,b] = (b-a) - amp*(F(b) - F(a))
```

`F` is **continuous at every integer** — `fract` reaches 1 exactly where `floor`
steps — so none of this repository's usual `floor()` epsilons are needed.

Three things get simpler and one gets harder:

- the peak is 1 by construction, so v6's `(1 + amp)` normalisation goes, and the
  lit part of a cell is at full level rather than 73% of it;
- the aperture-weighted blend reads `F` directly instead of a sine at the
  boundary;
- `lp_brightness` ships at **1.00**, not 1.25 — the 1.25 exists to give back the
  light a sinusoid mesh eats, and this one eats `amp*w`, about 15%. Left at 1.25
  the whole frame clipped and the grid vanished;
- the stripes lose the sin/cos pair the mesh used to share with them, and the
  colour-cast correction needs a new closed form. A gap's fundamental is
  `2·sin(πw)/π` of its depth where a sinusoid's is 1, its mean is `1 − amp·w`
  rather than 1, and its trough no longer coincides with the stripe phase, so
  all three terms appear where v6 needed none. Measured on a white field, the
  worst channel spread over the case matrix is **0.208 levels against v9a's
  2.250** — the correction is right, and better than the one it replaces.

**It costs 94 ops**: 432 against v9a's 338, which is a predicted 108% of a frame
and the only shader in this repository over one. Three `gapInt` evaluations
replace one closed-form sinusoid integral. If this arm wins, making it cheap is
the next job — and it has to be before the waveform could go near `lcd-turbo`.

`v9c` also crawls more at equal brightness (0.256 against v9a's 0.066 at 1.00):
a harder edge gives the end clamp more to bite on.
