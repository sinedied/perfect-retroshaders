#version 450
// crt-perfect v14 - scanlines, an RGB mask and curvature, pixel-perfect scale.
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
// - Needs a LINEAR filter, set in the preset. Under NEAREST the scale becomes
//   ordinary nearest-neighbour and the picture gets ragged edges.
// - Render at the output resolution, 1:1 with the display.
// - At min. pitch 2.00 the mask becomes 2 colours: use 2.50 or more to keep
//   the triads visible.
// - Brightness above 1.00 clips, may create pattern artifacts against the
//   pixel grid unless the output is an integer scale.

layout(push_constant) uniform Push
{
	vec4 SourceSize;
	vec4 OriginalSize;
	vec4 OutputSize;
	float cp_scanlines;
	float cp_rgb_mask;
	float cp_mask_type;
	float cp_mask_size;
	float cp_min_pitch;
	float cp_curvature;
	float cp_brightness;
	float cp_gamma;
} params;

layout(std140, set = 0, binding = 0) uniform UBO
{
	mat4 MVP;
} global;

#pragma parameter cp_scanlines "Scanline visibility" 0.60 0.00 1.00 0.05
#pragma parameter cp_rgb_mask "RGB mask visibility" 0.20 0.00 1.00 0.05
#pragma parameter cp_mask_type "Mask 0=off 1=grille 2=slot" 1.00 0.00 2.00 1.00
#pragma parameter cp_mask_size "Mask triads per pixel" 1.00 0.25 2.00 0.25
#pragma parameter cp_min_pitch "Min. pitch in px" 3.00 2.00 6.00 0.25
#pragma parameter cp_curvature "Screen curvature" 0.00 0.00 0.15 0.01
#pragma parameter cp_brightness "Brightness" 1.25 0.25 4.00 0.05
#pragma parameter cp_gamma "Gamma" 1.00 0.50 2.00 0.05

// The names the shader body uses, mapped onto slang's. After the Push block, so
// they cannot rewrite its members. Everything below is the released shader.
#define TextureSize params.SourceSize.xy
#define InputSize params.OriginalSize.xy
#define OutputSize params.OutputSize.xy
#define Texture Source
#define COMPAT_TEXTURE texture
#define COMPAT_PRECISION
#define cp_scanlines params.cp_scanlines
#define cp_rgb_mask params.cp_rgb_mask
#define cp_mask_type params.cp_mask_type
#define cp_mask_size params.cp_mask_size
#define cp_min_pitch params.cp_min_pitch
#define cp_curvature params.cp_curvature
#define cp_brightness params.cp_brightness
#define cp_gamma params.cp_gamma

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
#define outsize vec4(OutputSize, 1.0 / OutputSize)

#define PI  3.141592654
#define TAU 6.283185307


// Average of a unit sinusoid of frequency f, in cycles per output pixel, over
// one pixel-wide box. Reaches zero at one cycle per pixel.
float boxSinc(float f)
{
    float x = PI * max(f, 1e-4);
    return sin(x) / x;
}

// Nothing above Nyquist can be drawn, so fade the pattern out entirely there -
// amplitude and darkening together, leaving no uniform dimming behind.
float nyquistFade(float f)
{
    return 1.0 - smoothstep(0.34, 0.5, f);
}

void main()
{
    vec2  uv   = vTexCoord;
    float tube = 1.0;
    float noWarp = 1.0;

    if (cp_curvature > 0.0) {
        // Dividing by the edge-midpoint value keeps the image edges on the
        // screen edges, so only the corners curve away and nothing is cropped.
        float norm = 1.0 / (1.0 + cp_curvature);
        vec2  c    = uv * 2.0 - 1.0;
        vec2  cc   = c * c;
        float r2   = cc.x + cc.y;

        uv  = c * (1.0 + cp_curvature * r2) * norm * 0.5 + 0.5;
        noWarp = 0.0;

        // The corners now sample past the image, where the sampler would
        // stretch the border texel; mask them instead.
        vec2 e  = outsize.zw;
        vec2 aa = clamp(uv / e, 0.0, 1.0) * clamp((1.0 - uv) / e, 0.0, 1.0);
        tube = aa.x * aa.y;
    }

    // h is deliberately independent of the warp: it keeps everything below it
    // uniform across the draw, which the driver can then compute once.
    vec2 p = uv * TextureSize;
    vec2 h = max(0.4995 * InputSize / OutputSize, 1e-6);

    // B is the nearest texel boundary and w the share of the footprint on its
    // low side, handed to the texture unit: one LINEAR tap returns the blend.
    vec2 B = floor(p + 0.5);
    vec2 w = clamp((B - p + h) / (2.0 * h), 0.0, 1.0);
    vec3 color = COMPAT_TEXTURE(Source, (B + 0.5 - w) / TextureSize).rgb;

    // The base is clamped because pow(0, g) is undefined and returns NaN on
    // real drivers. 1e-8, not 1e-5, which would lift pure black to 1/255.
    if (abs(cp_gamma - 1.0) > 0.001) {
        color = pow(max(color, 1e-8), vec3(cp_gamma));
    }

    float scanSrcPitch = OutputSize.y / max(InputSize.y, 1.0);
    float scanPitch    = max(scanSrcPitch, cp_min_pitch);
    float scanLocked   = (1.0 - smoothstep(cp_min_pitch * 1.001, cp_min_pitch * 1.02, scanSrcPitch)) * noWarp;
    float scanFreq     = 1.0 / scanPitch;

    // The flat pitch, used even under curvature: it holds the pattern to one
    // cycle per source line, and keeps this uniform across the draw.
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

    // Brightness rides the pattern, so the clamp below lands on the product.
    // Clamping the picture instead flattens highlights before the mask shapes
    // them.
    vec3 gain = sqrt(max(mask * (scan * cp_brightness), 0.0));

    FragColor = vec4(clamp(color * gain * tube, 0.0, 1.0), 1.0);
}
