# crt-perfect

Design record. Why this shader is built the way it is, what was
measured, and what was tried and rejected. AGENTS.md carries only what an agent
needs before touching anything; this is the detail behind it.

> **Tool names in this record are historical.** These notes were written against
> a harness of nine separate scripts, since consolidated into five entry points.
> The measurements are unchanged; only where they live moved. See the table in
> `docs/measurement.md`.


## Barrel distortion (crt-perfect-v6, v7, v8)

Curvature is **pure ALU** — a radial polynomial warp is `dot(c,c)` and a few
multiply-adds, with no `tan`/`atan` anywhere. That is what makes it affordable here
where CRT-Geom-style curvature is not:

| | ops | tex | SFU | curvature off | curvature on |
|---|---|---|---|---|---|
| `pixellate` (yardstick) | 292 | 4 | **30** | 100.0% | |
| `crt-perfect` flat | 501 | 4 | **14** | 104.7% | |
| v6 — patterns flat, black on all four sides | 588 | 4 | **14** | | |
| v7 — patterns warped, border cropped away | 596 | 4 | **14** | | |
| v8 — patterns warped, nothing cropped | 628 | 4 | **14** | 124.3% | 134.4% |
| v9 — v8 with the band-limit made uniform | 626 | 4 | **14** | 108.3% | 117.3% |
| **v10 — v9 with the pitch computed as if flat** | **610** | 4 | **14** | **107.5%** | **117.2%** |

**SFU never moves**, and it never predicted the time either — see the benchmark
section. The figure that matters here is that **v8 cost 19.6 points over the flat
shader even with curvature switched off**, and v9 gets that down to 3.5.

### The pattern pitch is computed as though there were no curvature

Curvature must not change the pattern's *pitch*, only its *position*. v7 to v9 lifted
the pitch floor to `cp_min_pitch * jmax` so the most magnified corner would keep
`cp_min_pitch` output pixels per cycle — and since the floor applies frame-wide, that
quietly rescaled the pattern everywhere:

| `cp_curvature` | cycles per source line | scanlines drawn |
|---|---|---|
| 0.00 | **1.000** | 240 |
| 0.05 | 0.933 | 224 |
| 0.10 | 0.838 | **201** |
| 0.15 | 0.767 | 184 |

One cycle per source line is what makes scanlines read as scanlines. Losing it is worse
than anything the floor was protecting against, because **curvature is a distortion by
construction** — artifacts it creates inside the region it is distorting are the effect,
not a defect in the pattern. v10 drops `jmax` from both the floor and the band-limit, at
which point `jmax` is dead and comes out entirely (626 → 610 ops).

The corners then run finer than the band-limit assumes: 2.16 to 2.80 output pixels per
cycle across the parameter range, always above the 2.0 that would alias, so the pattern
is drawn a little stronger there than its true box average rather than breaking up.
Measured evenness is 1.11–1.15, the same band as every other version.

**Nothing in the harness could see this.** Every curvature test measures a flat grey
field, or a checkerboard through the scaler with the patterns switched off — none of
them has a source with rows in it, so none of them can watch the pattern drift off the
source. It was caught by looking at the screen. `beat.py:source_lock()` now checks it
directly, against the older behaviour as a control.

### Do not make a band-limit argument per-fragment

This is the single most expensive mistake made in this family, and the v7 notes
asserted the opposite with confidence, so it is worth stating flatly:

> `boxSinc` holds a `sin` and `nyquistFade` a `smoothstep`. While their argument
> depends only on uniforms, **the driver hoists them out of the fragment shader** and
> evaluates them once per draw. Multiply that argument by anything per-fragment and
> you buy two `sin` and two `smoothstep` per pixel.

v7 and v8 band-limited on `freq * jac`, where `jac` is the local magnification, and
paid that on every frame whether or not curvature was on. Bisected by removing one
piece of v8 at a time:

| | vs `pixellate` | recovered |
|---|---|---|
| v8, curvature off | 124.0% | |
| minus the per-fragment band-limiting | **107.5%** | **16.5 pts** |
| minus `jac` on the scaler footprint | 122.4% | 1.6 pts |
| minus `jmax` / `noWarp` on the pitch | 123.6% | 0.4 pts |
| minus the tube mask multiply | 128.0% | none |

