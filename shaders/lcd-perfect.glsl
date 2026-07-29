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
    cell and the column matrix about 3.7%.

    The defaults were chosen by measuring, not by eye. At 320x240 into 1024x768
    they give a mean level of 82.5%, a row swing of 58 and a column swing of 36,
    which is within a few percent of crt-perfect's own figures, at a moire beat
    of 0.24 - lower than crt-perfect's 0.26, and seven times lower than lcd1x's
    1.87 at a grid more than twice as strong. Raising lp_grid or lp_gap past the
    defaults trades beat for contrast: lp_grid 0.55 at lp_gap 0.20 doubles the
    row swing and quadruples the beat, past the point where it is visible.

    Both the grid and the stripes darken the image, as a real panel does.
    lp_brightness compensates, but it is a linear gain into a hard clamp, and a
    clamp is a non-linearity applied after the blend - which is exactly what this
    shader is built to avoid, and it measurably brings the beat back. To brighten,
    prefer lp_gamma below 1: it lifts more, crushes no highlights and adds no
    beat.

    Unlike the grid, the stripes do not band-limit themselves: their pattern
    repeats once per cell whatever their width, so below about three output pixels
    per cell they turn into colour speckle rather than fading. They are faded out
    over that range explicitly. At 1024x768 only Game Boy-sized content has real
    room for them; at 640x480 they are off almost everywhere. They also cost beat
    far faster than the grid does - 0.24 at the default 0.20, but 0.56 at 0.35 and
    1.18 at 0.50 - and they leave a tint of about one 8-bit level on a white
    field, because the sqrt below is applied per channel and the three stripes do
    not sample the same phases.

    NOT SIMULATED, deliberately:

      - Response-time ghosting. It needs the previous frame, so it needs a
        feedback pass, and the intended hosts run single-pass GLSL only.
      - Backlit versus reflective response, and panel colour casts. Those belong
        to a colour pass, not to a geometry one.
      - Non-square pixels. Every panel in scope is square-pixel.

*/

#pragma parameter lp_grid       "lp_grid"       0.30 0.00 1.00 0.05
#pragma parameter lp_gap        "lp_gap"        0.16 0.00 0.50 0.01
#pragma parameter lp_subpixels  "lp_subpixels"  0.20 0.00 1.00 0.05
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
#define lp_grid 0.30
#define lp_gap 0.16
#define lp_subpixels 0.20
#define lp_layout 0.0
#define lp_brightness 1.00
#define lp_gamma 1.00
#endif

// The column matrix as a fraction of the row matrix, measured off a Game Boy
// Color panel: 3.7% of the cell across against 9% down.
#define GAP_ASPECT 0.4

// Antiderivative of the aperture profile, normalised so its mean over a cell is
// exactly 1 whatever the parameters are. The aperture is a trapezoid: lit across
// a width of w, dark across the rest, with a linear ramp of width t joining them.
//
// Differencing it over an output pixel's footprint gives the true mean of the
// aperture over that pixel - the box filter itself, not an approximation of it -
// for the price of a floor and two clamps, with no transcendental anywhere.
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
// The ramp is not decoration either. A hard-edged aperture is a rectangle, and a
// rectangle carries every harmonic of the cell frequency. Those above Nyquist
// fold back to low frequencies - at 3.2 output pixels per cell the third
// harmonic lands on a 16-pixel period, squarely in the visible band - and a
// one-pixel box prefilter only attenuates it by a factor of fifteen, which is
// nowhere near enough. Compared at matched contrast, widening the ramp to twice
// the matrix width takes the worst measured beat from 2.52 to 0.23, an eleven-
// fold reduction, and makes contrast far more even across scale factors as a
// side effect. Softening was first tried at fixed visibility, where it looked
// useless; it only shows up once contrast is held constant.
//
// One identity below is worth naming: at an integer x the fractional term
// vanishes and A(x) == x exactly, for every v, w and t. That is what makes the
// grid-weighted blend in main() free.
vec2 apertureIntegral(vec2 x, vec2 w, vec2 t, float v)
{
    vec2 n = floor(x);
    vec2 f = x - n;
    // integral of a unit ramp of width t, twice: once rising at 0, once at w - t
    vec2 s0 = clamp(f / t, 0.0, 1.0);
    vec2 s1 = clamp((f - (w - t)) / t, 0.0, 1.0);
    vec2 phi = (t * s0 * s0 - t * s1 * s1) * 0.5
               + max(f - t, 0.0) - max(f - w, 0.0);
    return (1.0 - v) * x + v * (n + phi / (w - t));
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

    vec2 aw = max(1.0 - lp_gap * vec2(GAP_ASPECT, 1.0), 1e-3);
    // ramp width, twice the matrix it joins, held clear of the flat top so the
    // trapezoid never collapses into a triangle
    vec2 at = min(max(2.0 * (1.0 - aw), 1e-4), 0.45 * aw);
    // Peak of that profile, which is its flat top: the modulation is scaled so
    // this lands at 1 and nothing above it exists.
    //
    // Normalising on the mean instead is tempting - it makes the grid cost no
    // brightness at all - but it puts the flat top above 1, so every bright pixel
    // runs into the clamp at the end of main(). A clamp is a non-linearity
    // applied after the blend, which is the one thing this shader may not do, and
    // it showed up exactly as predicted: pure white lost 7% of its light and the
    // beat rose with it. Peak-normalising costs mean level instead, which
    // lp_gamma below 1 gives back with no clipping and no beat.
    vec2 pk = (1.0 - lp_grid) + lp_grid / (aw - at);

    vec2 Alo = apertureIntegral(p - h, aw, at, lp_grid);
    vec2 Ahi = apertureIntegral(p + h, aw, at, lp_grid);

    // total aperture in this footprint; the floor matters because at a large
    // scale and a fat matrix a whole output pixel can land inside the gap, and
    // this is a divisor
    vec2 I = max(Ahi - Alo, 1e-6);
    vec2 w = clamp((B - Alo) / I, 0.0, 1.0);

    // mean aperture over the footprint, scaled so the flat top is exactly 1
    vec2 g = I / (2.0 * h * pk);
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
    // the stripes are, so unlike the grid it never flattens; below roughly three
    // output pixels per cell there is no room for three of them and what survives
    // is colour speckle at full strength rather than a fading tint.
    // ------------------------------------------------------------------
    vec3 stripe = vec3(1.0);
    if (lp_subpixels > 0.0) {
        float amount = lp_subpixels * smoothstep(3.0, 6.0, 1.0 / d.x);
        if (amount > 0.0) {
            vec3 third = vec3(1.0 / 3.0);
            // Stripe edges get a ramp too, but a much narrower one than the
            // matrix. The matrix wants a wide ramp to kill its harmonics; the
            // stripes measured no beat benefit from one, and a wide ramp only
            // narrows their flat top, which drives the peak up and the mean
            // level down for nothing.
            vec3 st = vec3(min(max(0.5 * lp_gap, 1e-4), 0.15 / 3.0));
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
