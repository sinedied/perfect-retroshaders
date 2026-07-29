/*
    crt-perfect - pixel-perfect scaling with CRT scanlines and an RGB subpixel mask.

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

    Does the whole CRT chain in a single pass: area-averaged upscale straight to
    the final on-screen size, horizontal scanlines whose count follows the source
    vertical resolution, and a luma-neutral RGB triad mask locked to the source
    pixel grid.

    REQUIRED PASS SETTINGS  (Shader > Shader 1 in the in-game menu)

        minarch_nrofshaders       = 1
        minarch_shader1           = crt-perfect.glsl
        minarch_shader1_filter    = NEAREST
        minarch_shader1_srctype   = source
        minarch_shader1_scaletype = source
        minarch_shader1_upscale   = screen      <-- important
        minarch_scale_filter      = NEAREST

    "upscale = screen" makes this pass render at exactly the final on-screen size,
    so one output pixel is one device pixel and the mask lands on real pixels.
    Any other upscale value resamples the result a second time and both the mask
    and the scanlines will alias.

    PARAMETERS

        Scanlines         visibility of the scanlines, 0 turns them off
        Beam_Width        0.2 = fat dark gap / thin beam, 1.0 = thin dark line
        RGB_Mask          visibility of the RGB mask, 0 turns it off
        Mask_Type         0 = off, 1 = aperture grille, 2 = slot mask
        Mask_Size         triads per source pixel (1.0 = one RGB triad per pixel)
        Brightness        gain applied at the end, compensates the darkening
        Fade_Below_Scale  scanlines fade out below this vertical scale factor

    The scanline count is always the source vertical resolution: 224p content
    gets 224 scanlines, no configuration needed. Both the scanlines and the mask
    fade themselves out when the screen has too few pixels to draw them cleanly
    (below Fade_Below_Scale output pixels per source line, and below 3 output
    pixels per triad respectively), which keeps high-resolution content and small
    windows free of moire instead of turning them into noise.

    Scanlines and mask darken the image, exactly like a real CRT and like the
    overlay images this was matched against. Brightness compensates for that;
    at the default 1.25 the peaks of the beam clip to white, which reads as
    highlight bloom. Lower it to 1.0 for a strictly non-clipping image.

*/

#pragma parameter Scanlines        "Scanline visibility"          0.55 0.00 1.00 0.05
#pragma parameter Beam_Width       "Scanline beam width"          0.65 0.20 1.00 0.05
#pragma parameter RGB_Mask         "RGB mask visibility"          0.35 0.00 1.00 0.05
#pragma parameter Mask_Type        "Mask 0off 1grille 2slot"      1.00 0.00 2.00 1.00
#pragma parameter Mask_Size        "Mask triads per pixel"        1.00 0.25 2.00 0.25
#pragma parameter Brightness       "Brightness"                   1.25 0.50 2.00 0.05
#pragma parameter Fade_Below_Scale "Fade scanlines below scale"   2.00 1.00 4.00 0.50

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

#define TAU 6.283185307

#ifdef PARAMETER_UNIFORM
uniform COMPAT_PRECISION float Scanlines;
uniform COMPAT_PRECISION float Beam_Width;
uniform COMPAT_PRECISION float RGB_Mask;
uniform COMPAT_PRECISION float Mask_Type;
uniform COMPAT_PRECISION float Mask_Size;
uniform COMPAT_PRECISION float Brightness;
uniform COMPAT_PRECISION float Fade_Below_Scale;
#else
#define Scanlines 0.55
#define Beam_Width 0.65
#define RGB_Mask 0.35
#define Mask_Type 1.0
#define Mask_Size 1.0
#define Brightness 1.25
#define Fade_Below_Scale 2.0
#endif

void main()
{
    vec2 texelSize = SourceSize.zw;

    // ------------------------------------------------------------------
    // Area-averaged upscale, straight to the output size. Each output pixel
    // integrates the source over its own footprint, so source pixels come out
    // as uniform blocks with a single soft pixel wherever a block boundary
    // falls between two output pixels. Integer scale factors stay exact.
    // Blending happens in linear light (x*x here, sqrt at the end); it is a
    // gamma of 2.0 rather than 2.2 to keep this off the pow() path, which
    // matters at 1024x768 on a Mali G31.
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

    topLeft     *= topLeft;
    bottomRight *= bottomRight;
    bottomLeft  *= bottomLeft;
    topRight    *= topRight;

    vec2 border = clamp(floor((vTexCoord / texelSize) + vec2(0.5)) * texelSize,
                        vec2(left, bottom), vec2(right, top));

    float totalArea = 4.0 * range.x * range.y;

    vec3 color;
    color  = ((border.x - left)  * (top - border.y)    / totalArea) * topLeft;
    color += ((right - border.x) * (border.y - bottom) / totalArea) * bottomRight;
    color += ((border.x - left)  * (border.y - bottom) / totalArea) * bottomLeft;
    color += ((right - border.x) * (top - border.y)    / totalArea) * topRight;

    // ------------------------------------------------------------------
    // Scanlines. The phase comes from the source row, so the line count is the
    // source vertical resolution automatically. The profile is a raised cosine
    // raised to a power: a single frequency, so it cannot alias no matter how
    // few output pixels a source line covers. exp2() maps Beam_Width onto that
    // exponent, 0.5 -> 1.0 (plain cosine), 1.0 -> 0.25 (thin dark line).
    // ------------------------------------------------------------------
    float vscale = OutputSize.y / max(InputSize.y, 1.0);
    float scanAmount = Scanlines * smoothstep(1.0, max(Fade_Below_Scale, 1.001), vscale);

    if (scanAmount > 0.0) {
        float k = exp2((0.5 - Beam_Width) * 4.0);
        float p = fract(vTexCoord.y * InputSize.y);
        // pow() is undefined for a base of exactly 0, which fract() hits on
        // every source line boundary that lands on an output pixel centre;
        // drivers return NaN there and the line renders black. Keep it positive.
        float base = max(0.5 - 0.5 * cos(TAU * p), 1e-5);
        float beam = pow(base, k);
        color *= mix(1.0, beam, scanAmount);
    }

    // ------------------------------------------------------------------
    // RGB mask, locked to the source pixel grid. Three cosines 120 degrees
    // apart sum to a constant, so the mask costs no brightness balance and
    // introduces no colour cast. The -1/6 offset centres the triad on the
    // source pixel: red at 1/6, green at 1/2, blue at 5/6 across it.
    // ------------------------------------------------------------------
    float triadPixels = OutputSize.x / max(InputSize.x * Mask_Size, 1.0);
    float maskAmount = RGB_Mask * smoothstep(1.5, 3.0, triadPixels);

    if (maskAmount > 0.0 && Mask_Type >= 0.5) {
        float phase = vTexCoord.x * InputSize.x * Mask_Size - (1.0 / 6.0);

        // slot mask: stagger the triads by half a cell on alternate source rows
        if (Mask_Type >= 1.5) {
            phase += 0.5 * mod(floor(vTexCoord.y * InputSize.y), 2.0);
        }

        vec3 mask = 0.5 + 0.5 * cos(TAU * (fract(phase) - vec3(0.0, 1.0 / 3.0, 2.0 / 3.0)));
        color *= mix(vec3(1.0), mask, maskAmount);
    }

    color = clamp(color * Brightness, 0.0, 1.0);

    FragColor = vec4(sqrt(color), 1.0);
}

#endif
