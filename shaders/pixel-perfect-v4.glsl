// pixel-perfect-v4 - uniform pixel blocks and a colour grade, at minimal cost.
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
//   pp_saturation  0.00 - 2.00  Colour intensity. 0 is grey. 1.00 is off.
//   pp_contrast    0.00 - 2.00  Contrast about mid grey. 1.00 is off.
//   pp_brightness  0.50 - 2.00  Output gain. Above 1 clips highlights.
//   pp_gamma       0.50 - 2.00  Output gamma. Below 1 brightens. 1.00 is off.
// -----------------------------------------------------------------------------
// Scales an image so every source pixel becomes an even block, with a single
// soft pixel wherever a block boundary falls between two output pixels. Integer
// scale factors come out exact. Each output pixel is the average of the source
// over its own footprint, which spans at most two texels per axis, so four taps
// with separable weights evaluate it exactly. On top of that sits a grade for
// tuning the image to taste: gain, contrast about mid grey, saturation toward
// luma, then gamma. Every control is off at its default, and each half of the
// grade sits behind its own uniform test, so a control left alone costs
// nothing at all rather than merely doing nothing.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - Brightness, contrast and saturation are affine, so they commute with the
//   scaler's blend and paint no pattern of their own. What costs is clipping,
//   once a control is pushed past the range the display can show.
// - pp_gamma is the one control that is non-linear after the blend, and much
//   the most expensive: on dense content it paints moire where the other
//   three do not. Reach for it last.

#pragma parameter pp_saturation "Colour saturation"        1.00 0.00 2.00 0.05
#pragma parameter pp_contrast   "Contrast, about mid grey" 1.00 0.00 2.00 0.05
#pragma parameter pp_brightness "Brightness gain, clips"   1.00 0.50 2.00 0.05
#pragma parameter pp_gamma      "Gamma, below 1 brightens" 1.00 0.50 2.00 0.05

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
uniform COMPAT_PRECISION float pp_saturation;
uniform COMPAT_PRECISION float pp_contrast;
uniform COMPAT_PRECISION float pp_brightness;
uniform COMPAT_PRECISION float pp_gamma;
#else
#define pp_saturation 1.0
#define pp_contrast 1.0
#define pp_brightness 1.0
#define pp_gamma 1.0
#endif

// Rec.709 luma, for the saturation mix. These are applied to encoded values
// rather than to linear light, which is what the rest of the shader works in -
// the alternative would need a linearise/re-encode round trip, and that is the
// exact construction the scaler exists to avoid.
const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

void main()
{
    // Work in source texels: p is this output pixel's centre, h its half-footprint.
    // The max() guards a host that leaves InputSize at 0: h is a divisor below, so
    // without it every pixel would come out NaN - a black screen, not a subtle
    // error. There is no sharpness control: narrowing the footprint below the
    // output pixel turns this back into nearest-neighbour, which is the uneven,
    // crawling result the shader exists to remove.
    vec2 p = TEX0.xy * TextureSize;
    vec2 h = max(0.4995 * InputSize / OutputSize, 1e-6);

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

    // Gain, contrast and saturation compose into a single affine map, because
    // each is affine on its own:
    //
    //   gain      c1 = col * g
    //   contrast  c2 = (c1 - 0.5) * k + 0.5  =  col*(g*k) + 0.5*(1 - k)
    //   satur.    c3 = mix(dot(c2, LUMA), c2, s)
    //
    // and LUMA sums to 1, so dot(c2, LUMA) = dot(col, LUMA)*(g*k) + 0.5*(1 - k)
    // and the whole chain is col*(ga*s) + dot(col, LUMA)*(ga*(1 - s)) + gb. One
    // dot and one fma, and at the defaults exactly col*1.0 + 0.0. Writing the
    // three steps out literally would not be exact there: (x - 0.5) rounds for
    // small x, so the contrast round trip would not return x, and
    // mix(l, col, 1.0) is only exactly col if the driver spells mix as
    // x*(1-a) + y*a rather than as x + a*(y - x). Do not un-fold this.
    //
    // Being affine is also what makes a grade safe after the blend at all. The
    // scaler's weights sum to 1, so ga*sum(w_i*x_i) + gb == sum(w_i*(ga*x_i +
    // gb)): grading here is identical to grading the four taps, at a quarter of
    // the cost, and it cannot give partial-coverage pixels a coverage-dependent
    // shift - which is the thing that beats against the pixel grid.
    //
    // All three are neutral at 1.00, so one test covers them, and it reads only
    // uniforms - the same value for every fragment in the draw, so the branch
    // is uniform and the block is skipped outright when nobody has touched a
    // slider. That is 32 instructions, against 16 and six SFU lanes for the
    // gamma below.
    //
    // Compared exactly, with no epsilon, unlike the gamma guard below. The two
    // guards are not the same kind of test. pow(x, 1.0) is exp2(log2(x)) on a
    // GPU and rounds, so the gamma needs a dead band around 1.0 to be a true
    // no-op; this block at 1.00 is col*1.0 + 0.0, which is exact, so there is
    // nothing to protect against and a dead band would only buy a range of
    // settings where this shader and v3 disagree. Exact is both cheaper and
    // strictly equivalent.
    //
    // Test the three separately. Do NOT sum them and compare against 3.0:
    // brightness 1.1 with contrast 0.9 cancels to exactly 3.0 and the grade
    // would be dropped without a trace.
    //
    // A uniform branch is safe here in a way the warped floor() elsewhere in
    // this repo is not. That one has its argument vary across the frame, so it
    // must cross the boundary somewhere and float32 and float64 land on
    // opposite sides; this argument does not vary at all.
    if (pp_brightness != 1.0 || pp_contrast != 1.0
        || pp_saturation != 1.0) {
        float ga = pp_brightness * pp_contrast;
        float gb = 0.5 - 0.5 * pp_contrast;
        col = col * (ga * pp_saturation)
            + (dot(col, LUMA) * (ga * (1.0 - pp_saturation)) + gb);

        // The clamp lives inside the guard because only a grade can push a
        // value out of range: the scaler's own output is a convex blend of four
        // taps that are each already within 0 to 1. It is where a grade is
        // actually paid for, being a non-linearity after the blend, so a
        // control pushed past what the display can show trades a little moire
        // for the clipped look. The pow below guards its own base, so leaving
        // it out of the neutral path costs that nothing.
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
