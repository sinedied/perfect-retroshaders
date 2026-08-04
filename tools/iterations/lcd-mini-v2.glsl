// lcd-mini v2 - an LCD matrix and RGB stripes, to sit behind any scaler.
// -----------------------------------------------------------------------------
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
//   lp_min_pitch   2.00 - 6.00  Smallest pattern pitch, in output pixels.
//   lp_subpixels   0.00 - 1.00  RGB stripe visibility. 0 disables them.
//   lp_layout      0 / 1        Stripe order: RGB or BGR.
//   lp_brightness  0.25 - 4.00  Midtone lift. 1.00 disables it.
//   lp_gamma       0.50 - 2.00  Output gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// A handheld LCD look: a soft backlit mesh with RGB subpixel stripes. Reads
// like a Game Boy Color or GBA screen in good light - a gentle grid rather
// than a hard black matrix, and it stays even at every scale instead of
// breaking into a pattern.
//
// Notes:
// - Draws the panel and nothing else. Put a scaler in front of it - pixel-turbo
//   is the matching one - or accept the sampler's own smooth upscale.
// - Render at the output resolution, 1:1 with the display.
// - Row/column balance sets which axis dominates. Real panels are row-dominant;
//   0.80 or so matches lcd1x.
// - Brightness lifts the midtones and leaves white at white, so highlights
//   never wash out.

#pragma parameter lp_grid       "Grid visibility"          0.30 0.00 1.00 0.01
#pragma parameter lp_balance    "Row/column balance"       0.60 0.00 1.00 0.01
#pragma parameter lp_min_pitch  "Minimum pitch in px"      3.00 2.00 6.00 0.25
#pragma parameter lp_subpixels  "RGB stripe visibility"    0.20 0.00 1.00 0.05
#pragma parameter lp_layout     "Stripe order 0=RGB 1=BGR" 0.00 0.00 1.00 1.00
#pragma parameter lp_brightness "Brightness"               1.25 0.25 4.00 0.05
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
uniform COMPAT_PRECISION float lp_min_pitch;
uniform COMPAT_PRECISION float lp_subpixels;
uniform COMPAT_PRECISION float lp_layout;
uniform COMPAT_PRECISION float lp_brightness;
uniform COMPAT_PRECISION float lp_gamma;
#else
#define lp_grid 0.30
#define lp_balance 0.60
#define lp_min_pitch 3.00
#define lp_subpixels 0.20
#define lp_layout 0.0
#define lp_brightness 1.25
#define lp_gamma 1.00
#endif

#define TAU 6.283185307
#define PI  3.141592654

// cos and sin of TAU/6, the angle from a cell's centre to the red stripe.
// Green sits half a turn from there, so its pair is (-1, 0) and costs nothing.
#define COS_TAU_6 0.5
#define SIN_TAU_6 0.866025404

// Mean of a unit sinusoid over one output pixel. The mesh gets this exactly
// from the integral below; the stripes are sampled, so they need it named.
float boxSinc(float f)
{
    float x = PI * max(f, 1e-4);
    return sin(x) / x;
}

// Past Nyquist the pattern would fold to a coarser pitch at nearly full
// strength, so take it out entirely instead.
vec2 nyquistFade(vec2 f)
{
    return 1.0 - smoothstep(0.34, 0.5, f);
}

