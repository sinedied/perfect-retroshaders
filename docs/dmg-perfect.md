# dmg-perfect

Design record. Why this shader is built the way it is, what was
measured, and what was tried and rejected. AGENTS.md carries only what an agent
needs before touching anything; this is the detail behind it.

## The DMG is a negative display, and it changes the sign of everything

A Game Boy DMG is a **reflective, normally-white STN panel with no backlight**.
Undriven crystal passes light, so an unpowered pixel shows the pale green substrate
and driving a pixel makes it **dark**. The gaps between pixels have no electrode at
all, so they can never be driven and sit permanently at the lightest state.

So its matrix is **lighter than a lit pixel** — the opposite of every backlit panel
`lcd-perfect` models. That is why `dmg_dot_matrix` defaults its grid colour to white
and mixes *toward* it, and why the grid is invisible on a white field and strongest on
dark content, which is how a real DMG reads. A web search asserted the opposite and
was discounted: the same answer claimed a DMG's "on" pixels look "almost white", which
is backwards for this panel, and it cited no measurement.

Three consequences that are not obvious until the sign is right:

- **A brightness default above 1 has no job here.** Across this family the gain exists
  to restore the level the pattern removes — `lcd-perfect` and `crt-perfect` sit at
  82% and 83% of white *with* their 1.20 and 1.25 lifts. A DMG grid adds light, so
  dmg-perfect sits at **100%** of white and a lift only meets the clamp. Measured 2.06
  beat on a full-range checkerboard, against 0.12 at unity. Check the mean level on
  white before copying a brightness default across.
- **A mean-normalised aperture cannot be reused as a coverage mask.** `lcd-perfect`
  normalises its aperture to a *mean* of 1, which for these parameters peaks near 2.9;
  as a mask that drives the mix past white and blows the frame out. A mask has to be
  **peak**-normalised, 0 in the gap and 1 in the dot.
- **No ramp.** A plain rectangular pulse box-filtered over the output pixel *is* the
  reference at a whole scale factor, so the trapezoid `lcd-perfect` v1 used would be
  visibly softer than the thing it is copying — and it costs 334 instructions against
  262. Cheaper and more faithful at once; the box filter is already the correct
  anti-aliasing width. The band-limiting the ramp was there to provide comes instead
  from the gap floor below, which is exact at a whole scale where the ramp was only
  close.

### State a minimum feature size in output pixels, not as a share of a cell

`dmg_dot_matrix` draws a line of exactly **one output pixel**. That is right at a
whole scale factor and wrong everywhere else: a 1px line cannot be placed 6.4 apart,
so its cells alternate 6, 7, 6, 7; and one pixel is 16% of a cell at 1024x768 and 50%
at 320x288, so it is not the same shader at two resolutions.

Making the gap a *share* of a cell fixes both — and introduces a third fault, because
a share lands on an arbitrary number of output pixels. **Below about two pixels a line
has no guaranteed fully-covered pixel at its core**, whatever its phase, so how its ink
spreads shifts cell to cell. Measured on an exactly-even synthetic grid at a 6.4px
period: a 1.28px line reads 1.7% spacing variation, a 1.99px line reads 0.04%. That is
a 40x difference with the geometry held exactly constant, and it matches which one
reads as steady by eye.

So the rule is a floor in output pixels, applied per axis:

```glsl
vec2 sc    = OutputSize / max(InputSize, 1.0);
vec2 offs  = abs(sc - floor(sc + 0.5));      // smooth, never an equality
vec2 room  = clamp(sc - 4.0, 0.0, 1.0);
vec2 minpx = 1.0 + clamp(offs / 0.25, 0.0, 1.0) * room;
vec2 gapEff = max(vec2(dp_gap), minpx / sc);
```

Three things in there took measuring:

- **`room` is not optional.** The second pixel costs `1/sc` of a cell, which is
  already 40% at five output pixels per cell and **60%** at the 3.33 a Game Boy gets
  down the screen at 640x480 — where it stops edging the dot and starts swallowing it.
  Without the limit, 640x480 measured a 1.35px *dot* rather than a line. The metric
  caught it; the eye would have too, eventually.
