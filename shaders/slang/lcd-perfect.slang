#version 450
// lcd-perfect v10 - an LCD matrix and RGB stripes over a pixel-perfect scale.
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
//   lp_grid        0.00 - 1.00  Grid visibility. 0 disables it.
//   lp_balance     0.00 - 1.00  Row/column balance. 0 rows, 1 columns.
//   lp_min_pitch   2.00 - 6.00  Smallest pattern pitch, in output pixels.
//   lp_subpixels   0.00 - 1.00  RGB stripe visibility. 0 disables them.
//   lp_layout      0 / 1        Stripe order: RGB or BGR.
//   lp_brightness  0.25 - 4.00  Output gain. 1.00 disables it.
//   lp_gamma       0.50 - 2.00  Output gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// A handheld LCD look: a soft backlit mesh with RGB subpixel stripes, over a
// clean pixel scale. Reads like a Game Boy Color or GBA screen in good light -
// a gentle grid rather than a hard black matrix, and it stays even at every
// scale instead of breaking into a pattern.
//
// Notes:
// - Needs a LINEAR filter, set in the preset. Under NEAREST the scale becomes
//   ordinary nearest-neighbour and the picture gets ragged edges.
// - Render at the output resolution, 1:1 with the display.
// - Row/column balance sets which axis dominates. Real panels are row-dominant;
//   0.80 or so matches lcd1x.
// - Brightness above 1.00 clips, may create pattern artifacts against the
//   pixel grid unless the output is an integer scale.

layout(push_constant) uniform Push
{
	vec4 SourceSize;
	vec4 OriginalSize;
	vec4 OutputSize;
	float lp_grid;
	float lp_balance;
	float lp_min_pitch;
	float lp_subpixels;
	float lp_layout;
	float lp_brightness;
	float lp_gamma;
} params;

layout(std140, set = 0, binding = 0) uniform UBO
{
	mat4 MVP;
} global;

#pragma parameter lp_grid "Grid visibility" 0.30 0.00 1.00 0.01
#pragma parameter lp_balance "Row/column balance" 0.60 0.00 1.00 0.01
#pragma parameter lp_min_pitch "Minimum pitch in px" 3.00 2.00 6.00 0.25
#pragma parameter lp_subpixels "RGB stripe visibility" 0.20 0.00 1.00 0.05
#pragma parameter lp_layout "Stripe order 0=RGB 1=BGR" 0.00 0.00 1.00 1.00
#pragma parameter lp_brightness "Brightness" 1.25 0.25 4.00 0.05
#pragma parameter lp_gamma "Gamma" 1.00 0.50 2.00 0.05

// The names the shader body uses, mapped onto slang's. After the Push block, so
// they cannot rewrite its members. Everything below is the released shader.
#define TextureSize params.SourceSize.xy
#define InputSize params.OriginalSize.xy
#define OutputSize params.OutputSize.xy
#define Texture Source
#define COMPAT_TEXTURE texture
#define COMPAT_PRECISION
#define lp_grid params.lp_grid
#define lp_balance params.lp_balance
#define lp_min_pitch params.lp_min_pitch
#define lp_subpixels params.lp_subpixels
#define lp_layout params.lp_layout
#define lp_brightness params.lp_brightness
#define lp_gamma params.lp_gamma

#pragma stage vertex
layout(location = 0) in vec4 Position;
layout(location = 1) in vec2 TexCoord;
layout(location = 0) out vec2 vTexCoord;

void main()
{
	gl_Position = global.MVP * Position;
	vTexCoord = TexCoord;
}

#pragma stage fragment
layout(location = 0) in vec2 vTexCoord;
layout(location = 0) out vec4 FragColor;
layout(set = 0, binding = 2) uniform sampler2D Source;

#define TEX0 vec4(vTexCoord, 0.0, 0.0)
#define TAU 6.283185307
#define PI  3.141592654

// cos and sin of TAU/6, the angle from a cell's centre to the red stripe.
// Green sits half a turn from there, so its pair is (-1, 0) and costs nothing.
#define COS_TAU_6 0.5
#define SIN_TAU_6 0.866025404

// Mean of a unit sinusoid over one output pixel. The mesh gets this exactly
// from the integral below; the stripes are sampled, so they need it named.
float boxSinc(float f)
{
    float x = PI * max(f, 1e-4);
    return sin(x) / x;
}

// Past Nyquist the pattern would fold to a coarser pitch at nearly full
// strength, so take it out entirely instead.
vec2 nyquistFade(vec2 f)
{
    return 1.0 - smoothstep(0.34, 0.5, f);
}

