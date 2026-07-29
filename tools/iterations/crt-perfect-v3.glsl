/*
    crt-perfect-v3 - moire-free CRT scanlines and RGB mask with pixel-perfect scaling.

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

    v3 of crt-perfect.glsl. Same single-pass design, rebuilt around removing
    moire. See WHY V3 below. v1 and v2 remain available for comparison.

    REQUIRED PASS SETTINGS  (Shader > Shader 1 in the in-game menu)

        minarch_nrofshaders       = 1
        minarch_shader1           = crt-perfect-v3.glsl
        minarch_shader1_filter    = NEAREST
        minarch_shader1_srctype   = source
        minarch_shader1_scaletype = source
        minarch_shader1_upscale   = screen      <-- important
        minarch_scale_filter      = NEAREST

    "upscale = screen" makes this pass render at exactly the final on-screen size,
    so one output pixel is one device pixel. Any other upscale value resamples the
    result a second time and both the mask and the scanlines will alias.

    TIP: setting the frontend's screen scaling to "Native" gives an exact integer
    scale factor, which removes the last of the resampling beat entirely (measured
    0.00) at the cost of small black borders.

    PARAMETERS

        Scanlines    visibility of the scanlines, 0 turns them off
        RGB_Mask     visibility of the RGB mask, 0 turns it off
        Mask_Type    0 = off, 1 = aperture grille, 2 = offset (slot) grille
        Mask_Size    triads per source pixel (1.0 = one RGB triad per pixel)
        Brightness   gain applied at the end, compensates the darkening

    The scanline count is always the source vertical resolution: 224p content gets
    224 scanlines, no configuration needed. There is no beam-width control and no
    fade threshold: the profile is a pure sinusoid and the band-limiting is exact
    and automatic (see below).

    Scanlines and mask darken the image, like a real CRT and like the overlay
    images this was matched against. Brightness compensates. At the default 1.25
    the beam peaks hard-clip to white - a plain clamp, not a bloom - so highlight
    detail above ~0.89 is lost. Use 1.0 for a strictly non-clipping image.

    WHY V3 - THE THREE SOURCES OF MOIRE

    1. THE GAMMA ROUND-TRIP (dominant, measured beat 3.35 of 255)

       v1/v2 linearised each texel (x*x), blended, then re-encoded (sqrt). At a
       non-integer scale a source pixel covers 3 or 4 output pixels, so the number
       of partial-coverage blend pixels differs from block to block. Because
       sqrt(mean(x^2)) != mean(x), those blend pixels get a coverage-dependent
       brightness shift, and the shift beats at 16px.

       v3 blends in gamma space and modulates in linear. With a gamma of 2.0,
       sqrt(lin * m) == srgb * sqrt(m), so resampling in sRGB and multiplying by
       sqrt(modulation) is *identical* to modulating in linear light - the CRT
       maths stays physically correct while the blend stays perfectly linear in
       the encoded domain. Measured beat drops 3.35 -> 0.13 with no loss of
       sharpness (a hard edge still resolves in 0 output pixels), and it removes
       four vector multiplies rather than adding any.

       For reference, a 16-tap Mitchell bicubic scores 0.03 but softens that edge
       to 3 output pixels and quadruples texture bandwidth. Not worth it.

    2. BEAM HARMONICS (measured 0.03 at a pure sine, up to 1.20)

       v1/v2 shaped the beam with pow(cosine, k). That is a single frequency only
       when k == 1; any other exponent adds harmonics, and harmonics alias long
       before the fundamental does. v3 uses a pure sinusoid, as lcd1x does, so the
       profile is single-frequency by construction. This is why Beam_Width is gone.

    3. SAMPLING THE PATTERN (now exact)

       A sinusoid averaged over a pixel-wide box is that same sinusoid scaled by
       sinc(f), f in cycles per output pixel. v3 applies that factor exactly, so
       the pattern is correctly band-limited instead of point-sampled, and it
       naturally vanishes at one cycle per pixel. Above Nyquist nothing can be
       represented at all, so the whole effect - modulation *and* its darkening -
       is faded out there, which also means no uniform dimming is ever left behind
       once the pattern is gone.

       This replaces v2's hand-tuned smoothstep thresholds, so Scanline_Min is
       gone too. Scanlines are at full strength above ~2.9 output pixels per
       source line and silent at or below 2.0; the mask is full above 3 output
       pixels per triad and silent at or below 2.

       That makes v3 inert at low target resolutions - at 640x480 a 240p source
       gives exactly 2 output pixels per line and nothing renders at all. Use
       crt-perfect-v4.glsl there; it is identical to v3 wherever v3 works.

    OTHER LIMITS

      - Requires fragment highp (all GLES 3.x targets provide it). The scanline
        and mask phases reach several hundred before fract(), which mediump cannot
        represent.
      - The four-tap area average is an upscaler: it assumes an output pixel
        footprint spans at most two source texels per axis, so it does not
        correctly downsample a source larger than the on-screen rect. (Same
        limitation as the stock pixellate.glsl it derives from.)
      - Blending in gamma space makes edge midpoints slightly darker than
        physically correct. Across a one-pixel transition this is not visible, and
        it is what most retro scalers do.

*/

