/*
    crt-perfect (variant b)

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

    A CRT shader: pixel-perfect scaling, horizontal scanlines and an RGB subpixel
    mask, in a single pass.

    This variant applies cp_gamma to the scaled image rather than to the source
    samples that feed the scaler. That is one texture fetch worth of maths instead
    of four, but it costs some of the shader's immunity to moire: see the note on
    cp_gamma below.

    The source is scaled by an area average taken in the encoded (gamma) domain,
    then modulated by two pure sinusoids - one across the source lines, one across
    the source columns in three colour phases. Both patterns are band-limited, and
    both fall back to a fixed output-space pitch when the image is too small to
    carry a pattern locked to the source grid.

    This shader must render at the final output resolution, one output pixel per
    display pixel. If its result is rescaled afterwards, the mask and the scanlines
    will alias.

    PARAMETERS

      cp_scanlines   0.00 - 1.00   scanline visibility, 0 disables them
      cp_rgb_mask    0.00 - 1.00   RGB mask visibility, 0 disables it
      cp_mask_type   0 / 1 / 2     off / aperture grille / offset (slot) grille
      cp_mask_size   0.25 - 2.00   triads per source pixel
      cp_brightness  0.25 - 4.00   output gain, compensates the pattern darkening
      cp_min_pitch   2.00 - 6.00   smallest pattern pitch, in output pixels
      cp_gamma       0.50 - 2.00   gamma applied after scaling, 1.00 disables it

    NOTE ON cp_gamma IN THIS VARIANT

    The scaler mixes neighbouring source samples wherever a source pixel boundary
    falls between two output pixels. How many such mixed pixels a source pixel
    produces varies from block to block at a non-integer scale - three here, four
    there - so any curve applied *after* the mix shifts those pixels by an amount
    that depends on their coverage, and that shift repeats at the beat frequency
    between the two grids. Applying the same curve to the samples *before* the mix
    keeps the mix linear and avoids this entirely.

    In this variant the effect is visible from about cp_gamma 1.2 outwards, and it
    is present even with the scanlines and the mask fully disabled, because its
    origin is the scaler and not the patterns.

    The scanline count follows the source vertical resolution while there is room
    for it: 224-line content gets 224 scanlines with no configuration. Below
    cp_min_pitch output pixels per line the pattern switches to a fixed pitch of
    cp_min_pitch instead, which is what keeps it working on small outputs.

    Suggested pitches when the source barely fits: 3.00 gives a soft, even grid,
    2.50 is finer and punchier, and 2.00 gives one bright line and one dark line
    per pair of output pixels. Every 0.25 step repeats over a whole number of
    output pixels, so none of them beat against the pixel grid.

    Scanlines and the mask both darken the image, as a real tube does. cp_brightness
    compensates; at values above ~1.2 the beam peaks clip to white, which is a plain
    clamp rather than a bloom, so highlight detail is lost above that point.

*/

#pragma parameter cp_scanlines  "cp_scanlines"  0.55 0.00 1.00 0.05
#pragma parameter cp_rgb_mask   "cp_rgb_mask"   0.40 0.00 1.00 0.05
#pragma parameter cp_mask_type  "cp_mask_type"  1.00 0.00 2.00 1.00
#pragma parameter cp_mask_size  "cp_mask_size"  1.00 0.25 2.00 0.25
#pragma parameter cp_brightness "cp_brightness" 1.25 0.25 4.00 0.05
#pragma parameter cp_min_pitch  "cp_min_pitch"  3.00 2.00 6.00 0.25
#pragma parameter cp_gamma      "cp_gamma"      1.00 0.50 2.00 0.05

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

#define Source Texture
#define vTexCoord TEX0.xy
#define SourceSize vec4(TextureSize, 1.0 / TextureSize)
#define outsize vec4(OutputSize, 1.0 / OutputSize)

#define PI  3.141592654
#define TAU 6.283185307