v9 band-limits on `freq * jmax` instead. `jmax = (1+4k)/(1+k)` is the largest
magnification anywhere in the frame and depends only on `cp_curvature`, so the
expression stays uniform and stays hoisted **in both modes** — the curvature-on path
gets 16 points faster as well. It band-limits as though every pixel sat at the most
magnified corner, which can only understate the amplitude, and the pitch floor already
held every local frequency at or under `1/cp_min_pitch`, so no aliasing margin was
given away. The cost is about 6% flatter pattern contrast across the frame; measured,
v9 is *more* uniform than v8 (1.08 against 1.13), which is the same fact stated kindly.

**Branching is not the lever.** Three other shapes were measured and all were worse:
computing the uniform form and overwriting it inside the branch (116.8%), a strict
`if/else` (112.0% off but **136.2% on**, i.e. worse than v8 in the mode it was meant to
help), and adding further uniform guards on the footprint and tube multiplies on top of
the winner (109.7%, a 2.3-point regression). Removing the per-fragment dependency is
the lever.

At `cp_curvature = 0`, **v9 is bit-identical to the shipped flat shader** — 0/255 over
three sources, four scale factors and both mask types. v8 measures 1/255 on the same
sweep, so v9 is the stricter superset. The guard is a uniform branch either way.

### What the warp is divided by is the whole design

All three apply the same warp, `c * (1 + k*r2)`. They differ only in the constant it
is normalised by, and that one constant decides the entire look:

| normalised by | corners | edges | result |
|---|---|---|---|
| nothing (v6) | inside the screen | inside the screen | tube, **black on all four sides** |
| `(1 + 2k)` — the corner value (v7) | exactly 1:1 | pushed off-screen | **the whole border is cropped**; only 89.8% of the source survives |
| `(1 + k)` — the edge-midpoint value (v8) | past the image | exactly 1:1 | tube fills the screen, **black only in the corners, nothing cropped** |

`r2` is 1 at an edge midpoint and 2 at a corner, which is where those two constants
come from. Both axes normalise by the same value, so this is symmetric at any aspect
ratio, and there is no cubic to solve for a zoom factor.

**v7's failure is worth understanding rather than just avoiding.** The curved border
*is* the cue that reads as a tube. Crop it and all that is left is the interior
magnification, which looks like a lens bump in the middle of a flat image — which is
exactly how it was described on sight. The distortion was correct; the framing was
not.

| | screen black | source visible |
|---|---|---|
| v6 | 18.45% | **100%** |
| v7 | 0.00% | 89.8% |
| **v8** | 4.50% | **100%** |

v8 across its range, at 1024x768: black 2.7% / 4.5% / 5.8% at `k` = 0.05 / 0.10 / 0.15,
**100% of the source visible at every setting**, and every edge midpoint lit — the
black is corner-shaped, never a bar.

### A curved image needs a tube mask even when it fills the screen

v7 dropped the mask because nothing was ever outside the image. v8 cannot: the sampler
is `CLAMP_TO_EDGE`, so an unmasked corner **smears the border texel** across the whole
corner rather than showing nothing. The first v8 prototype did exactly that and it was
obvious in the render and invisible in every number.

### No number in this repo could catch v7

This is the process lesson, not a footnote. Every gate was green on v7: 1/255 against
an independent model, 0.039 beat, pitch invariant exactly 3.00, 0% black pixels. It
had silently thrown away 10% of the image, including the entire border.

`preview.py --only border-grid` renders a grid whose four edges are each a different
colour, which is the pattern that shows it. A screenshot, a plain grid or a
checkerboard all show the interior distortion and say nothing about what happened to
the edges. **Anything that changes geometry gets looked at, not just measured.**

### The footprint correction is anisotropic

The scaler derives `range` from a constant `InputSize/OutputSize`; under warp the local
magnification varies, so at the edges the footprint is too small and the blend is wrong
over about a third of the frame, by up to 94/255. The correction is *not* the scalar
radial factor: for `u' = u(1 + k(u^2+v^2))` the axis-aligned derivatives are
`1 + k(3u^2 + v^2)` and `1 + k(u^2 + 3v^2)`, which differ. Both fall out of `c*c`,
already computed for `r2`, so the exact per-axis Jacobian costs the same as the wrong
scalar one. Against a supersampled reference (RMS, 8-bit levels):

| `cp_curvature` | no correction | isotropic (wrong) | anisotropic (shipped) |
|---|---|---|---|
| 0.05 | 0.901 | 0.861 | **0.817** |
| 0.10 | 1.049 | 0.927 | **0.778** |
| 0.15 | 1.239 | 1.007 | **0.753** |