void main()
{
    // Source pixels, from InputSize rather than TextureSize: a later pass is
    // handed the ORIGINAL source size in InputSize, so TextureSize cannot be
    // trusted here.
    vec2 p = TEX0.xy * InputSize;
    vec2 d = max(InputSize / OutputSize, 1e-6);

    // Cells per period: one, until a cell is too small to carry a line, then a
    // WHOLE number of cells rather than a fixed size in output pixels - that is
    // what keeps the pattern periodic on the source grid so it cannot beat.
    //
    // ceil() on a division needs the bias: a/b is a*rcp(b), so a ratio equal to
    // 1 can land a hair above and jump the image to a two-cell period.
    vec2 N = max(ceil(lp_min_pitch * d - 1e-4), 1.0);

    vec2 f = d / N;

    // One fade, read twice: the mesh takes both axes, the stripes the column
    // one. A sinusoid does not band-limit itself, so this cannot be dropped.
    vec2 fade = nyquistFade(f);

    // Once a period spans several cells only one boundary in N carries a line,
    // so the same amplitude concentrates into a heavier pattern. N == 1, every
    // ordinary case, is untouched.
    vec2 amp = clamp(lp_grid * 2.0 * vec2(lp_balance, 1.0 - lp_balance), 0.0, 1.0)
               * fade * (2.0 / (N + 1.0));

    // Half an output pixel, in cycles: puts one sample per cycle on the
    // trough, which is what lets a two-pixel pitch resolve at all.
    vec2 phase = 0.5 * f;

    // The pattern coordinate, in periods. With N == 1 this is exactly p.
    vec2 t  = p / N;
    vec2 hh = 0.4995 * f;

    // The aperture integral over the footprint: the exact box filter. Both ends
    // are symmetric about X, so one cos of X does the work of two, and the
    // stripes below ride the same pair. q is uniform-only and hoists out.
    //
    // There is no blend here, so the aperture-WEIGHTED blend lcd-turbo needs -
    // Alo, AB and a third sine - goes with it. That machinery exists because the
    // mesh's dark line and the scaler's soft transition pixel sit on the same
    // cell boundary and correlate; with no scaler underneath there is no
    // transition pixel to correlate with.
    vec2 X    = TAU * (t - phase);
    vec2 sinX = sin(X);
    vec2 cosX = cos(X);
    vec2 q    = amp * sin(TAU * hh) / (TAU * hh);

    // Peak-normalised, so the flat top lands at 1 and nothing meets the clamp.
    vec2 g = max(1.0 - q * cosX, 0.0) / (1.0 + amp);
    float gain = g.x * g.y;

    // Straight through: behind a scaler this is 1:1 and exact.
    vec3 color = COMPAT_TEXTURE(Texture, TEX0.xy).rgb;

    // Three sinusoids 120 degrees apart, summing to exactly 3 at every pixel,
    // so they are luminance neutral and blue costs no third cosine. They ride
    // the mesh's pitch rules, so the box filter and the fade band-limit them.
    //
    // The triad is centred on its cell, so both stripe angles are a constant
    // offset from X and the pair above covers them by the angle-sum identity.
    vec3 stripe = vec3(1.0);
    if (lp_subpixels > 0.0) {
        float sinc = boxSinc(f.x);
        float ac   = lp_subpixels * sinc * fade.x;
        vec2 rg = 1.0 + ac * vec2(COS_TAU_6 * cosX.x + SIN_TAU_6 * sinX.x,
                                  -cosX.x);
        // Peak-normalised, so the triad never exceeds 1. It is the other half
        // of the same rule: nothing multiplied in after the blend may push the
        // result past the clamp. Every other pattern in this repo already does
        // this; the stripe peaked near 2 and was the one that did not.
        stripe = vec3(rg, 3.0 - rg.x - rg.y) / (1.0 + ac);

        // Take the colour cast out. A column mesh and the stripes share a
        // pitch, so whichever stripe lands on the mesh's dark line is dimmed -
        // about four levels on a white field. The mean of the product over a
        // cell has a closed form, so dividing by it costs a constant and no
        // extra taps. Must use the BOX-FILTERED amplitude, not the nominal one,
        // or it overshoots where the filter bites.
        // The stripe argument already carries -phase and the trough is at
        // phase, so it cancels. Subtracting it again rotates the correction off
        // the symmetry and reintroduces the very cast being corrected.
        float M = amp.x * sinc;
        vec3 corr = 1.0 - 0.5 * M * ac * vec3(COS_TAU_6, -1.0, COS_TAU_6);
        // The closed form is the cast in linear light, but sqrt() below halves
        // any relative deviation on the way to the encoded value, so the
        // correction has to be halved too. Applying it whole overshoots to the
        // opposite sign.
        stripe /= sqrt(max(corr, 1e-3));

        if (lp_layout >= 0.5) {
            stripe = stripe.bgr;
        }
    }

    // The colour is still encoded, and the encoding is treated as a gamma of 2,
    // so sqrt(linear * m) == encoded * sqrt(m): one square root replaces the
    // whole decode, modulate and re-encode round trip.
    vec3 m = sqrt(max(stripe * gain, 0.0));

    // Brightness rides the gamma exponent, so the two cost one pow(). As a gain
    // it would have to clip, and one tap cannot clamp per source pixel - the
    // texture unit has already blended. An exponent leaves 0 at 0 and 1 at 1,
    // so nothing meets the clamp. It does beat, and that is a recorded
    // exception; see docs/optimized/lcd-turbo.md.
    //
    // Before the pattern, so it leaves the grid's contrast alone.
    // Guarded on the two parameters rather than on their ratio: max() of two
    // literals does not constant-fold, so a guard on the ratio kept the pow in
    // the shader at settings where it does nothing.
    if (abs(lp_gamma - 1.0) > 0.001 || abs(lp_brightness - 1.0) > 0.001) {
        color = pow(max(color, 1e-8),
                  vec3(lp_gamma / max(lp_brightness, 1e-3)));
    }

    vec3 outc = color * m;

    FragColor = vec4(clamp(outc, 0.0, 1.0), 1.0);
}


#endif
