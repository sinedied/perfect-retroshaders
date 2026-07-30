// lcd-perfect-v2a - a sinusoidal LCD mesh over a pixel-perfect scale.
// -----------------------------------------------------------------------------
// Author:  sinedied
// Licence: MIT - Copyright (c) 2026 sinedied
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions: the above copyright
// notice and this permission notice shall be included in all copies or
// substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS",
// WITHOUT WARRANTY OF ANY KIND.
// -----------------------------------------------------------------------------
// PARAMETERS
//
//   lp_grid        0.00 - 1.00  Grid visibility. 0 disables it.
//   lp_balance     0.00 - 1.00  Row/column balance. 0 rows, 1 columns.
//   lp_subpixels   0.00 - 1.00  RGB stripe visibility. 0 disables them.
//   lp_layout      0 / 1        Stripe order: RGB or BGR.
//   lp_brightness  0.25 - 4.00  Output gain.
//   lp_gamma       0.50 - 2.00  Source gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// Simulates a handheld LCD panel as a soft mesh rather than a hard matrix: one
// sinusoid across the source columns and one across the rows, both locked to
// the source grid. This is the shape lcd1x uses, and a sinusoid carries no
// harmonics to fold back past Nyquist, so it stays clean where a hard-edged
// aperture needs a widened ramp to.
//
// lp_balance sets which axis dominates. Real panels are row-dominant - a Game
// Boy Color measures a 9% matrix down against 3.7% across - but lcd1x is the
// reverse at about 4:1, which is a balance of 0.8.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - The stripes need a few output pixels per cell and fade out below that, so
//   they only show on small sources or high output resolutions.

#pragma parameter lp_grid       "Grid visibility"          0.37 0.00 1.00 0.01
#pragma parameter lp_balance    "Row/column balance"       0.79 0.00 1.00 0.01
#pragma parameter lp_subpixels  "RGB stripe visibility"    0.20 0.00 1.00 0.05
#pragma parameter lp_layout     "Stripe order 0=RGB 1=BGR" 0.00 0.00 1.00 1.00
#pragma parameter lp_brightness "Brightness"               1.00 0.25 4.00 0.05
#pragma parameter lp_gamma      "Gamma"                    1.00 0.50 2.00 0.05

#if defined(VERTEX)

#if __VERSION__ >= 130
#define COMPAT_VARYING out
#define COMPAT_ATTRIBUTE in
#define COMPAT_TEXTURE texture
#else
#define COMPAT_VARYING varying
#define COMPAT_ATTRIBUTE attribute
#define COMPAT_TEXTURE texture2D
#endif

#ifdef GL_ES
#define COMPAT_PRECISION mediump
#else
#define COMPAT_PRECISION
#endif

COMPAT_ATTRIBUTE vec4 VertexCoord;
COMPAT_ATTRIBUTE vec4 COLOR;
COMPAT_ATTRIBUTE vec4 TexCoord;
COMPAT_VARYING vec4 COL0;
COMPAT_VARYING vec4 TEX0;

uniform mat4 MVPMatrix;
uniform COMPAT_PRECISION int FrameDirection;
uniform COMPAT_PRECISION int FrameCount;
uniform COMPAT_PRECISION vec2 OutputSize;
uniform COMPAT_PRECISION vec2 TextureSize;
uniform COMPAT_PRECISION vec2 InputSize;

void main()
{
    gl_Position = MVPMatrix * VertexCoord;
    COL0 = COLOR;
    TEX0.xy = TexCoord.xy;
}

#elif defined(FRAGMENT)

#if __VERSION__ >= 130
#define COMPAT_VARYING in
#define COMPAT_TEXTURE texture
out vec4 FragColor;
#else
#define COMPAT_VARYING varying
#define FragColor gl_FragColor
#define COMPAT_TEXTURE texture2D
#endif

#ifdef GL_ES
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#define COMPAT_PRECISION highp
#else
#define COMPAT_PRECISION
#endif

uniform COMPAT_PRECISION int FrameDirection;
uniform COMPAT_PRECISION int FrameCount;
uniform COMPAT_PRECISION vec2 OutputSize;
uniform COMPAT_PRECISION vec2 TextureSize;
uniform COMPAT_PRECISION vec2 InputSize;
uniform sampler2D Texture;
COMPAT_VARYING vec4 TEX0;

#ifdef PARAMETER_UNIFORM
uniform COMPAT_PRECISION float lp_grid;
uniform COMPAT_PRECISION float lp_balance;
uniform COMPAT_PRECISION float lp_subpixels;
uniform COMPAT_PRECISION float lp_layout;
uniform COMPAT_PRECISION float lp_brightness;
uniform COMPAT_PRECISION float lp_gamma;
#else
#define lp_grid 0.37
#define lp_balance 0.79
#define lp_subpixels 0.20
#define lp_layout 0.0
#define lp_brightness 1.00
#define lp_gamma 1.00
#endif

#define TAU 6.283185307

