// lcd-perfect - an LCD matrix and RGB stripes over a pixel-perfect scale.
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
// The mesh follows the source grid, one cycle per cell, while a cell is wide
// enough to carry a line. Below lp_min_pitch output pixels per cell the period
// grows to a whole number of cells rather than to a fixed size in output
// pixels, so it keeps tracking the source and stays exactly periodic on it.
// That is what keeps a 480x272 source usable: at 640x480 it is 1.33 output
// pixels per cell, below the two per cycle any pattern needs.
//
// The stripes are three sinusoids 120 degrees apart, summing to a constant at
// every pixel. They ride the mesh's pitch rules, so they band-limit with it.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - A column mesh and the stripes share a pitch, so they multiply into a
//   per-channel cast. It is divided out in closed form.

#pragma parameter lp_grid       "Grid visibility"          0.30 0.00 1.00 0.01
#pragma parameter lp_balance    "Row/column balance"       0.50 0.00 1.00 0.01
#pragma parameter lp_min_pitch  "Minimum pitch in px"      3.00 2.00 6.00 0.25
#pragma parameter lp_subpixels  "RGB stripe visibility"    0.20 0.00 1.00 0.05
#pragma parameter lp_layout     "Stripe order 0=RGB 1=BGR" 0.00 0.00 1.00 1.00
#pragma parameter lp_brightness "Brightness"               1.20 0.25 4.00 0.05
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
#define lp_grid 0.34
#define lp_balance 0.79
#define lp_min_pitch 3.00
#define lp_subpixels 0.20
#define lp_layout 0.0
#define lp_brightness 1.00
#define lp_gamma 1.00
#endif

#define TAU 6.283185307
#define PI  3.141592654

// Integral of the aperture profile 1 - m*cos(TAU*(t - phase)), in cycles.
// Differencing it over an output pixel's footprint is the exact box filter, and
// at an integer t the sine term depends on the phase alone, which is what lets
// the blend below be weighted by aperture rather than by area.
vec2 apertureIntegral(vec2 t, vec2 m, vec2 phase)
{
    return t - m * sin(TAU * (t - phase)) / TAU;
}

// Mean of a unit sinusoid of f cycles per output pixel over one pixel, reaching
// zero at one cycle per pixel. The mesh gets this exactly, from the integral
// above; the stripes are sampled rather than integrated, so they need it named.
float boxSinc(float f)
{
    float x = PI * max(f, 1e-4);
    return sin(x) / x;
}

// Nothing above Nyquist can be represented, so take the pattern out entirely
// rather than let it fold to a coarser pitch at nearly full strength. Reaching
// zero at half a cycle per pixel is the point: between there and one cycle the
// fold is what would be seen, not the pattern.
vec2 nyquistFade(vec2 f)
{
    return 1.0 - smoothstep(0.34, 0.5, f);
}

