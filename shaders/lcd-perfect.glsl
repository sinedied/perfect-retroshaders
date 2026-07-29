/*
    lcd-perfect

    Author:  sinedied
    Licence: MIT - Copyright (c) 2026 sinedied

    Permission is hereby granted, free of charge, to any person obtaining a copy of
    this software and associated documentation files (the "Software"), to deal in
    the Software without restriction, including without limitation the rights to
    use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
    of the Software, and to permit persons to whom the Software is furnished to do
    so, subject to the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial portions of
    the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

    An LCD shader: pixel-perfect scaling, a black-matrix grid and optional RGB
    subpixel stripes, in a single pass and without moire.

    Simulates the panels of handhelds like the Game Boy Color, Game Boy Advance,
    DS and PSP: a grid of rectangular apertures separated by an opaque matrix,
    each aperture split into three coloured stripes.

    An LCD cell is a rectangle, and the average of a rectangular pulse train over
    an output pixel has a closed form. So rather than band-limiting a sinusoid the
    way a CRT beam profile has to be, this shader evaluates that average exactly.
    Three things follow, and they are the reason this approach was chosen:

      - The mean is exactly the aperture width at every scale factor, so the grid
        costs no brightness and needs no compensation term.
      - Contrast falls to zero on its own as cells approach the pixel grid, so
        there is no fade to tune and nothing to alias.
      - It is floor, fract and clamp. No transcendentals at all.

    This shader must render at the final output resolution, one output pixel per
    display pixel, and the sampler must be NEAREST. If its result is rescaled
    afterwards, the grid and the stripes will alias.

    Upscaling only, like pixel-perfect: below 1:1 an output pixel spans more than
    two source texels per axis and four taps stop being an average.

    PARAMETERS

      lp_grid       0.00 - 1.00   grid visibility, 0 disables it
      lp_gap        0.00 - 0.50   matrix thickness, as a fraction of a cell
      lp_subpixels  0.00 - 1.00   RGB stripe visibility, 0 disables them
      lp_layout     0 / 1         stripe order, RGB or BGR
      lp_brightness 0.25 - 4.00   output gain
      lp_gamma      0.50 - 2.00   gamma applied to the source, 1.00 disables it

    lp_gap sets the gap between rows. The gap between columns is 0.4 of it, which
    is the ratio measured off a Game Boy Color panel - its subpixels are 0.910 of
    the cell tall but 0.296 of 0.333 wide, so the row matrix is about 9% of the
    cell and the column matrix about 3.7%. The default lp_gap of 0.12 reproduces
    that, for a fill factor near the ~75% the same panel measures.

    Unlike the grid, the stripes do not band-limit themselves: their pattern
    repeats once per cell whatever their width, so below about three output pixels
    per cell they turn into colour speckle rather than fading. They are faded out
    over that range explicitly. At 1024x768 only Game Boy-sized content has real
    room for them; at 640x480 they are off almost everywhere.

    NOT SIMULATED, deliberately:

      - Response-time ghosting. It needs the previous frame, so it needs a
        feedback pass, and the intended hosts run single-pass GLSL only.
      - Backlit versus reflective response, and panel colour casts. Those belong
        to a colour pass, not to a geometry one.
      - Non-square pixels. Every panel in scope is square-pixel.

*/

#pragma parameter lp_grid       "lp_grid"       0.80 0.00 1.00 0.05
#pragma parameter lp_gap        "lp_gap"        0.12 0.00 0.50 0.01
#pragma parameter lp_subpixels  "lp_subpixels"  0.35 0.00 1.00 0.05
#pragma parameter lp_layout     "lp_layout"     0.00 0.00 1.00 1.00
#pragma parameter lp_brightness "lp_brightness" 1.00 0.25 4.00 0.05
#pragma parameter lp_gamma      "lp_gamma"      1.00 0.50 2.00 0.05

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
uniform COMPAT_PRECISION float lp_subpixels;
uniform COMPAT_PRECISION float lp_layout;
uniform COMPAT_PRECISION float lp_brightness;
uniform COMPAT_PRECISION float lp_gamma;
#else
#define lp_grid 0.80
#define lp_gap 0.12
#define lp_subpixels 0.35
#define lp_layout 0.0
#define lp_brightness 1.00
#define lp_gamma 1.00
#endif

// The column matrix as a fraction of the row matrix, measured off a Game Boy
// Color panel: 3.7% of the cell across against 9% down.
#define GAP_ASPECT 0.4