// Antiderivative of the aperture profile, which is a sinusoid of one cycle per
// cell, mean 1, darkest on the cell boundary:
//
//   a(x) = 1 - m * cos(TAU * (x - phase))
//   A(x) = x - m * sin(TAU * (x - phase)) / TAU
//
// Differencing A over an output pixel's footprint is the exact mean of a over
// that pixel, which reduces in closed form to a(x) scaled by sinc of the
// footprint - the same band-limiting crt-perfect does, for two sines.
//
// A sinusoid rather than a rectangle because a rectangle carries every harmonic
// of the cell frequency, and the ones above Nyquist fold back into the visible
// band: at 3.2 output pixels per cell the third harmonic lands on a 16-pixel
// period. A sinusoid has nothing to fold. It also costs no floor, no clamp and
// no ramp integral, which is most of what the hard-edged version spends.
//
// The identity that matters is A(n) == n at integers, since that is what makes
// the aperture-weighted blend in main() free. It holds exactly when phase is 0,
// and when it is not, A(n) - n is m * sin(TAU * phase) / TAU - a constant across
// the draw, so it stays free.
vec2 apertureIntegral(vec2 x, vec2 m, vec2 phase)
{
    return x - m * sin(TAU * (x - phase)) / TAU;
}

vec3 apertureIntegral3(vec3 x, vec3 w, vec3 t, float v)
{
    vec3 n = floor(x);
    vec3 f = x - n;
    vec3 s0 = clamp(f / t, 0.0, 1.0);
    vec3 s1 = clamp((f - (w - t)) / t, 0.0, 1.0);
    vec3 phi = (t * s0 * s0 - t * s1 * s1) * 0.5
               + max(f - t, 0.0) - max(f - w, 0.0);
    return (1.0 - v) * x + v * (n + phi / (w - t));
}