- **The whole-scale test is a distance, never an equality.** A mathematically whole
  scale can land a few ULP off, which is already a recorded trap here.
- **The floor has to fade out with the parameter.** At `dp_gap` 0 the floor would
  otherwise hold a 1px line open under a slider the user has closed, so it is gated by
  `smoothstep(0.0, 0.01, dp_gap)`.

### The two-pass pipeline everyone reaches for collapses into one pass

Frontends get a good DMG by drawing `dmg_dot_matrix` at a whole scale factor and
letting a `pixellate` pass do the rest. That is not a workaround for a missing
feature — it is a **different and better computation**, and it is worth knowing why,
because v1 did the naive thing and broke up at a fractional scale.

Drawing the matrix at a whole scale then resampling gives `mean(source × grid)` over
each output pixel. Multiplying a scaled image by a grid gives `mean(source) ×
mean(grid)`. The two differ by their covariance inside the pixel, and a dot-matrix
line sits exactly on the cell boundary — which is exactly where the scaler's soft
transition pixel is — so that covariance is large and varies cell to cell. Measured
against the two-pass as ground truth, v1 was **67/255** out at 1024x768.

Both passes are linear, so the composite has a closed form. Writing `a` for
`dp_grid`:

    O = (1 - a) * A  +  a * [ L * dot + level * (1 - dot) ]

`A` is the ordinary **area**-weighted four-tap blend; `L` is the same four taps
weighted by how much **aperture** falls each side of the texel boundary; `dot` is the
mean lit coverage. Both means are needed, and that is the part that is easy to get
wrong:

| | max difference from the two-pass |
|---|---|
| area mean only — what v1 did | 10.1 at 1024x768, 45.3 at 640x480 |
| aperture mean only — what `lcd-perfect` does | **98.0** |
| **both** | **0.075**, and exactly 0.000 at whole scales |

**The aperture-weighted blend alone is right in `lcd-perfect` and wrong here**, because
its pattern peaks at the cell *centre* while a dot matrix's gap sits on the cell
*edge*. Porting the technique across by analogy makes things nine times worse than
doing nothing. It cost 25 instructions to measure that and it would have cost a
release to assume it.

`tools/twopass.py` builds the pipeline literally — nearest at a whole scale, hard
grid, then an exact box resample written from scratch — and gates the match. It
self-tests by checking that at a whole scale its own pass two is an identity.

Two details the closed form needs:

- **Where a pixel lands wholly in a gap the aperture weight is 0/0.** The value is
  arbitrary and float32 need not pick what float64 picks. It is harmless while it is
  multiplied by a coverage of zero — and it is *not* harmless the moment something
  else reads it, which is what a shadow term does. Fall back to the area weight.
- **State the line width in output pixels via the whole scale that fits**, not as a
  share of a cell: `N = max(floor(min(sc.x, sc.y) + 1e-3), 1.0)`, gap = `dp_gap / N`.
  That is what the two-pass does, it holds the line near one pixel at every scale, and
  at a whole scale it is exactly one pixel so the reference identity survives. Below
  N = 2 the picture disappears into the substrate entirely — 60% flat grey, a
  black-frame-class failure — so the grid still needs its fade.

### A metric that scores smoothness will ask for the wrong shader

v1 forced every line to at least two output pixels. That came from `grid.py`'s
spacing CV, which reads a 1.28px line as 1.7% and a 1.99px line as 0.04% — so the
metric asked for the widest line available, and the first thing anyone said about v1
was that its lines were far too fat.

The CV was not lying, it was answering a different question. A narrow line really
does spread its ink differently from cell to cell; that is edge softness, and it is
much less visible than a line twice the width it should be. `grid.py` now reports
the CV **and** the part of it that is not edge softness, by measuring a synthetic
grid of the same spacing and width whose lattice is exact by construction:

| | total CV | of which lattice |
|---|---|---|
| `dmg_dot_matrix` at 1024x768 | 7.7% / 8.9% | **6.7 / 7.6** |
| dmg-perfect-v2 at 1024x768 | 1.8% / 0.6% | **0.1 / 0.3** |

The bracketed figure is the one that means something is wrong. Judged on the total,
v2 looks four times worse than it is.