void main()
{
    vec2 p = TEX0.xy * TextureSize;
    vec2 d = max(InputSize / OutputSize, 1e-6);
    vec2 h = 0.4995 * d;
    vec2 B = floor(p + 0.5);

    // ------------------------------------------------------------------
    // Which regime the mesh is in.
    //
    // One cycle per source cell while the cells are big enough to carry it, so
    // the mesh follows the content. Below lp_min_pitch output pixels per cell it
    // stops tracking the source and takes a fixed output-space pitch, which is
    // exactly periodic on the pixel grid and so cannot alias at all.
    //
    // A sinusoid does not band-limit itself. The trapezoid this shader grew out
    // of did - its coverage flattens on its own as cells shrink - and the fade
    // was dropped along with it when the aperture changed. That is what let a
    // 480x272 source through: at 640x480 it is 1.33 output pixels per cell,
    // below the two per cycle a pattern needs, and it folded to a wrong coarser
    // pitch at nearly full amplitude.
    //
    // The regime blend is a narrow biased smoothstep, not a comparison. GPUs
    // evaluate a/b as a*rcp(b), so a pitch mathematically equal to lp_min_pitch
    // can land either side of it, and the regimes do not agree on contrast.
    // ------------------------------------------------------------------
    // ------------------------------------------------------------------
    // How many cells the mesh spans per period.
    //
    // One, while a cell is wide enough to carry a line. When it is not, the
    // period grows to a whole number of cells rather than to a fixed size in
    // output pixels. That distinction is the whole fix: a pattern pinned to
    // output space stops tracking the source, and a two-dimensional one then
    // interferes with the pixel blocks - a 3px mesh over 2px blocks measured a
    // real 12px beat, and at 480x272 into 640x480 it was worse. crt-perfect
    // escapes that only because its horizontal pattern is a colour mask and
    // carries no luminance, so its luminance pattern is one-dimensional and has
    // nothing to interfere in the other axis. A mesh has both axes and cannot
    // borrow that.
    //
    // Staying on a whole number of cells keeps the pattern exactly periodic on
    // the source grid, so it cannot beat against it at any scale, and the
    // aperture-weighted blend below keeps working unchanged.
    //
    // ceil() on a division needs the bias: GPUs evaluate a/b as a*rcp(b), so a
    // ratio mathematically equal to 1 can land a hair above it and jump the
    // whole image to a two-cell period.
    // ------------------------------------------------------------------
    vec2 N = max(ceil(lp_min_pitch * d - 1e-4), 1.0);

    vec2 f = d / N;

    // Once a period spans several cells, only one boundary in N carries a line,
    // so the same amplitude concentrates into a coarser, heavier pattern that
    // has more room to interfere with the content. Easing it back over that
    // range is what brings 480x272 into 640x480 from 0.94 to 0.34; N == 1, which
    // is every ordinary case, is untouched. 1/N was measured too and buys
    // another 0.1 of beat for noticeably less mesh at N == 2.
    vec2 amp = clamp(lp_grid * 2.0 * vec2(lp_balance, 1.0 - lp_balance), 0.0, 1.0)
               * nyquistFade(f) * (2.0 / (N + 1.0));

    // Half an output pixel, in cycles. It puts one sample per cycle on the
    // trough, which is what lets a two-pixel pitch resolve at all: sampling at
    // pixel centres instead places both samples symmetrically about the peak,
    // and they return the same value.
    vec2 phase = 0.5 * f;

    // The pattern coordinate, in periods. With N == 1 this is exactly p.
    vec2 t  = p / N;
    vec2 hh = 0.4995 * f;

    vec2 Alo = apertureIntegral(t - hh, amp, phase);
    vec2 Ahi = apertureIntegral(t + hh, amp, phase);
    vec2 I   = max(Ahi - Alo, 1e-6);

    // Peak-normalised, so the flat top lands at 1 and nothing meets the clamp.
    vec2 g = I / (2.0 * hh * (1.0 + amp));
    float gain = g.x * g.y;

    // ------------------------------------------------------------------
    // The blend weights.
    //
    // While the mesh tracks the cells, its dark line sits on the cell boundary,
    // which is where the scaler's one soft transition pixel sits too, so the two
    // correlate and the blend has to be weighted by how much aperture falls each
    // side rather than how much area. Once the mesh locks to output space that
    // correlation is gone and plain area weights are the correct ones, so the
    // two are blended on the same regime term.
    // ------------------------------------------------------------------
    vec2 Bt  = B / N;
    vec2 AB  = Bt - amp * sin(TAU * (Bt - phase)) / TAU;
    vec2 w   = clamp((AB - Alo) / I, 0.0, 1.0);

    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;

    vec3 a = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 b = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 c = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 e = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    // Gamma on the taps, before the blend, so the blend stays linear in them.
    // pow(0, g) is undefined and returns NaN on real drivers, and black texels
    // are everywhere, so the base is clamped; 1e-8 is small enough that pure
    // black still encodes to 0 even at the lowest gamma.
    if (abs(lp_gamma - 1.0) > 0.001) {
        vec3 gm = vec3(lp_gamma);
        a = pow(max(a, 1e-8), gm);
        b = pow(max(b, 1e-8), gm);
        c = pow(max(c, 1e-8), gm);
        e = pow(max(e, 1e-8), gm);
    }

    vec3 color = mix(mix(e, c, w.x), mix(b, a, w.x), w.y);

    // ------------------------------------------------------------------
    // RGB stripes: three sinusoids 120 degrees apart, which sum to exactly 3 at
    // every pixel, so the stripe is luminance neutral by construction and blue
    // costs no third cosine. They ride the mesh's own pitch rules, so the box
    // filter and the Nyquist fade band-limit them and no separate fade is
    // needed - the one they used to have switched them off entirely at 3.2
    // output pixels per cell, which is the most common scale there is.
    //
    // The -1/6 centres the triad on its cell: red at 1/6, green at 1/2 and blue
    // at 5/6 across it.
    // ------------------------------------------------------------------
    vec3 stripe = vec3(1.0);
    if (lp_subpixels > 0.0) {
        float sinc = boxSinc(f.x);
        float ac   = lp_subpixels * sinc * nyquistFade(f).x;
        vec2 rg = 1.0 + ac * cos(TAU * (t.x - phase.x - (1.0 / 6.0)
                                        - vec2(0.0, 1.0 / 3.0)));
        stripe = vec3(rg, 3.0 - rg.x - rg.y);

        // --------------------------------------------------------------
        // Take the colour cast out.
        //
        // A column mesh and a stripe mask both sit at one cycle per cell, so
        // they correlate: whichever stripe lands on the mesh's dark line is
        // dimmed relative to the other two, and swapping the stripe order swaps
        // which one, so RGB and BGR cast in different directions. It is not a
        // small effect - an uncorrected column-dominant mesh casts about four
        // levels on a white field, where crt-perfect casts none, and it is only
        // absent there because a CRT mask has no column pattern to correlate
        // with in the first place.
        //
        // The mean of the product over a cell has a closed form: for a mesh
        // 1 - M*cos(TAU*(t - psi)) against a stripe 1 + ac*cos(TAU*(t - k)) it
        // is 1 - (M*ac/2)*cos(TAU*(k - psi)). Dividing each channel by that
        // equalises the three for a per-channel constant and no extra taps. The
        // amplitude has to be the box-filtered one, not the nominal one, or the
        // correction overshoots wherever the filter is biting.
        // --------------------------------------------------------------
        // The stripe argument already carries -phase, and the mesh trough is
        // at phase, so the phase cancels out of the difference between them.
        // Subtracting it a second time here is what an earlier version did, and
        // it rotated the correction off the symmetry: red and blue stopped
        // matching, which put a cast in that flipped sign with the stripe
        // order - the exact fault being corrected for.
        float M = amp.x * sinc;
        vec3 corr = 1.0 - 0.5 * M * ac
                    * cos(TAU * (vec3(0.0, 1.0 / 3.0, 2.0 / 3.0) + (1.0 / 6.0)));
        // The square root is not decoration. That closed form is the cast in
        // linear light, but what is seen - and measured - is the encoded value,
        // and sqrt() below halves any relative deviation on the way there. So
        // the correction has to be halved too, which is what taking its square
        // root does. Applying it whole overshoots to the opposite sign: green
        // went from 3 levels bright to 3.4 levels dark.
        stripe /= sqrt(max(corr, 1e-3));

        if (lp_layout >= 0.5) {
            stripe = stripe.bgr;
        }
    }

    // The colour is still encoded, and the encoding is treated as a gamma of 2,
    // so sqrt(linear * m) == encoded * sqrt(m): one square root replaces the
    // whole decode, modulate and re-encode round trip.
    vec3 m = sqrt(max(stripe * (gain * lp_brightness), 0.0));

    FragColor = vec4(clamp(color * m, 0.0, 1.0), 1.0);
}


#endif
