/*
    crt-perfect-v4 - moire-free CRT scanlines and RGB mask with pixel-perfect
    scaling, down to a 640x480 target.

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

    v4 of crt-perfect.glsl. Identical to v3 wherever there are enough output
    pixels per source line; adds a minimum pitch so the effect still works at low
    target resolutions, where v3 rendered nothing at all. v1-v3 remain available.

    REQUIRED PASS SETTINGS  (Shader > Shader 1 in the in-game menu)

        minarch_nrofshaders       = 1
        minarch_shader1           = crt-perfect-v4.glsl
        minarch_shader1_filter    = NEAREST
        minarch_shader1_srctype   = source
        minarch_shader1_scaletype = source
        minarch_shader1_upscale   = screen      <-- important
        minarch_scale_filter      = NEAREST

    "upscale = screen" makes this pass render at exactly the final on-screen size,
    so one output pixel is one device pixel. Any other upscale value resamples the
    result a second time and both the mask and the scanlines will alias.

    PARAMETERS

        Scanlines    visibility of the scanlines, 0 turns them off
        RGB_Mask     visibility of the RGB mask, 0 turns it off
        Mask_Type    0 = off, 1 = aperture grille, 2 = offset (slot) grille
        Mask_Size    triads per source pixel (1.0 = one RGB triad per pixel)
        Brightness   gain applied at the end, compensates the darkening
        Min_Pitch    smallest pattern pitch, in output pixels (see below)

    Above Min_Pitch the scanline count is the source vertical resolution: 224p
    content gets 224 scanlines, no configuration needed.

    MIN_PITCH - MAKING IT WORK AT LOW TARGET RESOLUTIONS

    At 640x480 a 240p source gives only two output pixels per source line, and two
    per triad. v3 faded both effects out completely there and rendered nothing.

    v4 runs the pattern at

        pitch = max(sourcePitch, Min_Pitch)          (in output pixels)

    which produces two regimes:

      - SOURCE-LOCKED, pitch == sourcePitch. Identical to v3 in every respect:
        continuous sinusoid at the source pitch, sinc prefiltered, faded out near
        Nyquist. This covers every 1024x768 and 1280x720 case.

      - GRID-LOCKED, pitch == Min_Pitch. The pattern is placed in output space and
        phase-aligned to the pixel grid. Because it then repeats exactly every few
        pixels it cannot beat, so the sinc prefilter and the Nyquist fade are
        skipped - they exist only to prevent aliasing, and applying them here would
        needlessly flatten the pattern.

    The switch between the two is a narrow smoothstep over 1.001 to 1.02 x Min_Pitch
    rather than a comparison. Do not "simplify" it back to a step(): GPUs evaluate
    a/b as a*rcp(b), so a source pitch that is mathematically equal to Min_Pitch can
    land a few ULP either side of it, and the two regimes differ in contrast by
    about 30%. The window is biased so equality is fully grid-locked, and is still
    ~100x wider than the float error.

    The reference overlays this was matched against work exactly this way: at their
    native 640x480 they use a fixed 3.00 px pitch (160 scanlines, 213 triads) and a
    2.67 px pitch respectively, regardless of whether the content was 224p or 240p.

    Useful settings at 640x480:

        Min_Pitch 3.00   the reference "crt" look, 160 lines / 213 triads
        Min_Pitch 2.50   finer and punchier, close to the reference "240p" look
        Min_Pitch 2.00   classic doubled-240p scanline, one line on, one off

    2.00 only produces that classic look when the vertical scale is exactly 2, i.e.
    a 240p source at 640x480. A 224p source there scales by 2.14, which stays
    source-locked and is faded out for being too close to Nyquist - use 2.50 or 3.00
    for mixed content. Note also that 2.00 leaves everything unclamped at 1024x768
    and 1280x720, so it doubles as a way to get exactly v3's behaviour back.

    Every 0.25 step repeats exactly over a whole number of output pixels (a pitch of
    k/4 repeats every k pixels), so no setting can produce a beat.

    WHY 2.00 WORKS HERE BUT NOT IN v3

    v3 sampled the profile at (i + 0.5) / pitch. At a pitch of 2 that gives phases
    0.25 and 0.75, which sit symmetrically about the beam peak and return identical
    values - the pattern vanished. v4 shifts by half an output pixel when
    grid-locked, to i / pitch, so one sample per cycle lands exactly on the trough.
    That rescues every even-integer pitch, not just 2:

        pitch   2.00   2.67   3.00   4.00   6.00
        v3      0.000  0.924  0.750  0.707  0.866     (contrast)
        v4      1.000  1.000  0.750  1.000  1.000

    CAVEAT AT MIN_PITCH 2.00

    Two pixels cannot carry three primaries, so at a 2.00 px triad the mask
    degenerates into alternating red/cyan columns rather than RGB triads. The
    scanlines are perfect there. If the RGB mask matters at 640x480, use 2.50 or
    above. Both patterns share one Min_Pitch rather than adding a seventh parameter.

    OTHER LIMITS

      - Requires fragment highp (all GLES 3.x targets provide it).
      - The four-tap area average is an upscaler: it assumes an output pixel
        footprint spans at most two source texels per axis, so it does not
        correctly downsample a source larger than the on-screen rect. (Same
        limitation as the stock pixellate.glsl it derives from.)
      - Blending happens in gamma space, which makes edge midpoints slightly darker
        than physically correct. Across a one-pixel transition this is not visible,
        and it is what removes the dominant source of moire - see v3's header.

*/

