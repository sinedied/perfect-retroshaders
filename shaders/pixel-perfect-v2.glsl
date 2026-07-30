// pixel-perfect-v2 - uniform pixel blocks and a gamma, at minimal cost.
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
//   pp_sharpness  0.20 - 1.00  Transition width between blocks, in output
//                              pixels. Lower is crisper.
//   pp_gamma      0.50 - 2.00  Output gamma. Below 1 brightens. 1.00 is off.
// -----------------------------------------------------------------------------
// Scales an image so every source pixel becomes an even block, with a single
// soft pixel wherever a block boundary falls between two output pixels. Integer
// scale factors come out exact. Nearest-neighbour would instead give blocks of
// uneven width that crawl as the image scrolls, and a plain bilinear filter
// would avoid that but blur everything. Each output pixel is the average of the
// source over its own footprint, which spans at most two texels per axis, so
// four taps with separable weights evaluate it exactly.
//
// pp_gamma is applied to the blended colour rather than to the four taps. That
// is four times cheaper - one pow instead of four - and on a scaler it is free
// in practice, because the transcendental hides behind the texture fetches.
//
// The two placements are not identical: the blend is linear, a gamma is not, so
// partial-coverage pixels come out slightly different. Measured on a 1px dither
// pattern the difference is about 4 levels at periods of 8 to 16 pixels, and on
// real frames it is 0.4 levels, confined to sprite edges. Neither placement
// produces any long-period structure at all. The cheaper one is used because
// the difference does not justify the cost, but the taps are where a shader
// that also multiplies by a pattern would have to apply it - see crt-perfect,
// where a post-blend gamma modulates the pattern's own amplitude.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.

#pragma parameter pp_sharpness "Transition width in px" 1.00 0.20 1.00 0.05
#pragma parameter pp_gamma     "Gamma"                  1.00 0.50 2.00 0.05

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
uniform COMPAT_PRECISION float pp_sharpness;
uniform COMPAT_PRECISION float pp_gamma;
#else
#define pp_sharpness 1.0
#define pp_gamma 1.0
#endif

void main()
{
    // Work in source texels: p is this output pixel's centre, h its half-footprint.
    // The max() matters: a host that does not set the uniform leaves it at 0, and h
    // is a divisor below, so without it every pixel would come out NaN.
    vec2 p = TEX0.xy * TextureSize;
    vec2 h = max(0.4995 * pp_sharpness * InputSize / OutputSize, 1e-6);

    // B is the texel boundary nearest the footprint. w is the share of the
    // footprint lying on B's low side, and clamps to exactly 0 or 1 whenever the
    // footprint sits wholly inside one texel - which is most output pixels, and is
    // what keeps the blocks flat instead of gradients.
    vec2 B = floor(p + 0.5);
    vec2 w = clamp((B - p + h) / (2.0 * h), 0.0, 1.0);

    // The two texel centres straddling B, on each axis.
    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;

    vec3 a = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 b = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 c = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 d = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    // Separable weights. Note mix(x, y, w) returns y at w == 1, so the low-side
    // value has to be the second argument on both axes.
    vec3 col = mix(mix(d, c, w.x), mix(b, a, w.x), w.y);

    // The branch is uniform across the draw, so a gamma of 1 costs nothing. The
    // base is clamped because pow(0, g) is undefined and returns NaN on real
    // drivers, and black texels are everywhere; 1e-8 is small enough that pure
    // black still encodes to 0 even at the lowest gamma, where 1e-5 would lift
    // it to 1/255.
    if (abs(pp_gamma - 1.0) > 0.001) {
        col = pow(max(col, 1e-8), vec3(pp_gamma));
    }

    FragColor = vec4(col, 1.0);
}

#endif