#pragma parameter Scanlines  "Scanline visibility"     0.55 0.00 1.00 0.05
#pragma parameter RGB_Mask   "RGB mask visibility"     0.40 0.00 1.00 0.05
#pragma parameter Mask_Type  "Mask 0off 1grille 2slot" 1.00 0.00 2.00 1.00
#pragma parameter Mask_Size  "Mask triads per pixel"   1.00 0.25 2.00 0.25
#pragma parameter Brightness "Brightness"              1.25 0.50 2.00 0.05

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
uniform COMPAT_PRECISION float Scanlines;
uniform COMPAT_PRECISION float RGB_Mask;
uniform COMPAT_PRECISION float Mask_Type;
uniform COMPAT_PRECISION float Mask_Size;
uniform COMPAT_PRECISION float Brightness;
#else
#define Scanlines 0.55
#define RGB_Mask 0.40
#define Mask_Type 1.0
#define Mask_Size 1.0
#define Brightness 1.25
#endif

// Exact average of a unit-amplitude sinusoid of frequency f (cycles per output
// pixel) over one pixel-wide box. Zero at one cycle per pixel.
float boxSinc(float f)
{
    float x = PI * max(f, 1e-4);
    return sin(x) / x;
}

// Nothing above Nyquist can be represented, so fade the effect out entirely
// there - amplitude and darkening together, so no uniform dimming is left behind.
float nyquistFade(float f)
{
    return 1.0 - smoothstep(0.34, 0.5, f);
}

void main()
{
    vec2 texelSize = SourceSize.zw;

    // ------------------------------------------------------------------
    // Area-averaged upscale straight to the output size, in GAMMA SPACE.
    // Each output pixel integrates the source over its own footprint, so source
    // pixels come out as uniform blocks with a single soft pixel wherever a
    // block boundary falls between two output pixels. Integer scale factors stay
    // exact. Blending in the encoded domain is what keeps the partial-coverage
    // pixels free of the coverage-dependent shift that caused v2's moire.
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

    // separable weights: the footprint is a rectangle, so the four corner areas
    // factor into one horizontal and one vertical term
    float wLeft = (border.x - left) / (2.0 * range.x);
    float wTop  = (top - border.y)  / (2.0 * range.y);

    vec3 color = mix(mix(bottomRight, bottomLeft, wLeft),
                     mix(topRight,    topLeft,    wLeft), wTop);

    // ------------------------------------------------------------------
    // Scanlines: one cycle per source line, so the count is the source vertical
    // resolution automatically. Pure sinusoid, split into its mean and its
    // amplitude so the amplitude alone can carry the sinc box filter while the
    // Nyquist fade scales both together.
    //
    //   scan(p) = (1 - A/2) - (A/2) * sinc(f) * cos(2*pi*p)
    // ------------------------------------------------------------------
    float scanFreq = InputSize.y / max(OutputSize.y, 1.0);   // cycles per output pixel
    float scanAmp  = Scanlines * nyquistFade(scanFreq);

    float scan = 1.0;
    if (scanAmp > 0.0) {
        float p = fract(vTexCoord.y * InputSize.y);
        scan = (1.0 - 0.5 * scanAmp)
             - 0.5 * scanAmp * boxSinc(scanFreq) * cos(TAU * p);
    }

    // ------------------------------------------------------------------
    // RGB mask, locked to the source pixel grid. Three primaries 120 degrees
    // apart, so the mask is luma neutral and casts no colour - which also lets
    // blue be derived from red and green instead of costing a third cosine.
    // The -1/6 offset centres the triad on the source pixel: red at 1/6, green
    // at 1/2, blue at 5/6 across it.
    // ------------------------------------------------------------------
    float maskFreq = (InputSize.x * Mask_Size) / max(OutputSize.x, 1.0);
    float maskAmp  = RGB_Mask * nyquistFade(maskFreq);

    vec3 mask = vec3(1.0);
    if (maskAmp > 0.0 && Mask_Type >= 0.5) {
        float phase = vTexCoord.x * InputSize.x * Mask_Size - (1.0 / 6.0);

        // offset grille: stagger the triads by half a cell on alternate source
        // rows. The vertical separation of a real slot mask comes from the
        // scanlines, so this reads as slots only with Scanlines > 0.
        if (Mask_Type >= 1.5) {
            phase += 0.5 * mod(floor(vTexCoord.y * InputSize.y), 2.0);
        }

        float dc = 1.0 - 0.5 * maskAmp;
        float ac = 0.5 * maskAmp * boxSinc(maskFreq);
        mask.rg = dc + ac * cos(TAU * (fract(phase) - vec2(0.0, 1.0 / 3.0)));
        mask.b  = 3.0 * dc - mask.r - mask.g;
    }

    // ------------------------------------------------------------------
    // Modulate. The source is still gamma encoded, and the gamma is 2.0, so
    // sqrt(linear * m) == encoded * sqrt(m): one square root replaces the whole
    // decode/modulate/encode round trip, and stays physically correct.
    // ------------------------------------------------------------------
    vec3 gain = sqrt(mask * (scan * Brightness));

    FragColor = vec4(clamp(color * gain, 0.0, 1.0), 1.0);
}

#endif
