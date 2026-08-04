// unflat-mini v1 - barrel distortion and a tube edge, behind any scaler.
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
//   um_curvature   0.00 - 0.30  Screen curvature. 0 disables it.
//   um_corner      0.00 - 4.00  Corner softness, in output pixels.
// -----------------------------------------------------------------------------
// Bends the picture like the glass of a tube TV, with rounded corners. Nothing
// is cropped: the edges of the image stay on the edges of the screen and only
// the corners curve away.
//
// Notes:
// - Needs a LINEAR filter, set in the preset. Under NEAREST the bend has
//   nothing to interpolate and the whole picture goes ragged.
// - Draws no pattern of its own. Put it after a shader that does - crt-mini is
//   the matching one - or use it alone to bend a plain upscale.
// - Render at the output resolution, 1:1 with the display.
// - It resamples whatever it is given, so a pattern drawn by an earlier pass is
//   softened by the bend. Curvature built into a single-pass shader avoids
//   that; this is the price of composing.

#pragma parameter um_curvature "Screen curvature"  0.00 0.00 0.30 0.01
#pragma parameter um_corner    "Corner softness"   1.00 0.00 4.00 0.25

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

#ifdef PARAMETER_UNIFORM
uniform COMPAT_PRECISION float um_curvature;
uniform COMPAT_PRECISION float um_corner;
#else
#define um_curvature 0.00
#define um_corner 1.00
#endif

void main()
{
    // The warp is c * (1 + k*r2); the divisor is the whole design decision.
    // (1 + k) is the edge-midpoint value, so an image edge lands exactly on the
    // screen edge and nothing is ever cropped, while the corners fall outside
    // the image and become the tube's rounded corners. The corner value
    // (1 + 2k) instead crops the entire border and reads as a lens bump; no
    // divisor at all leaves black on all four sides. Both axes use the same
    // constant, so it is symmetric at any aspect ratio.
    vec2  uv   = vTexCoord;
    float tube = 1.0;

    if (um_curvature > 0.0) {
        float norm = 1.0 / (1.0 + um_curvature);
        vec2  c    = uv * 2.0 - 1.0;
        vec2  cc   = c * c;
        float r2   = cc.x + cc.y;

        uv = c * (1.0 + um_curvature * r2) * norm * 0.5 + 0.5;

        // The corners reach past the image and must be masked: the sampler
        // clamps to edge, which would stretch the border texel across the
        // whole corner.
        vec2 e  = max(um_corner, 1e-4) / OutputSize;
        vec2 aa = clamp(uv / e, 0.0, 1.0) * clamp((1.0 - uv) / e, 0.0, 1.0);
        tube = aa.x * aa.y;
    }

    vec3 color = COMPAT_TEXTURE(Source, uv).rgb;

    FragColor = vec4(clamp(color * tube, 0.0, 1.0), 1.0);
}


#endif