**A metric is a proxy, and a proxy that has never been checked against a preference
will eventually be optimised against that preference.** This one shipped a shader
nobody wanted, and it was only caught because the shader was looked at.

### A shadow measures opacity, and opacity is relative to the paper

A pixel casts a shadow because it blocks light, so its shadow strength is its
**opacity**, and on a reflective panel that is `1 - luma / luma(paper)` — the
level of undriven panel is the divisor, not an absolute. dmg-perfect-v2 used
`clamp(1 - luma, 0, 1)`, which is the same expression with the paper hardcoded
to **white**.

Nothing in a Game Boy palette is anywhere near white, so every shade was judged
most of the way opaque and the shadow became a flat dimming of the whole
picture. Measured on real frames: the undriven shade is luma 0.455 and covers
**67–75% of the screen**, and it was casting **55% of a full shadow**. Paper
dimmed 2.87/255 against ink's 3.88 — a ratio of **1.4x**, which is why it read
as a veil rather than as depth. With the divisor restored the same frame gives
0.02 against 1.45, a ratio of **65x**.

The tell that this was the cause rather than merely a plausible fix: on **GBC**
content, where the paper really is near-white, the old expression measures
*correctly* (paper opacity 0.027). It was never wrong in general — only whenever
paper is not white, which is every DMG palette in existence.

**The divisor cannot be a constant.** Lightest shade, by core:

| palette | paper luma |
|---|---|
| Gambatte GB-DMG — its default | **0.401** |
| mGBA DMG Green | 0.560 |
| Gambatte GB-Light | 0.568 |
| Gambatte GB-Pocket / SameBoy olive | 0.664 – 0.767 |
| SameBoy lime | 0.806 |
| SameBoy / mGBA greyscale | 0.973 – 1.000 |

So it is taken as **the brightest of the four taps the scaler already has**,
floored at 0.35. The taps are free and cannot be wrong on the high side, since
undriven panel is by definition the brightest thing near a dot; the floor stops
the estimate collapsing in the middle of a large dark region, where all four
taps are ink and the shadow would otherwise switch off exactly where the picture
is darkest. **The floor must sit below the darkest paper anyone ships** — 0.45
was proposed and would have dimmed Gambatte's *default* palette by 10.8%,
reintroducing the same bug on the most likely core, and the sample screenshots
at 0.455 would have hidden it.

Cost: the shadow-off path is **295 ops, unchanged from v2** - the branch is
uniform, so the fix is free unless the shadow is asked for. With it on the
static count is 459 against v2's 400, and it is still **6 SFU**, still four
taps, and still free of transcendentals.

**Do not copy libretro's caster.** Its Game Boy shaders compute alpha from
`1 - source.rgb` exactly as v2 did, and get away with it because those presets
*replace* the palette — they reduce the frame to a brightness and re-colour it
from their own `COLOR_PALETTE`, so the input they are handed genuinely does have
white paper. They also add a `baseline_alpha` of 0.05 to 0.10 so that even fully
undriven dots cast a shadow, which is a deliberate look and the exact opposite
of what is wanted here. No libretro Game Boy shader reconstructs a drive level
from an already-palettised frame; there is no prior art for this.

### A cast shadow goes under the panel, not into the gaps

v3 subtracted the shadow from the gap colour and only from there, on the
reasoning that the gap is the substrate and the substrate is what a shadow falls
on. That is geometrically true and visually useless: the gap is **one output
pixel wide**, so the shadow could only ever darken the grid lines. It read as a
mesh drawn on top of the picture rather than as anything lying underneath, and
at a whole scale factor it was very nearly invisible — 0.7 opacity on a 20x
render shows almost nothing.

The optics say otherwise. On a reflective panel the light crosses the liquid
crystal, reflects off the substrate and crosses back, so a neighbour that shades
the substrate scales **whatever that cell finally shows**. So the shadow is one
multiply on the finished colour:

    col *= 1.0 - dp_shadow * opacity(casting cell) * displacedAperture;

and the "under" behaviour falls out for free — an undriven cell is transparent
so the shadow reads through it clearly, a driven cell is already dark so it
hides it. That is what makes the dots look raised instead of outlined.

Three consequences worth keeping:

