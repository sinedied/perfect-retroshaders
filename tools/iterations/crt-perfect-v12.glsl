// crt-perfect v12 - scanlines, an RGB mask and curvature, pixel-perfect scale.
// -----------------------------------------------------------------------------
// Author:  sinedied
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
//   cp_scanlines   0.00 - 1.00  Scanline visibility. 0 disables them.
//   cp_rgb_mask    0.00 - 1.00  RGB mask visibility. 0 disables it.
//   cp_mask_type   0 / 1 / 2    Off, aperture grille, slot grille.
//   cp_mask_size   0.25 - 2.00  Mask triads per source pixel.
//   cp_min_pitch   2.00 - 6.00  Smallest pattern pitch, in output pixels.
//   cp_curvature   0.00 - 0.15  Screen curvature. 0 disables it.
//   cp_brightness  0.25 - 4.00  Output gain. 1.00 disables it.
//   cp_gamma       0.50 - 2.00  Output gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// A CRT look: soft scanlines and an RGB shadow mask over a clean pixel scale,
// with optional screen curvature. Reads like a small tube TV, sharp rather than
// blurry, and neither pattern beats against the pixel grid at any scale.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - At min. pitch 2.00 the mask becomes 2 colours: use 2.50 or more to keep
//   the triads visible.