// Antiderivative of a unit-height pulse train of period 1 and lit width w, with
// the aperture at the leading edge of the cell, differenced over a footprint of d
// to give the exact mean of the train over that footprint.
//
// Edge, not centre, and that is load-bearing. Centring the aperture splits the
// matrix line across a cell boundary, so at any integer scale factor it lands
// half in one output pixel and half in the next and the contrast halves - at
// exactly 2.0 output pixels per cell the two halves are symmetric and the grid
// disappears completely. Putting the whole line inside one cell fixes every
// integer scale at once, and costs one term less than the half-pixel phase shift
// that would otherwise be needed. It also places the line on the cell boundary,
// which is where the scaler's block boundary is and where a real black matrix is.
//
// This is the true box filter, not an approximation of one, so there is nothing
// left to alias at any scale, and the result's own mean over the pattern is
// exactly w. Both axes of the grid go through the vec2 form in one call, all
// three stripes through the vec3 form in another.
//
// Reducing x to its cell before differencing was tried, on the theory that
// making lo and hi round together would cancel their error. It changed nothing
// at all - not one pixel - because the error is already in x, carried in from
// the interpolated texcoord, not created here. Two floors for nothing.
vec2 aperture2(vec2 x, vec2 d, vec2 w)
{
    vec2 lo = x - 0.5 * d, hi = x + 0.5 * d;
    vec2 fl = floor(lo), fh = floor(hi);
    return ((fh - fl) * w + clamp(hi - fh, vec2(0.0), w) - clamp(lo - fl, vec2(0.0), w)) / d;
}

vec3 aperture3(vec3 x, vec3 d, vec3 w)
{
    vec3 lo = x - 0.5 * d, hi = x + 0.5 * d;
    vec3 fl = floor(lo), fh = floor(hi);
    return ((fh - fl) * w + clamp(hi - fh, vec3(0.0), w) - clamp(lo - fl, vec3(0.0), w)) / d;
}

void main()
{
    // ------------------------------------------------------------------
    // Area-averaged upscale, as pixel-perfect does it. Each output pixel is the
    // mean of the source over its own footprint, which spans at most two texels
    // per axis, so four taps suffice and the weights separate per axis.
    //
    // The average is taken on the encoded values. That is what keeps the result
    // free of moire: a source pixel covers three or four output pixels at a
    // non-integer scale, so the number of partial-coverage pixels varies from
    // block to block, and any non-linearity applied across the blend gives those
    // pixels a coverage-dependent shift that beats against the pixel grid.
    // ------------------------------------------------------------------
    vec2 p = TEX0.xy * TextureSize;
    vec2 d = max(InputSize / OutputSize, 1e-6);
    vec2 h = 0.4995 * d;

    vec2 B = floor(p + 0.5);
    vec2 w = clamp((B - p + h) / (2.0 * h), 0.0, 1.0);

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
        vec3 g = vec3(lp_gamma);
        a = pow(max(a, 1e-8), g);
        b = pow(max(b, 1e-8), g);
        c = pow(max(c, 1e-8), g);
        e = pow(max(e, 1e-8), g);
    }

    // mix(x, y, t) returns y at t == 1, so the low-side tap goes second on both axes
    vec3 color = mix(mix(e, c, w.x), mix(b, a, w.x), w.y);

    // ------------------------------------------------------------------
    // The black matrix. One cell per source pixel on both axes, so the grid
    // follows the content: 160x144 material gets a 160x144 grid with nothing to
    // configure.
    //
    // Dividing the coverage by the aperture width makes the pattern's mean
    // exactly 1, so lp_grid scales a term that is already zero-mean and the grid
    // costs no brightness at any scale. Nothing here needs a Nyquist fade: the
    // box filter is exact, so as cells shrink the coverage converges to the
    // aperture width on its own and the pattern flattens out instead of aliasing.
    // ------------------------------------------------------------------
    float gain = 1.0;
    if (lp_grid > 0.0 && lp_gap > 0.0) {
        vec2 aw = max(1.0 - lp_gap * vec2(GAP_ASPECT, 1.0), 1e-3);
        vec2 g = 1.0 + lp_grid * (aperture2(p, d, aw) / aw - 1.0);
        gain = g.x * g.y;
    }

    // ------------------------------------------------------------------
    // RGB stripes: three apertures across the cell, a third of it each, box
    // filtered the same way. Their coverages sum to exactly one at every scale,
    // so the stripe is exactly luminance neutral - a white field comes out white,
    // never tinted - and blending toward white keeps that true at any visibility.
    //
    // These do need a fade. The stripe pattern repeats once per cell however thin
    // the stripes are, so unlike the grid it never flattens; below roughly three
    // output pixels per cell there is no room for three of them and what survives
    // is colour speckle at full strength rather than a fading tint.
    // ------------------------------------------------------------------
    vec3 stripe = vec3(1.0);
    if (lp_subpixels > 0.0) {
        float amount = lp_subpixels * smoothstep(3.0, 6.0, 1.0 / d.x);
        if (amount > 0.0) {
            float third = 1.0 / 3.0;
            // Phases put the R aperture on the first third of the cell, G on the
            // second and B on the last. Swizzling the result is how BGR is
            // reached; negating the phases instead would give RBG, not BGR.
            vec3 cov = aperture3(p.x - vec3(0.0, third, 2.0 * third),
                                 vec3(d.x), vec3(third));
            if (lp_layout >= 0.5) {
                cov = cov.bgr;
            }
            stripe = mix(vec3(1.0), cov * 3.0, amount);
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