- **It is cheaper in beat, not dearer.** Confining a pattern to the one-pixel
  grid lines is the worst thing you can do to it: that is the highest frequency
  in the frame. Measured on a DMG palette, v3's shadow costs 0.32 at 0.35 and
  0.56 at 0.75, where v4 costs **0.19 and 0.29** — and at 0.15 to 0.30 v4
  measures *below* its own shadow-off baseline. A shadow that lies under
  everything is a low-frequency multiply; one that lives in the gaps is not.
- **Offsets belong in source pixels.** v3 measured its offset in output pixels,
  so "1.5" was three tenths of a cell at 5x and half a cell at 3x — the same
  parameter meaning a different look at each resolution, which is the fault
  `dp_gap` was fixed for two versions earlier. A shadow is thrown by a dot, so
  it belongs a fraction of a *cell* away. Verified scale-invariant: a dot in
  cell 16 throws a shadow spanning exactly +0.5 to +1.5 source pixels at 5x, 8x,
  13x and 20x alike.
- **The casting cell needs its own tap.** At a cell or more of offset it is
  outside the four the scaler holds. One nearest sample is right rather than
  merely cheap: opacity is a per-cell quantity, and the displaced aperture
  already supplies the edges. It costs a fifth texture fetch, inside the uniform
  branch, so nothing pays for it with the shadow off — the off path is 291 ops
  and four taps, bit-identical to v3.

And the same `floor()` trap once more, in a new place: the casting cell index is
`floor(p - offset)`, which lands exactly on a boundary for a great many pixels
at once whenever the offset is a whole number of source pixels away from the
half-texel sample position. A few ULP then pick a different cell across what may
be a hard edge in the content, which measured **102/255**. `floor(q + 1e-3)`
resolves it toward the cell whose dot actually starts there; where the bias
picks the far side instead, the displaced aperture is in its gap and the shadow
is zero anyway.

### A box filter you already have is a blur you can widen for free

The shadow's coverage is the exact mean of the displaced aperture over the
output pixel's footprint - that is what `dotInt(q + h) - dotInt(q - h)` divided
by `2h` computes. Widening `h` past the footprint therefore convolves the
aperture with a wider box, which is a real blur, and it costs **nothing**: the
same two antiderivative evaluations, a larger constant. Measured, the
everything-off path is 291 instructions with the blur and 291 without.

Checked against an explicit convolution of the hard pulse train rather than
assumed - the residual is discretisation only and falls as the window grows.

Two things to know before reaching for it elsewhere:

- **It fills in as it widens.** A box wider than the aperture's gap raises the
  minimum off zero: at a 0.80 duty cycle the trough goes 0.00, 0.50, 0.71 as the
  half-width goes 0.10, 0.20, 0.35 of a cell. For a shadow that is right - a
  blurred shadow should lose its internal structure - but a pattern that needs
  to keep its contrast cannot be softened this way.
- **It only blurs what the aperture controls.** The shadow's strength also comes
  from a per-cell opacity that is sampled nearest, and widening the aperture
  window does not touch that. It works here because the aperture's gaps sit
  exactly where the opacity steps, so the hard part of the step lands where the
  coverage is already near zero.

### An affine trim is free after the blend, and free again when it is neutral

`dp_red`, `dp_green` and `dp_blue` are plain per-channel gains. A gain is affine
and the blend weights sum to one, so applying it to the finished colour is
*identical* to applying it to the four taps at a quarter of the cost - the same
argument that lets `pixel-perfect-v3` grade after the blend, and not an
exception to the design rule but its converse.

It goes on the finished colour rather than on the taps for a second reason: the
substrate is part of the panel, so it should take the same tint as the picture.

Behind a uniform branch it costs nothing at all when neutral, which is what
makes it worth having on a shader with a tight budget: **291 ops with the trim
present and neutral, the same as the version that had no trim.** Measured on a
DMG palette it adds no beat at any setting tested, including gains above 1,
because a Game Boy palette peaks at 0.455 and a 1.4x gain still does not reach
the clamp - which is the thing that would have cost beat.

### A weighted blend is stable where a max over the same taps is not

