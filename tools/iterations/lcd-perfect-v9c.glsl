// lcd-perfect v9c - an LCD black matrix and RGB stripes, pixel-perfect scale.
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
//   lp_gap         0.25 - 3.00  Grid line thickness, in output pixels.
//   lp_balance     0.00 - 1.00  Row/column balance. 0 rows, 1 columns.
//   lp_min_pitch   2.00 - 6.00  Smallest pattern pitch, in output pixels.
//   lp_subpixels   0.00 - 1.00  RGB stripe visibility. 0 disables them.
//   lp_layout      0 / 1        Stripe order: RGB or BGR.
//   lp_brightness  0.25 - 4.00  Output gain. 1.00 disables it.
//   lp_gamma       0.50 - 2.00  Output gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// A handheld LCD look: a black matrix of thin dark lines with RGB subpixel
// stripes, over a clean pixel scale. Reads like a Game Boy Color or GBA screen
// seen close up - a defined grid of a set thickness in pixels, which stays even
// at every scale instead of breaking into a pattern.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - Row/column balance sets which axis dominates. Real panels are row-dominant;
//   0.80 or so matches lcd1x.
// - Line thickness is in output pixels, so the grid looks the same whatever the
//   game's resolution. Above about a third of a cell it stops reading as a line.
// - The line can never take more than 90% of a cell, so at scales below about
//   3x the top of the thickness range stops doing anything.
// - Grid visibility is the line's darkness, not the whole cell's, so it wants a
//   higher setting than a soft mesh does. 1.00 is a hard black matrix.
// - Brightness above 1.00 clips, and a clip beats against the pixel grid unless
//   the output is a whole multiple of the source. Off an integer scale, prefer
//   gamma. The lit part of a cell is already at full level, so unlike a soft
//   mesh this one needs no gain to make up for what it takes.

#pragma parameter lp_grid       "Grid visibility"          0.30 0.00 1.00 0.01
#pragma parameter lp_gap        "Grid line thickness px"   1.00 0.25 3.00 0.25
#pragma parameter lp_balance    "Row/column balance"       0.60 0.00 1.00 0.01
#pragma parameter lp_min_pitch  "Minimum pitch in px"      3.00 2.00 6.00 0.25
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
uniform COMPAT_PRECISION float lp_gap;
uniform COMPAT_PRECISION float lp_balance;
uniform COMPAT_PRECISION float lp_min_pitch;
uniform COMPAT_PRECISION float lp_subpixels;
uniform COMPAT_PRECISION float lp_layout;
uniform COMPAT_PRECISION float lp_brightness;
uniform COMPAT_PRECISION float lp_gamma;
#else
#define lp_grid 0.30
#define lp_gap 1.00
#define lp_balance 0.60
#define lp_min_pitch 3.00
#define lp_subpixels 0.20
#define lp_layout 0.0
#define lp_brightness 1.00
#define lp_gamma 1.00
#endif

#define TAU 6.283185307
#define PI  3.141592654

// cos and sin of TAU/6, the angle from a cell's centre to the red stripe.
// Green sits half a turn from there, so its pair is (-1, 0) and costs nothing.
#define COS_TAU_6 0.5
#define SIN_TAU_6 0.866025404

// Mean of a unit sinusoid over one output pixel. The stripes are sampled, so
// they need it named; the mesh gets its own from the integral below.
float boxSinc(float f)
{
    float x = PI * max(f, 1e-4);
    return sin(x) / x;
}

// The gap train's antiderivative, in periods: whole gaps from floor(), the
// partial one from min(). Continuous at every integer, because fract() reaches
// 1 exactly where floor() steps, so no epsilon is needed on the floor.
vec2 gapInt(vec2 x, vec2 w)
{
    return floor(x) * w + min(fract(x), w);
}

// Past Nyquist the pattern would fold to a coarser pitch at nearly full
// strength, so take it out entirely instead.
vec2 nyquistFade(vec2 f)
{
    return 1.0 - smoothstep(0.34, 0.5, f);
}

