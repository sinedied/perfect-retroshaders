# unflat-mini

Barrel distortion and the tube's rounded corners, on their own, so a scaler and
a pattern of the caller's choosing can sit in front.

It exists because of a measurement rather than a preference. Curvature was the
one option in this repository that **cost when it was switched off** — 3.58 ms
on `crt-turbo` with the slider at zero — because the block wrote two values that
the rest of the shader then had to compute per fragment instead of once per
draw. Taking it out of `crt-mini` is worth more than the feature costs to run.

## What it saved

| | device ms | frame |
|---|---:|---:|
| `crt-mini` v4, curvature present and **off** | 10.48 | 63% |
| **`crt-mini` v5, curvature deleted** | **7.94** | **48%** |
| `unflat-mini` alone, curvature **on** at 0.15 | 4.14 | 25% |
| **`crt-mini` → `unflat-mini`, curvature on** | **10.42** | **63%** |

**The composed chain with the bend actually on is cheaper than the single-pass
version was with the bend off.** That is the whole argument for the split, and
it is not what a second full-screen pass usually does.

## What it costs in quality

Composing is not free, and the shader header says so. In `crt-perfect` the warp
happens *before* the scaler, so the mask and scanlines are drawn in warped space.
Here the pattern is drawn flat and then resampled by the bend, so it softens.

Measured on a flat field at curvature 0.15, as the peak-to-trough depth of the
scanline modulation:

| region | single-pass `crt-perfect` | `crt-mini` → `unflat-mini` | the chain, unwarped |
|---|---:|---:|---:|
| centre | 57.5 | 54.1 | 55.3 |
| edge | 55.7 | 53.8 | 55.3 |

**About 6% of pattern depth against single-pass, and 2% against not bending at
all.** There is mild banding where the warp compresses rows, visible on a flat
field and hard to see on real content. This was expected to be much worse — a
bilinear resample of a one-pixel-pitch pattern could have destroyed it — and the
reason it does not is that the warp is gentle enough that most of the screen is
near-identity.

So: use `crt-perfect`'s built-in curvature when you want the best picture, and
`unflat-mini` when you want the frame time or want to bend something else.

## The geometry

Unchanged from `crt-mini` v4, because it was already right and the numbers were
already recorded in `docs/crt-perfect.md`:

- The warp is `c * (1 + k*r2)` divided by `(1 + k)`. That divisor is the design
  decision: it is the edge-midpoint value, so an image edge lands exactly on the
  screen edge and **nothing is ever cropped**, while the corners fall outside
  and become the tube's rounded corners.
- Dividing by the corner value `(1 + 2k)` crops the whole border instead and
  reads as a lens bump. That is what `crt-perfect-v7` did, and it passed every
  number in the harness while having pushed the entire image border off-screen.
- No divisor at all leaves black on all four sides.
- The corner mask is a linear ramp, `um_corner` output pixels wide, because the
  sampler clamps to edge and would otherwise stretch the border texel across the
  whole corner.

`um_corner` is exposed here where `crt-mini` had it fixed at one output pixel:
with no pattern of its own to hide behind, the edge is more visible.