Note the direction: uncorrected error *rises* with curvature while corrected error
*falls*. That divergence, not the absolute values, is what says the correction is right
rather than merely different.

### Warped patterns: the invariant, and why no image metric can check it

A pattern locked to the source cannot also be locked to the output pixel grid, so under
warp its screen pitch varies and is finest at the corners. Two things keep it safe, and
both are needed:

- the pitch floor is lifted to `cp_min_pitch * jmax`, where `jmax = (1+4k)/(1+2k)` is
  the largest magnification in the frame, so **even the worst corner keeps
  `cp_min_pitch` output pixels per cycle**;
- `boxSinc` and `nyquistFade` are evaluated on the *local* frequency `freq * jac`.

**Check this on the geometry, not on the image.** `beat.py:min_local_pitch()` does. The
obvious empirical checks do not work, because aliasing does not remove pattern energy,
it relocates it — so a strength or uniformity metric reads an aliased pattern as
perfectly healthy. Measured: the naive implementation is *more* uniform (1.07–1.14)
than the correct one (1.10–1.21) at every curvature, and its corner strength is equal
or higher. Only the invariant separates them:

| smallest output px per cycle | v7 | naive |
|---|---|---|
| 320x240 -> 1024x768, k=0.10 | **3.00** | 2.74 |
| 480x272 -> 1024x768, k=0.10 | **3.00** | 2.57 |
| 480x272 -> 1024x768, k=0.20 | **3.00** | 2.33 |

v7 sits exactly on the floor everywhere; naive falls through it.

### Two traps hit while measuring curvature

- **A pattern-strength ratio is invalid on a shader with black corners.** Tiles at the
  tube edge are part black, or contain the mask's one-pixel fade, and either way carry
  a gradient that RMS-about-the-mean scores as pattern energy: 29 against a frame-wide
  14.4, which inverts the ratio and reports a flat shader as collapsing. v7 crops
  rather than leaving corners black, which is the only reason the check ever worked —
  so **v8 shipped with it silently not applying**. `beat.py` now excludes tiles that
  are not wholly inside the tube *and* clear of the fade.
- **A row-mean profile is invalid on a warped image.** Measuring pattern contrast as
  the peak-to-peak of a tile's row-mean reported the corner collapsing from 34.7 to
  3.2 — a 10x falloff that looks exactly like catastrophic aliasing. The scanlines are
  curved there, so averaging along tile rows smears them. RMS about the local mean has
  no preferred direction and reads 12.4 against 12.1 on the same image.
- **A curved render cannot be measured with the flat beat metric.** Barrel distortion
  varies the local magnification on purpose, so block sizes genuinely change across the
  frame and a band-limited FFT scores that intended variation as moire — 4 to 20 where
  the flat metric reads 0.26. Difference against a supersampled reference of the same
  warp instead, and read the reference-noise trap below before trusting the result.

### The slot mask has an irreducible knife edge under warp

The slot mask picks its row parity with `floor()`. Flat, that argument is constant
along a row, so the `+ 1e-3` epsilon nudges whole rows clear of the boundary. **Under
warp the argument varies smoothly across the frame, so it must cross an integer
somewhere** — that crossing is what makes the rows — and wherever it does, float32 and
float64 can land on opposite sides. No epsilon fixes this; an epsilon only moves where
the crossing happens.

Measured at curvature 0.10: **16 pixels of 786432**, every one within `1.9e-5` of an
integer against a median distance of 0.25 across the frame. Isolated single pixels,
never a region, and only ever on the slot mask.

This is what `Model(outliers=N)` is for. Raising `tolerance` to 45 would have covered
it and simultaneously blinded the check to a real systematic error of the same size;
the outlier budget keeps `tolerance` at 1, counts the offenders, and prints the count.
Negative-tested both ways: a +3/255 bias everywhere fails on 921600 outliers, and
shrinking the budget to 4 fails on 16.

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
on both axes at once.

**Do not turn this into "brighten with gamma, never with gain."** That advice was
given here and has been **rejected by the project owner**: gamma below 1 flattens
contrast and washes the colours out, and clipping is what old CRTs and LCDs actually
did — which is the thing being simulated. Peak normalisation is about where the
*pattern* sits, not about how the user is told to brighten. `lp_brightness` and
`cp_brightness` are legitimate controls; the headers state what they cost and stop
there.