void main()
{
    vec2 p = TEX0.xy * TextureSize;
    vec2 d = max(InputSize / OutputSize, 1e-6);
    vec2 B = floor(p + 0.5);

    // Cells per period: a WHOLE number of cells, never a fixed pixel size, so
    // the pattern stays periodic on the source grid. The bias is load-bearing -
    // a/b is a*rcp(b), so a ratio of exactly 1 can land a hair above it.
    vec2 N = max(ceil(lp_min_pitch * d - 1e-4), 1.0);

    vec2 f = d / N;

    // A sinusoid does not band-limit itself, so this cannot be dropped.
    vec2 fade = nyquistFade(f);

    // Once a period spans several cells only one boundary in N carries a line,
    // so the amplitude is spread back out. N == 1 is untouched.
    vec2 amp = clamp(lp_grid * 2.0 * vec2(lp_balance, 1.0 - lp_balance), 0.0, 1.0)
               * fade * (2.0 / (N + 1.0));

    // Half an output pixel, in cycles: puts one sample per cycle on the
    // trough, which is what lets a two-pixel pitch resolve at all.
    vec2 phase = 0.5 * f;

    // The pattern coordinate, in periods. With N == 1 this is exactly p.
    vec2 t  = p / N;
    vec2 hh = 0.4995 * f;

    // The aperture integral over the footprint, the exact box filter. Both ends
    // are symmetric about X, so one sin and one cos of X do the work of four
    // and the stripes below reuse the pair.
    vec2 X    = TAU * (t - phase);
    vec2 sinX = sin(X);
    vec2 cosX = cos(X);

    vec2 Y    = TAU * hh;
    vec2 sinY = sin(Y);
    vec2 cosY = cos(Y);
    vec2 k    = amp / TAU;

    // Alo must use the UNCLAMPED Iraw, or the two disagree where I clamps.
    vec2 Iraw = 2.0 * hh - k * (2.0 * cosX * sinY);
    vec2 Alo  = t - 0.5 * Iraw - (k * cosY) * sinX;
    vec2 I    = max(Iraw, 1e-6);

    // Peak-normalised, so the flat top lands at 1 and nothing meets the clamp.
    vec2 g = I * (1.0 / (2.0 * hh * (1.0 + amp)));
    float gain = g.x * g.y;

    // The mesh's dark line and the scaler's transition pixel both sit on the
    // cell boundary, so the blend is weighted by aperture, not by area.
    vec2 Bt  = B / N;
    vec2 AB  = Bt - k * sin(TAU * (Bt - phase));
    vec2 w   = clamp((AB - Alo) / I, 0.0, 1.0);

    // One LINEAR tap, handed the weights above: this texcoord asks the texture
    // unit for exactly mix(T[B], T[B-1], w).
    vec3 color = COMPAT_TEXTURE(Texture, (B + 0.5 - w) / TextureSize).rgb;

    // Three sinusoids 120 degrees apart, summing to exactly 3 at every pixel,
    // so they are luminance neutral and blue costs no third cosine.
    vec3 stripe = vec3(1.0);
    if (lp_subpixels > 0.0) {
        float sinc = boxSinc(f.x);
        float ac   = lp_subpixels * sinc * fade.x;
        vec2 rg = 1.0 + ac * vec2(COS_TAU_6 * cosX.x + SIN_TAU_6 * sinX.x,
                                  -cosX.x);
        stripe = vec3(rg, 3.0 - rg.x - rg.y);

        // A column mesh and the stripes share a pitch, so whichever stripe
        // lands on the dark line is dimmed. Divide the cast back out; M must be
        // the BOX-FILTERED amplitude or it overshoots where the filter bites.
        float M = amp.x * sinc;
        vec3 corr = 1.0 - 0.5 * M * ac * vec3(COS_TAU_6, -1.0, COS_TAU_6);
        // sqrt() below halves any deviation on the way to the encoded value,
        // so the correction is halved here to match.
        stripe /= sqrt(max(corr, 1e-3));

        if (lp_layout >= 0.5) {
            stripe = stripe.bgr;
        }
    }

    // Treating the encoding as a gamma of 2 makes sqrt(linear * m) equal
    // encoded * sqrt(m), so one square root replaces the decode and re-encode.
    // Brightness rides the pattern, so the clamp lands on the product.
    vec3 m = sqrt(max(stripe * (gain * lp_brightness), 0.0));

    // The base is clamped because pow(0, g) is undefined and returns NaN on
    // real drivers. 1e-8, not 1e-5, which would lift pure black to 1/255.
    if (abs(lp_gamma - 1.0) > 0.001) {
        color = pow(max(color, 1e-8), vec3(lp_gamma));
    }

    vec3 outc = color * m;

    FragColor = vec4(clamp(outc, 0.0, 1.0), 1.0);
}
