# lcd-perfect

Design record. Why this shader is built the way it is, what was
measured, and what was tried and rejected. AGENTS.md carries only what an agent
needs before touching anything; this is the detail behind it.

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
