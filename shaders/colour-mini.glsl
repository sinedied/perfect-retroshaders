// colour-mini v3 - colour controls only, to sit behind any scaler.
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
//   pp_brightness    0.50 - 2.00  Midtone lift. 1.00 disables it.
//   pp_contrast      0.00 - 2.00  Contrast. 1.00 disables it.
//   pp_saturation    0.00 - 2.00  Colour intensity. 1.00 disables it.
//   pp_gamma         0.50 - 2.00  Output gamma. 1.00 disables it.
//   pp_temperature  -1.00 - 1.00  Warm above 0, cool below. 0.00 is off.
//   pp_tint         -1.00 - 1.00  Green above 0, magenta below. 0.00 is off.
// -----------------------------------------------------------------------------
// Brightness, contrast, saturation, gamma and white balance, and nothing
// else. Drops in behind whatever scaler you like - or in front of nothing at
// all - so you can tune a picture to a screen without paying for effects you
// do not want.
//
// Notes:
// - Needs a LINEAR filter, set in the preset. Under NEAREST every tap stops
//   interpolating: the pattern still draws, so nothing looks broken, but the
//   picture underneath it is nearest-neighbour.
// - Draws no pattern and does no scaling: it passes the picture through
//   untouched at its default settings.
// - Put a scaler in front of it for sharp pixel blocks. On its own it is a
//   plain smooth upscale.
// - Brightness above 1.00 clips, and a clip beats against the pixel grid unless
//   the output is a whole multiple of the source. Off an integer scale, prefer
//   gamma.

#pragma parameter pp_brightness  "Brightness"               1.00  0.50 2.00 0.05
#pragma parameter pp_contrast    "Contrast"                 1.00  0.00 2.00 0.05
#pragma parameter pp_saturation  "Saturation"               1.00  0.00 2.00 0.05
#pragma parameter pp_gamma       "Gamma"                    1.00  0.50 2.00 0.05
#pragma parameter pp_temperature "Cool / warm balance"      0.00 -1.00 1.00 0.01
#pragma parameter pp_tint        "Magenta / green balance"  0.00 -1.00 1.00 0.01

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
uniform COMPAT_PRECISION float pp_brightness;
uniform COMPAT_PRECISION float pp_contrast;
uniform COMPAT_PRECISION float pp_saturation;
uniform COMPAT_PRECISION float pp_gamma;
uniform COMPAT_PRECISION float pp_temperature;
uniform COMPAT_PRECISION float pp_tint;
#else
#define pp_brightness 1.0
#define pp_contrast 1.0
#define pp_saturation 1.0
#define pp_gamma 1.0
#define pp_temperature 0.0
#define pp_tint 0.0
#endif

// Rec.709 luma, for the saturation mix. Applied to encoded values: the round
// trip to linear is the construction the scaler exists to avoid.
const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

void main()
{
    // Straight through. Behind a scaler this is 1:1 and exact; in front of
    // nothing it is the sampler's own upscale. TextureSize is deliberately not
    // used - a later pass is handed the ORIGINAL source size in it, not the
    // size of the texture it is sampling.
    vec3 col = COMPAT_TEXTURE(Texture, TEX0.xy).rgb;

    // The balance goes first, so saturation sees the tinted colour and 0 really
    // is monochrome. Applied last it would put colour back into an image
    // saturation had just flattened. It is a separate multiply either way,
    // since dot(col*t, LUMA) is not t*dot(col, LUMA).
    //
    // Brightness, contrast and saturation then fold into one affine map, using
    // the fact that LUMA sums to 1. Folded, not three steps: that makes it
    // exactly col*1.0 + 0.0 at the defaults, where the literal chain rounds. Do
    // not un-fold it. Affine is also what makes grading safe after the blend.
    //
    // Tested separately, not summed, or a warm temperature could cancel a cool
    // tint.
    if (pp_brightness != 1.0 || pp_contrast != 1.0 || pp_saturation != 1.0
        || pp_temperature != 0.0 || pp_tint != 0.0) {
        // Warm/cool trades red against blue, tint trades green against both.
        // Not luma-normalised, so they shift the level a little too.
        col *= 1.0 + pp_temperature * vec3(1.0, 0.0, -1.0)
                   + pp_tint        * vec3(-0.5, 1.0, -0.5);

        float ga = pp_brightness * pp_contrast;
        float gb = 0.5 - 0.5 * pp_contrast;
        col = col * (ga * pp_saturation)
            + (dot(col, LUMA) * (ga * (1.0 - pp_saturation)) + gb);
    }

    // The branch is uniform across the draw, so a gamma of 1 costs nothing. The
    // base is clamped because pow(0, g) is undefined and returns NaN on real
    // drivers, and black texels are everywhere; 1e-8 is small enough that pure
    // black still encodes to 0 even at the lowest gamma, where 1e-5 would lift
    // it to 1/255.
    if (abs(pp_gamma - 1.0) > 0.001) {
        col = pow(max(col, 1e-8), vec3(pp_gamma));
    }

    // Last, always: a grade or a gamma can leave 0 to 1, the blend cannot.
    FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}

#endif