The paper estimate reads the four taps and takes their maximum. That is not
safe as written, and the reason is a variant of the `floor()` knife edge already
recorded here.

`B = floor(p + 0.5)` selects the tap *pair*. At an exact boundary — which at a
whole scale factor is not an edge case but every other pixel — it can land on
either side, giving `{n-1, n}` or `{n, n+1}`. **The blend does not care**,
because whichever way it goes the weight lands entirely on the same texel; that
is why the scaler has always been stable there. A maximum over the pair very
much does care: it swaps in a different neighbour, and on a real frame that
moved the shadow by **29/255** between the GPU and the model.

The fix is to weight before reducing — gate each tap by its own blend weight,
`k = wA.x * wA.y` and so on, through a narrow `smoothstep`. At the knife edge
both candidate pairings collapse onto the same contributing tap, so the estimate
is identical either way.

**The general lesson: a reduction over the taps is not automatically as stable
as the blend over them.** Any new term that reads the taps directly rather than
through the blend has to be checked against the boundary case separately, and a
whole scale factor is where to look, not a fractional one.

### The gate that keeps a reduction stable is itself a visible artifact

The weighting fix above is correct and it was applied four times — v3 over the
scaler taps, v4 over the casting cell index, v7 over the 2x2 cell set — and the
fourth time the fix was the bug.

`smoothstep(0, 0.02, k)` is a **step**, so it matters enormously what `k` does
across a cell. Over the scaler's `wA` it is safe: that weight is saturated at 0
or 1 everywhere except the one transition pixel per block, so the gate is a
stable *selection* and `paper` comes out piecewise constant. Over the shadow's
bilinear weight it is not: `gf` sweeps the full 0..1 once per cell, so `kb`
crosses 0.02 **inside every cell**, and `paper` jumped between `PAPER_FLOOR` and
the palette's paper level along a contour that repeats per cell.

Measured against v6, that is **22/255**, and it reads as a hard dark bar down
the edge of every dark region with the soft gradient gone — which is exactly how
it was described on sight.

**v8 removes the reduction instead of gating it.** `paper` is the luma of the
area blend, floored: continuous in position by construction, stable at the
`floor()` boundary for the same reason the scaler is, and one dot product and
one max against v7's four multiplies, a `smoothstep` on a `vec4` and three
maxes. It is **7.2 points of the yardstick cheaper** and it is the version that
looks right.

| | ops | shadow off | shadow on |
|---|---|---|---|
| v6 — reduce over the scaler taps | 574 | 103.1% | 143.4% |
| v7 — reduce over the shadow cells | 549 | 103.1% | 136.0% |
| **v8 — no reduction, the blend's own luma** | **511** | 105.7% | **132.3%** |

At a whole scale factor the blend returns the source texel exactly, so **v8 is
bit-identical to v6** there — 0/255 over two sample frames at 3x, 4x and 5x and
at three shadow strengths — and v6 is the version whose blur was judged right.

**The general lesson, which supersedes the one above rather than replacing it:**
a reduction over the taps is unstable, and gating it fixes the instability by
introducing a discontinuity. Prefer not needing the reduction. Where a
divisor, a reference level or any other per-pixel quantity can be taken from the
blend instead, take it from the blend — it is continuous, it is already
computed, and it cannot manufacture structure the content does not have.

### Do not trust a smoothness metric to find a smoothness fault

The seam this caused was hunted with the obvious metric — the largest
single-output-pixel step in the shadow field — and that metric **ranked v7 as
the smoothest of the three**: 0.15 against v6's 0.22 and v8's 0.20. It is
dominated by the dot aperture's own edges, which all three share, so the term
actually at fault contributes almost nothing to it.

Nor did a paper-field roughness count help: v7's `paper` has *fewer* hard steps
than v6's (1.14% of the frame against 1.49%), because most of v7's field really
is flatter. What is wrong with it is one thin contour, not its average.

Three metrics said v7 was fine or better. The render settled it in one look.
This is the same lesson as `grid.py`'s CV shipping a shader nobody wanted, and
as `crt-perfect-v7` passing all eight gates with the border cropped off:
**anything that changes how the picture looks gets looked at.**

### The Game Boy contrast wheel is affine, which is why it is affordable