#pragma parameter cp_scanlines  "Scanline visibility"        0.60 0.00 1.00 0.05
#pragma parameter cp_rgb_mask   "RGB mask visibility"        0.20 0.00 1.00 0.05
#pragma parameter cp_mask_type  "Mask 0=off 1=grille 2=slot" 1.00 0.00 2.00 1.00
#pragma parameter cp_mask_size  "Mask triads per pixel"      1.00 0.25 2.00 0.25
#pragma parameter cp_min_pitch  "Min. pitch in px"           3.00 2.00 6.00 0.25
#pragma parameter cp_curvature  "Screen curvature"           0.00 0.00 0.15 0.01
#pragma parameter cp_brightness "Brightness"                 1.25 0.25 4.00 0.05
#pragma parameter cp_gamma      "Gamma"                      1.00 0.50 2.00 0.05

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
uniform COMPAT_PRECISION float cp_curvature;
#else
#define cp_scanlines 0.60
#define cp_rgb_mask 0.20
#define cp_mask_type 1.00
#define cp_mask_size 1.00
#define cp_brightness 1.25
#define cp_min_pitch 3.00
#define cp_gamma 1.00
#define cp_curvature 0.00
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

    // Barrel distortion. The warp is c * (1 + k*r2); the divisor is the whole
    // design decision. (1 + k) is the edge-midpoint value, so an image edge
    // lands exactly on the screen edge and nothing is ever cropped, while the
    // corners fall outside the image and become the tube's rounded corners.
    // The corner value (1 + 2k) instead crops the entire border and reads as a
    // lens bump; no divisor at all leaves black on all four sides. Both axes
    // use the same constant, so it is symmetric at any aspect ratio.
    vec2  uv   = vTexCoord;
    vec2  jac  = vec2(1.0);
    float tube = 1.0;
    float noWarp = 1.0;

    if (cp_curvature > 0.0) {
        float norm = 1.0 / (1.0 + cp_curvature);
        vec2  c    = uv * 2.0 - 1.0;
        vec2  cc   = c * c;
        float r2   = cc.x + cc.y;

        uv  = c * (1.0 + cp_curvature * r2) * norm * 0.5 + 0.5;
        jac = (1.0 + cp_curvature * (vec2(3.0, 1.0) * cc.x
                                   + vec2(1.0, 3.0) * cc.y)) * norm;
        noWarp = 0.0;

        // The corners reach past the image and must be masked: the sampler
        // clamps to edge, which would stretch the border texel across the
        // whole corner. Faded over one pixel so the curve does not stair-step.
        vec2 e  = outsize.zw;
        vec2 aa = smoothstep(vec2(0.0), e, uv) * smoothstep(vec2(0.0), e, 1.0 - uv);
        tube = aa.x * aa.y;
    }

    vec2 range = vec2(abs(InputSize.x / (outsize.x * SourceSize.x)),
                      abs(InputSize.y / (outsize.y * SourceSize.y)));
    range = range / 2.0 * 0.999 * jac;

    float left   = uv.x - range.x;
    float top    = uv.y + range.y;
    float right  = uv.x + range.x;
    float bottom = uv.y - range.y;

    // Brightness is applied HERE, per tap, and clamped here too. Applied after
    // the blend it multiplies the scanlines and mask as well, and the clamp
    // that follows is then a non-linearity past the blend: at a non-integer
    // scale it shifts partial-coverage pixels by an amount that depends on
    // their coverage and beats. Per tap the clamp is per SOURCE pixel, so it
    // cannot vary with coverage. See docs/crt-perfect.md.
    //
    // The exponent carries brightness through both the encoding and the gamma
    // below. Its argument is uniform-only, so the driver hoists it.
    float sb = pow(max(cp_brightness, 1e-4), 0.5 / max(cp_gamma, 1e-3));
    vec3 topLeft     = COMPAT_TEXTURE(Source, (floor(vec2(left,  top)    / texelSize) + 0.5) * texelSize).rgb;
    vec3 bottomRight = COMPAT_TEXTURE(Source, (floor(vec2(right, bottom) / texelSize) + 0.5) * texelSize).rgb;
    vec3 bottomLeft  = COMPAT_TEXTURE(Source, (floor(vec2(left,  bottom) / texelSize) + 0.5) * texelSize).rgb;
    vec3 topRight    = COMPAT_TEXTURE(Source, (floor(vec2(right, top)    / texelSize) + 0.5) * texelSize).rgb;
    topLeft     = min(topLeft     * sb, 1.0);
    bottomRight = min(bottomRight * sb, 1.0);
    bottomLeft  = min(bottomLeft  * sb, 1.0);
    topRight    = min(topRight    * sb, 1.0);

    vec2 border = clamp(floor((uv / texelSize) + vec2(0.5)) * texelSize,
                        vec2(left, bottom), vec2(right, top));

    float wLeft = (border.x - left) / (2.0 * range.x);
    float wTop  = (top - border.y)  / (2.0 * range.y);

    vec3 color = mix(mix(bottomRight, bottomLeft, wLeft),
                     mix(topRight,    topLeft,    wLeft), wTop);

    if (abs(cp_gamma - 1.0) > 0.001) {
        color = pow(max(color, 1e-8), vec3(cp_gamma));
    }

    // Positioned in tube space, so the patterns curve with the glass. Their
    // pitch is the flat one - see the note below the floor.
    float scanSrcPitch = OutputSize.y / max(InputSize.y, 1.0);
    float scanPitch    = max(scanSrcPitch, cp_min_pitch);
    float scanLocked   = (1.0 - smoothstep(cp_min_pitch * 1.001, cp_min_pitch * 1.02, scanSrcPitch)) * noWarp;
    float scanFreq     = 1.0 / scanPitch;

    // Pitch and band-limit are computed as though the screen were flat, on two
    // counts. It keeps the pattern locked to the source - one cycle per source
    // line - which is what makes scanlines read as scanlines; scaling the pitch
    // by the frame's worst magnification turned 240 source lines into 201. And
    // it keeps the argument uniform, so the driver hoists boxSinc's sin and
    // nyquistFade's smoothstep out of the fragment shader. Making it vary per
    // pixel cost 16.5 points of frame time, paid even with curvature off.
    //
    // The magnified corners therefore run slightly stronger than their true box
    // average. Still above two output pixels per cycle at every setting, so it
    // is over-contrast rather than aliasing - and curvature is a distortion by
    // construction. See docs/crt-perfect.md.
    float scanLocal    = scanFreq;

    float scanAmp = cp_scanlines * mix(nyquistFade(scanLocal), 1.0, scanLocked);
    float scanAC  = 0.5 * scanAmp * mix(boxSinc(scanLocal), 1.0, scanLocked);

    float scan = 1.0;
    if (scanAmp > 0.0) {
        float y = uv.y * OutputSize.y - 0.5 * scanLocked;
        scan = (1.0 - 0.5 * scanAmp) - scanAC * cos(TAU * fract(y * scanFreq));
    }

    float maskSrcPitch = OutputSize.x / max(InputSize.x * cp_mask_size, 1.0);
    float maskPitch    = max(maskSrcPitch, cp_min_pitch);
    float maskLocked   = (1.0 - smoothstep(cp_min_pitch * 1.001, cp_min_pitch * 1.02, maskSrcPitch)) * noWarp;
    float maskFreq     = 1.0 / maskPitch;
    float maskLocal    = maskFreq;

    float maskAmp = cp_rgb_mask * mix(nyquistFade(maskLocal), 1.0, maskLocked);

    vec3 mask = vec3(1.0);
    if (maskAmp > 0.0 && cp_mask_type >= 0.5) {
        float x = uv.x * OutputSize.x - 0.5 * maskLocked;
        float phase = x * maskFreq - (1.0 / 6.0);

        if (cp_mask_type >= 1.5) {
            float row = floor((uv.y * OutputSize.y - 0.5 * scanLocked) * scanFreq + 1e-3);
            phase += 0.5 * mod(row, 2.0);
        }

        float dc = 1.0 - 0.5 * maskAmp;
        float ac = 0.5 * maskAmp * mix(boxSinc(maskLocal), 1.0, maskLocked);
        mask.rg = dc + ac * cos(TAU * (fract(phase) - vec2(0.0, 1.0 / 3.0)));
        mask.b  = max(3.0 * dc - mask.r - mask.g, 0.0);
    }

    vec3 gain = sqrt(max(mask * scan, 0.0));

    FragColor = vec4(clamp(color * gain * tube, 0.0, 1.0), 1.0);
}

#endif
