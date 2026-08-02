// lcd-perfect v7 - an LCD matrix and RGB stripes over a pixel-perfect scale.
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
//   lp_brightness  0.25 - 4.00  Output gain. 1.00 disables it.
//   lp_gamma       0.50 - 2.00  Output gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// A handheld LCD look: a soft backlit mesh with RGB subpixel stripes, over a
// clean pixel scale. Reads like a Game Boy Color or GBA screen in good light -
// a gentle grid rather than a hard black matrix, and it stays even at every
// scale instead of breaking into a pattern.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - Row/column balance sets which axis dominates. Real panels are row-dominant;
//   0.80 or so matches lcd1x.

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

// cos and sin of TAU/6, the angle from a cell's centre to the red stripe.
// Green sits half a turn from there, so its pair is (-1, 0) and costs nothing.
#define COS_TAU_6 0.5
#define SIN_TAU_6 0.866025404

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
    // filter. Both ends are symmetric about X at a half-width Y that depends
    // only on the sizes, so by the angle-sum identities one sin and one cos of
    // X do the work of four, and the stripes below ride the same pair.
    //
    // Alo reuses that product, so it must take the UNCLAMPED difference or the
    // two stop agreeing exactly where the clamp bites.
    vec2 X    = TAU * (t - phase);
    vec2 sinX = sin(X);
    vec2 cosX = cos(X);

    vec2 Y    = TAU * hh;
    vec2 sinY = sin(Y);
    vec2 cosY = cos(Y);
    vec2 k    = amp / TAU;

    vec2 Iraw = 2.0 * hh - k * (2.0 * cosX * sinY);
    vec2 Alo  = t - 0.5 * Iraw - (k * cosY) * sinX;
    vec2 I    = max(Iraw, 1e-6);

    // Peak-normalised, so the flat top lands at 1 and nothing meets the clamp.
    vec2 g = I * (1.0 / (2.0 * hh * (1.0 + amp)));

    // While the mesh tracks the cells its dark line sits on the cell boundary,
    // where the scaler's soft transition pixel also sits, so the two correlate
    // and the blend must be weighted by aperture rather than by area. Once the
    // mesh locks to output space that correlation is gone.
    //
    // The one sine left that does not share X: taken at the boundary B. The
    // matching cosine is what lets the stripes take the same treatment below.
    vec2 Bt   = B / N;
    vec2 psiB = TAU * (Bt - phase);
    vec2 sinB = sin(psiB);
    vec2 AB   = Bt - k * sinB;
    vec2 w    = clamp((AB - Alo) / I, 0.0, 1.0);

    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;

    vec3 a = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 b = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 c = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 e = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    // Three sinusoids 120 degrees apart, summing to exactly 3 at every pixel,
    // so they are luminance neutral and blue costs no third cosine.
    //
    // INTEGRATED ACROSS THE COLUMN, not sampled at its centre, and weighted per
    // channel into the blend rather than multiplied on after it. A stripe
    // multiplied on afterwards makes the shader compute average(content) x
    // average(stripe) where it wants average(content x stripe); the two differ
    // by a covariance whose size depends on where the cell boundary falls
    // inside the pixel, which walks with the scroll and reads as a slow colour
    // band. See docs/lcd-perfect.md.
    vec3 wx   = vec3(w.x);
    vec3 gx   = vec3(g.x);
    if (lp_subpixels > 0.0) {
        float ac = lp_subpixels * fade.x;
        // The mesh is a TROUGH at the cell boundary, 1 - amp*cos, so it enters
        // the product with a negative amplitude. Getting this sign wrong puts
        // the colour cast correction below on the wrong side of white.
        float A  = -amp.x;

        // theta at the two ends of the footprint and at the cell boundary. The
        // ends come from the angle-sum pair already computed for the mesh, so
        // only the boundary cosine is new.
        float cosBx = cos(psiB.x);
        vec3 sinT = vec3(sinX.x * cosY.x - cosX.x * sinY.x,   // t - hh
                         sinB.x,                              // boundary
                         sinX.x * cosY.x + cosX.x * sinY.x);  // t + hh
        vec3 cosT = vec3(cosX.x * cosY.x + sinX.x * sinY.x,
                         cosBx,
                         cosX.x * cosY.x - sinX.x * sinY.x);
        vec3 pos  = vec3(t.x - hh.x, Bt.x, t.x + hh.x);

        // Antiderivative of (mesh x stripe) at all three positions at once. The
        // mesh and the stripe share a pitch, so their product carries a second
        // harmonic; double-angle keeps it free of another sine.
        vec3 sin2T = 2.0 * sinT * cosT;
        vec3 cos2T = 1.0 - 2.0 * sinT * sinT;
        vec3 Amesh = pos + (A / TAU) * sinT;
        float Aac  = A * ac;

        vec3 Fr = Amesh + (ac / TAU) * (sinT * COS_TAU_6 - cosT * SIN_TAU_6)
                + Aac * (0.5 * COS_TAU_6 * pos
                         + (sin2T * COS_TAU_6 - cos2T * SIN_TAU_6) / (4.0 * TAU));
        vec3 Fg = Amesh - (ac / TAU) * sinT
                - Aac * (0.5 * pos + sin2T / (4.0 * TAU));
        // Blue is what the other two leave: the triad sums to 3 everywhere, so
        // the product sums to three times the mesh and its integral follows.
        vec3 Fb = 3.0 * Amesh - Fr - Fg;

        vec3 L = vec3(Fr.y - Fr.x, Fg.y - Fg.x, Fb.y - Fb.x);
        vec3 H = vec3(Fr.z - Fr.y, Fg.z - Fg.y, Fb.z - Fb.y);
        vec3 T = max(L + H, 1e-6);

        wx = clamp(L / T, 0.0, 1.0);
        gx = T * (1.0 / (2.0 * hh.x * (1.0 + amp.x)));

        // Take the colour cast out. The mesh and the stripes share a pitch, so
        // whichever stripe sits on the mesh's dark line is dimmed - about four
        // levels on a white field. The mean of the product over a whole cell is
        // the closed form below, so dividing by it costs a constant. It goes in
        // before the sqrt, which is where v6 applied its square root.
        gx /= 1.0 + (0.5 * Aac) * vec3(COS_TAU_6, -1.0, COS_TAU_6);

        if (lp_layout >= 0.5) {
            wx = wx.bgr;
            gx = gx.bgr;
        }
    }

    vec3 color = mix(mix(e, c, wx), mix(b, a, wx), w.y);

    // The colour is still encoded, and the encoding is treated as a gamma of 2,
    // so sqrt(linear * m) == encoded * sqrt(m): one square root replaces the
    // whole decode, modulate and re-encode round trip.
    vec3 m = sqrt(max(gx * (g.y * lp_brightness), 0.0));

    // Before the pattern, so gamma leaves the grid's contrast alone. v5 puts
    // it after, where it deepens the grid too.
    if (abs(lp_gamma - 1.0) > 0.001) {
        color = pow(max(color, 1e-8), vec3(lp_gamma));
    }

    vec3 outc = color * m;

    FragColor = vec4(clamp(outc, 0.0, 1.0), 1.0);
}


#endif