#ifdef PARAMETER_UNIFORM
uniform COMPAT_PRECISION float cp_scanlines;
uniform COMPAT_PRECISION float cp_rgb_mask;
uniform COMPAT_PRECISION float cp_mask_type;
uniform COMPAT_PRECISION float cp_mask_size;
uniform COMPAT_PRECISION float cp_brightness;
uniform COMPAT_PRECISION float cp_min_pitch;
uniform COMPAT_PRECISION float cp_gamma;
#else
#define cp_scanlines 0.55
#define cp_rgb_mask 0.40
#define cp_mask_type 1.0
#define cp_mask_size 1.0
#define cp_brightness 1.25
#define cp_min_pitch 3.0
#define cp_gamma 1.0
#endif

// Exact average of a unit-amplitude sinusoid of frequency f, in cycles per output
// pixel, over one pixel-wide box. Reaches zero at one cycle per pixel.
float boxSinc(float f)
{
    float x = PI * max(f, 1e-4);
    return sin(x) / x;
}

// Nothing above Nyquist can be represented, so fade the pattern out entirely there,
// amplitude and darkening together, leaving no uniform dimming behind.
float nyquistFade(float f)
{
    return 1.0 - smoothstep(0.34, 0.5, f);
}

void main()
{
    vec2 texelSize = SourceSize.zw;

    // ------------------------------------------------------------------
    // Area-averaged upscale, straight to the output size. Each output pixel
    // integrates the source over its own footprint, so source pixels come out as
    // uniform blocks with a single soft pixel wherever a block boundary falls
    // between two output pixels; integer scale factors stay exact.
    //
    // The average is taken on the encoded values, not on linear light. That is
    // what keeps the result free of moire: a source pixel covers three or four
    // output pixels at a non-integer scale, so the number of partial-coverage
    // pixels varies from block to block, and any non-linearity applied across the
    // blend gives those pixels a coverage-dependent shift that beats.
    // ------------------------------------------------------------------
    vec2 range = vec2(abs(InputSize.x / (outsize.x * SourceSize.x)),
                      abs(InputSize.y / (outsize.y * SourceSize.y)));
    range = range / 2.0 * 0.999;

    float left   = vTexCoord.x - range.x;
    float top    = vTexCoord.y + range.y;
    float right  = vTexCoord.x + range.x;
    float bottom = vTexCoord.y - range.y;

    vec3 topLeft     = COMPAT_TEXTURE(Source, (floor(vec2(left,  top)    / texelSize) + 0.5) * texelSize).rgb;
    vec3 bottomRight = COMPAT_TEXTURE(Source, (floor(vec2(right, bottom) / texelSize) + 0.5) * texelSize).rgb;
    vec3 bottomLeft  = COMPAT_TEXTURE(Source, (floor(vec2(left,  bottom) / texelSize) + 0.5) * texelSize).rgb;
    vec3 topRight    = COMPAT_TEXTURE(Source, (floor(vec2(right, top)    / texelSize) + 0.5) * texelSize).rgb;

    vec2 border = clamp(floor((vTexCoord / texelSize) + vec2(0.5)) * texelSize,
                        vec2(left, bottom), vec2(right, top));

    // The footprint is a rectangle, so the four corner areas factor into one
    // horizontal and one vertical weight.
    float wLeft = (border.x - left) / (2.0 * range.x);
    float wTop  = (top - border.y)  / (2.0 * range.y);

    vec3 color = mix(mix(bottomRight, bottomLeft, wLeft),
                     mix(topRight,    topLeft,    wLeft), wTop);

    // Gamma on the scaled image, before the patterns are applied. The branch is
    // uniform across the draw, so a gamma of 1 costs nothing. The base is clamped
    // because pow(0, g) is undefined and returns NaN on some drivers, and the
    // floor is small enough that pure black still encodes to 0 at any gamma.
    if (abs(cp_gamma - 1.0) > 0.001) {
        color = pow(max(color, 1e-8), vec3(cp_gamma));
    }

    // ------------------------------------------------------------------
    // Scanlines. One cycle per source line while there is room for it, so the
    // count is the source vertical resolution; below cp_min_pitch output pixels
    // per line the pattern moves to output space at exactly cp_min_pitch and is
    // phase-aligned to the pixel grid.
    //
    // A grid-locked pattern repeats over a whole number of pixels and therefore
    // cannot alias, so neither the box filter nor the Nyquist fade applies to it.
    // The half-pixel shift puts one sample per cycle on the trough, which is what
    // lets a two-pixel pitch resolve at full contrast: sampling at pixel centres
    // instead would place both samples symmetrically about the peak, and they
    // would return the same value.
    //
    // The regime blend is a narrow smoothstep rather than a comparison. GPUs
    // evaluate a/b as a*rcp(b), so a source pitch mathematically equal to
    // cp_min_pitch can land a few ULP either side of it, and the two regimes
    // differ in contrast by about 30%. The window is biased so equality is fully
    // grid-locked, and is far wider than the error.
    // ------------------------------------------------------------------
    float scanSrcPitch = OutputSize.y / max(InputSize.y, 1.0);
    float scanPitch    = max(scanSrcPitch, cp_min_pitch);
    float scanLocked   = 1.0 - smoothstep(cp_min_pitch * 1.001, cp_min_pitch * 1.02, scanSrcPitch);
    float scanFreq     = 1.0 / scanPitch;

    float scanAmp = cp_scanlines * mix(nyquistFade(scanFreq), 1.0, scanLocked);
    float scanAC  = 0.5 * scanAmp * mix(boxSinc(scanFreq), 1.0, scanLocked);

    float scan = 1.0;
    if (scanAmp > 0.0) {
        float y = vTexCoord.y * OutputSize.y - 0.5 * scanLocked;
        // fract() keeps the cosine argument small; the phase reaches several
        // hundred cycles before it, which costs precision otherwise
        scan = (1.0 - 0.5 * scanAmp) - scanAC * cos(TAU * fract(y * scanFreq));
    }

    // ------------------------------------------------------------------
    // RGB mask, on the same two regimes. Three primaries 120 degrees apart sum to
    // a constant, so the mask is luminance neutral and casts no colour - which
    // also lets blue be derived from red and green rather than costing a third
    // cosine. The -1/6 offset centres the triad on its cell, putting red at 1/6,
    // green at 1/2 and blue at 5/6 across it.
    // ------------------------------------------------------------------
    float maskSrcPitch = OutputSize.x / max(InputSize.x * cp_mask_size, 1.0);
    float maskPitch    = max(maskSrcPitch, cp_min_pitch);
    float maskLocked   = 1.0 - smoothstep(cp_min_pitch * 1.001, cp_min_pitch * 1.02, maskSrcPitch);
    float maskFreq     = 1.0 / maskPitch;

    float maskAmp = cp_rgb_mask * mix(nyquistFade(maskFreq), 1.0, maskLocked);

    vec3 mask = vec3(1.0);
    if (maskAmp > 0.0 && cp_mask_type >= 0.5) {
        float x = vTexCoord.x * OutputSize.x - 0.5 * maskLocked;
        float phase = x * maskFreq - (1.0 / 6.0);

        // Offset grille: stagger the triads by half a cell on alternate lines of
        // the scanline grid. The epsilon keeps floor() off its exact boundary,
        // which its argument crosses once per line; without it a few ULP flip a
        // whole row's stagger. Note the vertical separation that makes this read
        // as slots comes from the scanlines, so it needs cp_scanlines above 0.
        if (cp_mask_type >= 1.5) {
            float row = floor((vTexCoord.y * OutputSize.y - 0.5 * scanLocked) * scanFreq + 1e-3);
            phase += 0.5 * mod(row, 2.0);
        }

        float dc = 1.0 - 0.5 * maskAmp;
        float ac = 0.5 * maskAmp * mix(boxSinc(maskFreq), 1.0, maskLocked);
        mask.rg = dc + ac * cos(TAU * (fract(phase) - vec2(0.0, 1.0 / 3.0)));
        // analytically non-negative, but keep it off sqrt()'s undefined domain
        mask.b  = max(3.0 * dc - mask.r - mask.g, 0.0);
    }

    // ------------------------------------------------------------------
    // The colour is still encoded, and the encoding is treated as a gamma of 2,
    // so sqrt(linear * m) == encoded * sqrt(m). One square root therefore
    // replaces the whole decode, modulate and re-encode round trip while leaving
    // the modulation itself in linear light, where it belongs.
    // ------------------------------------------------------------------
    vec3 gain = sqrt(max(mask * (scan * cp_brightness), 0.0));

    FragColor = vec4(clamp(color * gain, 0.0, 1.0), 1.0);
}

#endif