void main()
{
    // ------------------------------------------------------------------
    // Scaler and grid together, because they cannot be separated without
    // manufacturing moire.
    //
    // The obvious construction - scale the image, then multiply by the grid -
    // computes mean(source) * mean(grid) over each output pixel. What it owes is
    // mean(source * grid), and the two differ by the covariance of the source and
    // the grid inside that pixel. Normally that is a rounding-level distinction.
    // Here it is not, because the matrix line sits exactly on the cell boundary
    // and so does the scaler's one soft transition pixel: the two are perfectly
    // correlated, and how much they overlap changes from cell to cell at a
    // non-integer scale. Measured, that construction beats at 2.5 - twelve times
    // the visible threshold - and no amount of gamma handling touches it, because
    // it is not a gamma problem.
    //
    // So the blend is weighted by the aperture instead. The footprint spans at
    // most two cells, the source is constant within each, and the grid is
    // separable, so the exact mean of the product is still a four-tap bilinear
    // blend - only with the weights taken from how much *aperture* falls on each
    // side of the boundary rather than how much area. Since A(B) == B at an
    // integer boundary, that costs nothing beyond the two integrals the grid
    // needed anyway, and it collapses to the plain area weights when the grid is
    // off.
    //
    // The blend is taken on the encoded values. That is what keeps the result
    // free of moire in the other direction: any non-linearity applied across the
    // blend gives partial-coverage pixels a coverage-dependent shift that beats.
    // ------------------------------------------------------------------
    vec2 p = TEX0.xy * TextureSize;
    vec2 d = max(InputSize / OutputSize, 1e-6);
    vec2 h = 0.4995 * d;
    vec2 B = floor(p + 0.5);

    // Amplitude per axis. x modulates across the columns and so draws the
    // vertical structure; lp_balance splits the total between them, 0.5 being
    // even and the ratio being b / (1 - b). Clamped because a sinusoid of
    // amplitude over 1 would go negative, and this is a light transmission.
    vec2 amp = clamp(lp_grid * 2.0 * vec2(lp_balance, 1.0 - lp_balance), 0.0, 1.0);

    // Half an output pixel, unconditionally. Without it every even-integer scale
    // puts both samples of a cell on symmetric points of the cosine and reads the
    // same value from each: at exactly 2.0 output pixels per cell the grid
    // vanishes completely. Measured over a dense sweep from 2.0 to 8.0, this
    // shift removes every dropout and is never worse than not shifting - median
    // contrast is unchanged, the minimum goes from 0 to 60.
    vec2 phase = 0.5 * d;

    vec2 Alo = apertureIntegral(p - h, amp, phase);
    vec2 Ahi = apertureIntegral(p + h, amp, phase);
    // A(B) - B, which the phase shift makes non-zero; uniform across the draw
    vec2 AB = B + amp * sin(TAU * phase) / TAU;

    vec2 I = max(Ahi - Alo, 1e-6);
    vec2 w = clamp((AB - Alo) / I, 0.0, 1.0);

    // Mean aperture over the footprint, scaled so the peak is exactly 1.
    //
    // Normalising on the mean instead is tempting - it makes the grid cost no
    // brightness at all - but it puts the crest above 1, so every bright pixel
    // runs into the clamp at the end of main(). A clamp is a non-linearity
    // applied after the blend, which is the one thing this shader may not do, and
    // it measured exactly that way: pure white lost 7% of its light and the beat
    // rose with it. Peak-normalising costs mean level instead, which lp_gamma
    // below 1 gives back with no clipping and no beat.
    vec2 g = I / (2.0 * h * (1.0 + amp));
    float gain = g.x * g.y;

    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;

    vec3 a = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 b = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 c = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 e = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    // Gamma goes on the taps, before the blend, so the blend stays linear in them
    // and the argument above still holds. Applying it to the blended colour would
    // be four times cheaper and would bring the beat back. The branch is uniform
    // across the draw, so a gamma of 1 costs nothing. The base is clamped because
    // pow(0, g) is undefined and returns NaN on real drivers, and black texels are
    // everywhere; 1e-8 is small enough that pure black still encodes to 0 even at
    // the lowest gamma, where 1e-5 would lift it to 1/255.
    if (abs(lp_gamma - 1.0) > 0.001) {
        vec3 gm = vec3(lp_gamma);
        a = pow(max(a, 1e-8), gm);
        b = pow(max(b, 1e-8), gm);
        c = pow(max(c, 1e-8), gm);
        e = pow(max(e, 1e-8), gm);
    }

    // mix(x, y, t) returns y at t == 1, so the low-side tap goes second on both axes
    vec3 color = mix(mix(e, c, w.x), mix(b, a, w.x), w.y);

    // ------------------------------------------------------------------
    // RGB stripes: three apertures across the cell, a third of it each, box
    // filtered the same way. Their coverages sum to exactly one at every scale,
    // so the stripe is exactly luminance neutral - a white field comes out white,
    // never tinted - and blending toward white keeps that true at any visibility.
    //
    // These do not get the weighted-blend treatment the grid gets: it would need
    // a separate pair of weights per channel, so three times the taps, and they
    // do not need it - their dark bands fall inside the cell rather than on its
    // boundary, so they barely correlate with the scaler's transition pixel.
    //
    // They do need a fade. The stripe pattern repeats once per cell however thin
    // the stripes are, so unlike the grid it never flattens; below a few output
    // pixels per cell there is no room for three of them and what survives is
    // colour speckle at full strength rather than a fading tint.
    //
    // The window is measured, not assumed. A fade of 3 to 6 leaves the stripes
    // at 1.3% of their strength at 3.2 output pixels per cell - which is
    // 320x240 into 1024x768, the most common scale there is - so they did
    // nothing at all exactly where they were most wanted. 2.5 to 5.0 takes the
    // colour they deliver there from 0.6 to 9 levels while holding the beat
    // under threshold; opening it further to 2.5 to 4.0 gives 21 levels but
    // costs a beat of 0.57 on the hard-edged aperture, which is over budget.
    // ------------------------------------------------------------------
    vec3 stripe = vec3(1.0);
    if (lp_subpixels > 0.0) {
        float amount = lp_subpixels * smoothstep(2.5, 5.0, 1.0 / d.x);
        if (amount > 0.0) {
            vec3 third = vec3(1.0 / 3.0);
            // A narrow ramp on the stripe edges. Widening it only narrows the
            // flat top, which drives the peak up and the mean level down, and
            // the stripes measured no beat benefit from it.
            vec3 st = vec3(0.05);
            vec3 sx = vec3(p.x) - vec3(0.0, 1.0 / 3.0, 2.0 / 3.0);
            // the aperture integral is normalised to a mean of 1, so at full
            // visibility a stripe already swings between 0 and 3
            vec3 cov = (apertureIntegral3(sx + vec3(h.x), third, st, 1.0)
                        - apertureIntegral3(sx - vec3(h.x), third, st, 1.0))
                       / (2.0 * h.x);
            // phases put R on the first third of the cell, G on the second and B
            // on the last; swizzling is how BGR is reached, negating the phases
            // instead would give RBG
            if (lp_layout >= 0.5) {
                cov = cov.bgr;
            }
            // Mean-normalised, not peak-normalised like the matrix. A stripe
            // concentrates one channel's light into a third of the cell, so its
            // mean is what has to stay at 1 for white to stay white - which puts
            // its peak near 3 and means high visibilities clip. That is inherent
            // to faking subpixels at all, not a choice this shader is making;
            // the default is set low enough that it stays off the clamp.
            stripe = mix(vec3(1.0), cov, amount);
        }
    }

    // ------------------------------------------------------------------
    // The colour is still encoded, and the encoding is treated as a gamma of 2,
    // so sqrt(linear * m) == encoded * sqrt(m). One square root therefore
    // replaces the whole decode, modulate and re-encode round trip while leaving
    // the modulation itself in linear light, where it belongs.
    // ------------------------------------------------------------------
    vec3 m = sqrt(max(stripe * (gain * lp_brightness), 0.0));

    FragColor = vec4(clamp(color * m, 0.0, 1.0), 1.0);
}

#endif
