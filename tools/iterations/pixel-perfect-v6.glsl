// pixel-perfect v6 - uniform pixel blocks and a colour grade, at minimal cost.
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
//   pp_brightness    0.50 - 2.00  Output gain. Above 1 clips highlights.
//   pp_contrast      0.00 - 2.00  Contrast about mid grey. 1.00 is off.
//   pp_saturation    0.00 - 2.00  Colour intensity. 0 is grey. 1.00 is off.
//   pp_gamma         0.50 - 2.00  Output gamma. Below 1 brightens. 1.00 is off.
//   pp_temperature  -1.00 - 1.00  Warm above 0, cool below. 0.00 is off.
//   pp_tint         -1.00 - 1.00  Green above 0, magenta below. 0.00 is off.
// -----------------------------------------------------------------------------
// Scales an image so every source pixel becomes an even block, with a single
// soft pixel wherever a block boundary falls between two output pixels. Integer
// scale factors come out exact. Each output pixel is the average of the source
// over its own footprint, which spans at most two texels per axis, so four taps
// with separable weights evaluate it exactly. On top of that sits a grade for
// tuning the image to taste: gain, contrast about mid grey, saturation toward
// luma, a white balance, then gamma. Every control is off at its default, and
// the whole grade sits behind one uniform test, so a grade left alone costs
// nothing at all rather than merely doing nothing.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - Brightness, contrast, saturation and the balance pair are all affine, so
//   they commute with the scaler's blend and paint no pattern of their own.
//   What costs is clipping, once a control is pushed past the range the
//   display can show.
// - pp_temperature and pp_tint are the two axes of a white balance, for panels
//   that are not neutral. Useful trims are small, roughly within 0.20; the rest
//   of the range is there for effect. They shift the overall level a little as
//   well as the colour, which pp_brightness can take back out.
// - pp_gamma is the one control that is non-linear after the blend, and much
//   the most expensive: on dense content it paints moire where the others do
//   not. Reach for it last.

#pragma parameter pp_brightness  "Brightness gain, clips"   1.00  0.50 2.00 0.05
#pragma parameter pp_contrast    "Contrast, about mid grey" 1.00  0.00 2.00 0.05
#pragma parameter pp_saturation  "Colour saturation"        1.00  0.00 2.00 0.05
#pragma parameter pp_gamma       "Gamma, below 1 brightens" 1.00  0.50 2.00 0.05
#pragma parameter pp_temperature "Warm / cool balance"      0.00 -1.00 1.00 0.01
#pragma parameter pp_tint        "Green / magenta balance"  0.00 -1.00 1.00 0.01

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

// Rec.709 luma, for the saturation mix. Applied to encoded values, not linear
// light: the round trip that would need is the construction the scaler exists
// to avoid.
const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

void main()
{
    // Source texels: p is this pixel's centre, h its half footprint. The max()
    // guards an unset InputSize, which is 0 and would make every pixel NaN.
    // There is no sharpness control on purpose: narrowing the footprint below
    // one output pixel is nearest-neighbour again, which is what crawls.
    vec2 p = TEX0.xy * TextureSize;
    vec2 h = max(0.4995 * InputSize / OutputSize, 1e-6);

    // B is the nearest texel boundary; w is the share of the footprint on its
    // low side. Clamps to exactly 0 or 1 wherever the footprint sits inside one
    // texel, which is most pixels - that is what keeps the blocks flat.
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

    // Brightness, contrast and saturation fold into one affine map, using the
    // fact that LUMA sums to 1. Folded, not three steps: that makes it exactly
    // col*1.0 + 0.0 at the defaults, where the literal chain rounds. Do not
    // un-fold it. Affine is also what makes grading safe after the blend - the
    // weights sum to 1, so it cannot give partial-coverage pixels the shift
    // that beats against the pixel grid.
    //
    // The balance stays a separate multiply after the saturation mix: folding
    // it in widens the luma term to vec3 and measures 4 instructions worse,
    // and dot(col*t, LUMA) is not t*dot(col, LUMA) anyway.
    //
    // Tested separately, not summed, or a warm temperature could cancel a cool
    // tint. Exact rather than an epsilon: every control is a true no-op at its
    // default.
    if (pp_brightness != 1.0 || pp_contrast != 1.0 || pp_saturation != 1.0
        || pp_temperature != 0.0 || pp_tint != 0.0) {
        float ga = pp_brightness * pp_contrast;
        float gb = 0.5 - 0.5 * pp_contrast;
        col = col * (ga * pp_saturation)
            + (dot(col, LUMA) * (ga * (1.0 - pp_saturation)) + gb);

        // Two chromatic axes: warm/cool trades red against blue, tint trades
        // green against both. Not normalised on luma, so these shift the level
        // a little as well as the colour.
        col *= 1.0 + pp_temperature * vec3(1.0, 0.0, -1.0)
                   + pp_tint        * vec3(-0.5, 1.0, -0.5);

        // Inside the guard because only a grade can leave 0 to 1: the scaler's
        // own output is a convex blend of taps already in range. It is also
        // what makes a balance safe to push negative.
        col = clamp(col, 0.0, 1.0);
    }

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