`dp_contrast` mimics the potentiometer on a DMG's LCD board. It is not digital:
it sets the amplitude of the V0–V5 bias ladder the driver builds its four drive
levels from, so it scales how hard every pixel is driven at once. Turned down
the picture washes out into undriven panel; turned up, a real one darkens
everything, background included.

The true transfer is a **sigmoid** — the LC electro-optic curve, reparametrised
by a common factor on V_rms — so it is strictly neither linear nor a power law.
But the only shipped reference implementation, libretro's `gb-pass4`, reduces
to `mix(paper, ink, alpha*contrast)` with `alpha` linear in source luminance,
which is exactly `a*x + b`. Affine is what everyone actually uses, and affine is
the one class that may sit after the blend.

Three things fall out of the pivot, and they are worth stating because the pivot
does all the work:

- **Pivot on the substrate and the map costs one multiply-add.** The substrate
  is then the map's fixed point, so applying it to the *finished* colour leaves
  the gaps exactly where they are — which is required rather than merely
  convenient, since a gap has no electrode over it and no bias voltage reaches
  it. Applying it to `area` and `dotm` separately to protect the gaps would cost
  twice as much and achieve the same thing.
- **The range stops at 1.00 because of where the map sends its endpoints, not
  because of any measurement.** It sends `[0,1]` to `[1-c, 1]`. At or below 1.00
  nothing can leave the range for any source or any palette; above it the low
  end is clipped by exactly `c-1`. Measured on a DMG palette, 1.15 reads **1.54
  beat against a 0.19 floor** with 32% of the frame clipped, while every setting
  inside the range clips **nothing** and measures at or below the floor. This is
  the `pp_sharpness` rule again: a half-range that is a known fault is not a
  tuning control. libretro ships the same `[0,1]`, very likely for this reason.
- **Fold it, do not write it as a `mix`.** `col*ga + gb` with `ga = c` and
  `gb = (1-c)*S` is `col*1.0 + 0.0` at the default, which is bit-exact.
  `mix(S, col, 1.0)` is only exactly `col` if the driver spells `mix` as
  `x*(1-a) + y*a`, and drivers ship the other form. Verified 0/255.

**A uniform branch around it bought nothing and was removed.** Unbranched it
measures 105.5% of the yardstick, branched-and-skipped 105.7%, and with the
shadow on the branch was a full point *worse*. The control costs ~2.4 points
whether it is enabled or not, so skipping the multiply-add is not what that pays
for — and the fold, not the branch, is what makes "off" exact. Do not add a
uniform branch to something this small without measuring; the idiom is not free
just because it is the idiom used elsewhere in the file.

Two things not to copy from libretro's version: it multiplies its shadow opacity
by `contrast`, coupling two controls that users set for different reasons; and
its Game Boy presets *replace* the palette, so its notion of "paper" is white in
a way ours can never be.

### Bit-identity with a reference is reachable, and worth gating on

At a whole scale factor a four-tap area average returns the source texel exactly, so a
scaler-based shader can be **bit-identical** to a point-sampling one. dmg-perfect
measures 0/255 against `dmg_dot_matrix` at 3x, 4x and 5x on both a flat field and a
game frame, wherever the two are set the same. That is a far stronger statement than
"looks the same", and `tools/grid.py` gates it.

The two 1/255 rows it reports are float32 and both were traced rather than shrugged
at: at a gamma of exactly 1 this shader skips the `pow` and the reference still
evaluates `pow(x, 1.0)`, which is `exp2(log2(x))` on a GPU and rounds; and at gamma
0.8 over a black gap `pow` has unbounded slope at 0, which moved 2 pixels out of 1.7
million. Wherever both take the same `pow`, the match is exact.

**That identity is what pins the gamma placement.** Putting the curve on the taps
instead would be design-rule-clean, but the reference gammas *after* its grid mix, and
`mix(pow(level,g), pow(c,g), m)` is not `pow(mix(level,c,m), g)` — on a dark pixel
under a light gap the two differ by **21 levels**, which is exactly where a DMG's grid
is most visible. So the cheap placement is kept and the cost is documented instead:
gamma 1.40 measures 0.86 beat against 0.12 at 1.00.
