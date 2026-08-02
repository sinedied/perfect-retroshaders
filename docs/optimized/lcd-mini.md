# lcd-mini

`lcd-turbo` with the scaler removed: the mesh, the RGB stripes and the cast
correction, at 1:1. **218 ops and 1 tap** against `lcd-turbo`'s 284; predicted
device cost 8.7 ms, 52% of a frame against 64%.

Read `docs/optimized/mini.md` first for the contract every mini shares.

## The one mini that gets structurally cheaper

`lcd-turbo` does not weight its single tap by footprint overlap. It weights it by
the mesh's own aperture, because the mesh's dark line sits on the cell boundary
and so does the scaler's soft transition pixel — the two correlate, and a plain
area blend leaves the correlation in the picture as a beat:

| `lcd-turbo` blend | worst moiré over the matrix |
|---|---:|
| plain area weights | 1.890 |
| aperture-weighted | 0.118 |

That machinery — `Alo`, `AB` and the boundary sine that positions them — is 70
of `lcd-turbo`'s 190 floor ops. **`lcd-mini` has no blend to weight, so all of
it goes: a 120-op floor against 190.**

Every other mini saves less, because what they drop is the scale itself rather
than something the scale forced on them: `crt-mini` saves 37 ops, `dmg-mini` 20,
`colour-mini` 33. This is the one place the split pays on the clock.

## Where the cost is now

| stage | ops | SFU | share of the shader with everything on |
|---|---:|---:|---:|
| one tap at 1:1 + pitch and band-limit setup | 120 | 7 | 55% |
| RGB stripes + cast correction | 86 | 6 | 40% |
| mesh | 7 | 0 | 3% |
| brightness · gamma | 6 | 6 | 3% |

The stripe block is now the largest single thing in the shader, and most of it
is the colour-cast correction. That is not optional — without it the stripes
tint the whole picture — so it needs a cheaper form rather than removal. It is
the second lever in `docs/optimized.md`.

## Assemblies

| stack | passes | device ms | frame |
|---|---:|---:|---:|
| `lcd-mini` alone | 1 | *8.7* | *52%* |
| `shimmerless → lcd-mini` | 2 | *10.8* | *65%* |
| `pixel-turbo → lcd-mini` | 2 | *10.9* | *66%* |
| `colour-mini @src → pixel-turbo → lcd-mini` | 3 | *11.1* | *66%* |
| `lcd-turbo` alone, for comparison | 1 | *10.7* | *64%* |

All predicted.

The first two rows are the choice this shader exists for. Alone it is 12 points
cheaper than `lcd-turbo` and the picture is softer, because the frontend's own
bilinear upscale is what feeds it. With a scaler in front it costs 2 points more
than `lcd-turbo` and looks the same.

The three-pass row is the clean one: brightness applied at source resolution
carries no moiré exception at all, for 2 points over `lcd-turbo`. See
`docs/optimized/colour-mini.md`.

## Measured

| | worst over the matrix |
|---|---:|
| moiré, defaults | 0.406 |
| moiré, everything on | 0.990 |
| crawl, defaults | 0.714 |
| crawl, everything on | 2.944 |

**Lower than `lcd-turbo` at defaults on both** (1.860 and 0.872), and the reason
is the missing scaler rather than anything this shader does better: a bilinear
upscale is smooth, so there is less structure for the brightness curve to beat
against. One exception is recorded, 0.406 at 480x272 → 1024x768.

The stripe crawl at full depth is `lcd-perfect`'s own inherited figure — the
stripe's aperture error, which `lcd-perfect-v7` fixed at +40% ops and was
rejected for. Nothing here made it worse.

Against `lcd-perfect-v8` the difference is large (104/255 at brightness 1.00),
and that number means nothing: it is a shader with a box scaler being compared
to one without. The comparison that matters is `pixel-turbo → lcd-mini` against
`lcd-turbo`, and that is a device measurement, not a harness one.