void main()
{
    vec2 p = TEX0.xy * TextureSize;
    vec2 d = max(InputSize / OutputSize, 1e-6);
    vec2 B = floor(p + 0.5);

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

    // The aperture integral, differenced over the footprint: the exact box
    // filter, so a hard line is band-limited by construction the way
    // dmg-perfect's dot is.
    //
    // The gap is centred on the cell boundary, and its width is given in output
    // pixels, so f converts it to a share of a period. Capped below a whole
    // cell so there is always something lit.
    //
    // Alo is reused below, so it takes the UNCLAMPED difference.
    vec2 gw  = clamp(lp_gap * f, 0.0, 0.9);
    vec2 go  = t + 0.5 * gw;
    vec2 Flo = gapInt(go - hh, gw);
    vec2 Fhi = gapInt(go + hh, gw);

    vec2 Iraw = 2.0 * hh - amp * (Fhi - Flo);
    vec2 Alo  = (t - hh) - amp * Flo;
    vec2 I    = max(Iraw, 1e-6);

    // The lit part of a cell is 1, not 1 + amp: outside the line the mesh does
    // not dim the picture at all, which is what a black matrix looks like.
    vec2 g = I / (2.0 * hh);
    float gain = g.x * g.y;

    // While the mesh tracks the cells its dark line sits on the cell boundary,
    // where the scaler's soft transition pixel also sits, so the two correlate
    // and the blend must be weighted by aperture rather than by area. Once the
    // mesh locks to output space that correlation is gone.
    vec2 Bt  = B / N;
    vec2 AB  = Bt - amp * gapInt(Bt + 0.5 * gw, gw);
    vec2 w   = clamp((AB - Alo) / I, 0.0, 1.0);

    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;

    vec3 a = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 b = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 c = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 e = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    vec3 color = mix(mix(e, c, w.x), mix(b, a, w.x), w.y);

    // Three sinusoids 120 degrees apart, summing to exactly 3 at every pixel,
    // so they are luminance neutral and blue costs no third cosine. They ride
    // the mesh's pitch rules, so the box filter and the fade band-limit them.
    //
    // The mesh is no longer a sinusoid, so it no longer supplies this pair.
    vec3 stripe = vec3(1.0);
    if (lp_subpixels > 0.0) {
        float Xs   = TAU * (t.x - phase.x);
        float sinX = sin(Xs);
        float cosX = cos(Xs);

        float sinc = boxSinc(f.x);
        float ac   = lp_subpixels * sinc * fade.x;
        vec2 rg = 1.0 + ac * vec2(COS_TAU_6 * cosX + SIN_TAU_6 * sinX, -cosX);
        // Peak-normalised, so the triad never exceeds 1. It is the other half
        // of the same rule: nothing multiplied in after the blend may push the
        // result past the clamp. Every other pattern in this repo already does
        // this; the stripe peaked near 2 and was the one that did not.
        stripe = vec3(rg, 3.0 - rg.x - rg.y) / (1.0 + ac);

        // Take the colour cast out. A column mesh and the stripes share a
        // pitch, so whichever stripe lands on the mesh's dark line is dimmed.
        // The mean of the product over a cell has a closed form, so dividing by
        // it costs a constant and no extra taps.
        //
        // A gap's fundamental is 2*sin(PI*w)/PI of its depth where a sinusoid's
        // is 1, and its mean is 1 - amp*w rather than 1, so both appear here
        // where v9a needed neither. Must use the BOX-FILTERED amplitude or it
        // overshoots where the filter bites.
        float M  = amp.x * sinc * (2.0 / PI) * sin(PI * gw.x);
        float Ap = TAU * phase.x;
        float cA = cos(Ap);
        float sA = sin(Ap);
        // The gap sits on the boundary and the stripe argument carries -phase,
        // so unlike v9a the two do not cancel and the offset has to be rotated
        // through. Dropping it reintroduces the very cast being corrected.
        vec3 ph = vec3(COS_TAU_6 * cA - SIN_TAU_6 * sA,
                       -cA,
                       COS_TAU_6 * cA + SIN_TAU_6 * sA);
        vec3 corr = 1.0 - (0.5 * M * ac / max(1.0 - amp.x * gw.x, 1e-3)) * ph;
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
    //
    // Brightness rides the pattern, so the one clamp below lands on the whole
    // product. Clamping the taps instead flattens every highlight to white
    // before the mesh and stripes can shape it. See docs/lcd-perfect.md.
    vec3 m = sqrt(max(stripe * (gain * lp_brightness), 0.0));

    // Before the pattern, so gamma leaves the grid's contrast alone. v5 puts
    // it after, where it deepens the grid too.
    if (abs(lp_gamma - 1.0) > 0.001) {
        color = pow(max(color, 1e-8), vec3(lp_gamma));
    }

    vec3 outc = color * m;

    FragColor = vec4(clamp(outc, 0.0, 1.0), 1.0);
}


#endif