#pragma parameter Scanlines  "Scanline visibility"     0.55 0.00 1.00 0.05
#pragma parameter RGB_Mask   "RGB mask visibility"     0.40 0.00 1.00 0.05
#pragma parameter Mask_Type  "Mask 0=off 1=grille 2=slot" 1.00 0.00 2.00 1.00
#pragma parameter Mask_Size  "Mask triads per pixel"   1.00 0.25 2.00 0.25
#pragma parameter Brightness "Brightness"              1.25 0.50 4.00 0.05
#pragma parameter Min_Pitch  "Min. pitch in px"        3.00 2.00 6.00 0.25

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
uniform COMPAT_PRECISION float Min_Pitch;
#else
#define Scanlines 0.55
#define RGB_Mask 0.40
#define Mask_Type 1.0
#define Mask_Size 1.0
#define Brightness 1.25
#define Min_Pitch 3.0
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
    // Blending in the encoded domain is what keeps partial-coverage pixels free
    // of the coverage-dependent shift that caused the moire before v3.
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

    float wLeft = (border.x - left) / (2.0 * range.x);
    float wTop  = (top - border.y)  / (2.0 * range.y);

    vec3 color = mix(mix(bottomRight, bottomLeft, wLeft),
                     mix(topRight,    topLeft,    wLeft), wTop);

    // ------------------------------------------------------------------
    // Scanlines. One cycle per source line while there is room for it; below
    // Min_Pitch output pixels per line the pattern switches to output space at
    // exactly Min_Pitch, phase-aligned to the pixel grid.
    //
    // Grid-locked patterns repeat exactly over a whole number of pixels, so they
    // cannot alias and neither the sinc prefilter nor the Nyquist fade applies.
    // The half-pixel shift puts one sample per cycle on the trough, which is what
    // makes a 2.00 px pitch resolve at full contrast instead of vanishing.
    // ------------------------------------------------------------------
    float scanSrcPitch = OutputSize.y / max(InputSize.y, 1.0);
    float scanPitch    = max(scanSrcPitch, Min_Pitch);
    // Blend between the regimes rather than switching on an exact comparison:
    // GPUs evaluate a/b as a*rcp(b), so scanSrcPitch can land a few ULP either
    // side of Min_Pitch and a hard step() would flip contrast by ~30%.
    float scanLocked   = 1.0 - smoothstep(Min_Pitch * 1.001, Min_Pitch * 1.02, scanSrcPitch);
    float scanFreq     = 1.0 / scanPitch;

    float scanAmp = Scanlines * mix(nyquistFade(scanFreq), 1.0, scanLocked);
    float scanAC  = 0.5 * scanAmp * mix(boxSinc(scanFreq), 1.0, scanLocked);

    float scan = 1.0;
    if (scanAmp > 0.0) {
        float y = vTexCoord.y * OutputSize.y - 0.5 * scanLocked;
        // fract() keeps the cosine argument small; the phase can reach several
        // hundred cycles before it, which costs precision otherwise
        scan = (1.0 - 0.5 * scanAmp) - scanAC * cos(TAU * fract(y * scanFreq));
    }

    // ------------------------------------------------------------------
    // RGB mask, same two regimes. Three primaries 120 degrees apart, so the mask
    // is luma neutral and casts no colour - which also lets blue be derived from
    // red and green instead of costing a third cosine. The -1/6 offset centres
    // the triad on its cell: red at 1/6, green at 1/2, blue at 5/6 across it.
    // ------------------------------------------------------------------
    float maskSrcPitch = OutputSize.x / max(InputSize.x * Mask_Size, 1.0);
    float maskPitch    = max(maskSrcPitch, Min_Pitch);
    float maskLocked   = 1.0 - smoothstep(Min_Pitch * 1.001, Min_Pitch * 1.02, maskSrcPitch);
    float maskFreq     = 1.0 / maskPitch;

    float maskAmp = RGB_Mask * mix(nyquistFade(maskFreq), 1.0, maskLocked);

    vec3 mask = vec3(1.0);
    if (maskAmp > 0.0 && Mask_Type >= 0.5) {
        float x = vTexCoord.x * OutputSize.x - 0.5 * maskLocked;
        float phase = x * maskFreq - (1.0 / 6.0);

        // offset grille: stagger the triads by half a cell on alternate lines of
        // the scanline grid. The epsilon keeps floor() off its exact boundary -
        // the argument passes through whole numbers once per line, and without it
        // a few ULP of difference flips a whole row's stagger.
        if (Mask_Type >= 1.5) {
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
    // Modulate. The source is still gamma encoded and the gamma is 2.0, so
    // sqrt(linear * m) == encoded * sqrt(m): one square root replaces the whole
    // decode/modulate/encode round trip, and stays physically correct.
    // ------------------------------------------------------------------
    vec3 gain = sqrt(max(mask * (scan * Brightness), 0.0));

    FragColor = vec4(clamp(color * gain, 0.0, 1.0), 1.0);
}

#endif
