#version 450
// dmg-perfect v11 - a Game Boy dot matrix over a pixel-perfect scale.
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
//   dp_grid           0.00 - 1.00  Grid visibility. 0 disables it.
//   dp_gap            0.25 - 2.00  Grid line thickness, in pixels.
//   dp_shadow         0.00 - 1.00  Shadow cast by driven dots. 0 disables it.
//   dp_brightness     0.25 - 4.00  Output gain. 1.00 disables it.
//   dp_gamma          0.50 - 2.00  Output gamma. 1.00 disables it.
//   dp_temperature   -1.00 - 1.00  Warm above 0, cool below. 0.00 is off.
//   dp_tint          -1.00 - 1.00  Green above 0, magenta below. 0.00 is off.
// -----------------------------------------------------------------------------
// An original Game Boy look: the dot matrix grid with its pale gaps, over a
// clean pixel scale. Dots can cast a shadow so they sit above the panel. The
// grid is invisible on white and strongest on dark content, as a real DMG is.
//
// Notes:
// - Needs a LINEAR filter, set in the preset. Under NEAREST the scale becomes
//   ordinary nearest-neighbour and the picture gets ragged edges.
// - Render at the output resolution, 1:1 with the display.
// - Grid line thickness is in output pixels, so the panel reads the same at
//   every resolution. 1.00 is a one-pixel line.
// - Brightness above 1.00 clips, may create pattern artifacts against the
//   pixel grid unless the output is an integer scale.

layout(push_constant) uniform Push
{
	vec4 SourceSize;
	vec4 OriginalSize;
	vec4 OutputSize;
	float dp_grid;
	float dp_gap;
	float dp_shadow;
	float dp_brightness;
	float dp_gamma;
	float dp_temperature;
	float dp_tint;
} params;

layout(std140, set = 0, binding = 0) uniform UBO
{
	mat4 MVP;
} global;

#pragma parameter dp_grid "Grid visibility" 0.30 0.00 1.00 0.01
#pragma parameter dp_gap "Grid line thickness" 1.00 0.25 2.00 0.05
#pragma parameter dp_shadow "Dot shadow" 0.00 0.00 1.00 0.01
#pragma parameter dp_brightness "Brightness" 1.00 0.25 4.00 0.05
#pragma parameter dp_gamma "Gamma" 1.20 0.50 2.00 0.05
#pragma parameter dp_temperature "Cool / warm balance" 0.00 -1.00 1.00 0.01
#pragma parameter dp_tint "Magenta / green balance" 0.00 -1.00 1.00 0.01

// The names the shader body uses, mapped onto slang's. After the Push block, so
// they cannot rewrite its members. Everything below is the released shader.
#define TextureSize params.SourceSize.xy
#define InputSize params.OriginalSize.xy
#define OutputSize params.OutputSize.xy
#define Texture Source
#define COMPAT_TEXTURE texture
#define COMPAT_PRECISION
#define dp_grid params.dp_grid
#define dp_gap params.dp_gap
#define dp_shadow params.dp_shadow
#define dp_brightness params.dp_brightness
#define dp_gamma params.dp_gamma
#define dp_temperature params.dp_temperature
#define dp_tint params.dp_tint

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
// The substrate a DMG's gaps show: undriven crystal at its lightest state.
#define DMG_SUBSTRATE 1.0

#define LUMA vec3(0.299, 0.587, 0.114)

// Floor under the paper level the shadow measures opacity against. Must sit
// below the darkest palette anyone ships.
#define PAPER_FLOOR 0.35

// In source pixels, so the shadow holds its proportions at every scale.
#define SHADOW_OFFSET vec2(0.45, 0.85)

// Extra half-width on the box that samples the displaced aperture. Softens the
// aperture's gaps only; the shadow's outer edge comes from the opacity field.
#define APERTURE_SOFT 0.5

// Antiderivative of the dot profile. Differencing it gives the exact box mean.
// Peak-normalised, so it is a coverage mask topping out at 1.
vec2 dotInt(vec2 x, vec2 w)
{
    vec2 n = floor(x);
    return n * w + clamp(x - n, vec2(0.0), w);
}

void main()
{
    // Source texels. The max() guards an unset uniform, which is 0 and would
    // make h a zero divisor below.
    vec2 p = TEX0.xy * TextureSize;
    vec2 h = max(0.4995 * InputSize / OutputSize, 1e-6);
    vec2 B = floor(p + 0.5);

    // N is the whole scale that fits, so a dp_gap line is dp_gap/N of a cell
    // and stays a pixel wide at any scale. The nudge guards floor() on a
    // division landing a ULP short.
    vec2 sc = OutputSize / max(InputSize, 1.0);
    float N = max(floor(min(sc.x, sc.y) + 1e-3), 1.0);
    vec2 lit = clamp(vec2(1.0 - dp_gap / N), 1e-3, 1.0);

    // Coverage of the lit dot over this output pixel, exactly, per axis.
    vec2 cov = max(dotInt(p + h, lit) - dotInt(p - h, lit), vec2(1e-6))
               / (2.0 * h);

    // Below two output pixels per cell the pattern folds to a coarser pitch,
    // so it has to reach zero at two, not at one.
    cov = mix(vec2(1.0), cov, smoothstep(vec2(2.0), vec2(2.9), sc));
    float dot2d = cov.x * cov.y;

    // B is the nearest texel boundary and w the share of the footprint on its
    // low side, handed to the texture unit: one LINEAR tap returns the blend.
    vec2 w = clamp((B - p + h) / (2.0 * h), 0.0, 1.0);
    vec3 area = COMPAT_TEXTURE(Texture, (B + 0.5 - w) / TextureSize).rgb;

    // Not applied to the SUBSTRATE, so brightening lifts the dots toward a
    // fixed paper rather than washing the whole panel out.
    vec3 grade = (1.0 + dp_temperature * vec3(1.0, 0.0, -1.0)
                      + dp_tint        * vec3(-0.5, 1.0, -0.5)) * dp_brightness;

    // Gaps show the substrate, dots show the picture; k is the share of this
    // pixel reading as gap.
    float k = dp_grid * (1.0 - dot2d);
    vec3 col = mix(area * grade, vec3(DMG_SUBSTRATE), k);

    // Multiplies everything rather than darkening the gap colour, which is
    // what puts the shadow underneath the dots.
    if (dp_shadow > 0.0) {
        // In source pixels, so the offset is a fixed fraction of a cell.
        vec2 q = p - SHADOW_OFFSET;

        // The dot's own shape, displaced and widened: a box blur of it.
        vec2 hs = h + APERTURE_SOFT;
        vec2 covS = max(dotInt(q + hs, lit) - dotInt(q - hs, lit), vec2(0.0))
                    / (2.0 * hs);
        covS = mix(vec2(1.0), covS, smoothstep(vec2(2.0), vec2(2.9), sc));

        // dot() is linear, so the luma of a blend is the blend of lumas and
        // one tap suffices.
        float casterLum = dot(COMPAT_TEXTURE(Texture, q / TextureSize).rgb, LUMA);

        // The undriven level to measure opacity against - not white, since no
        // Game Boy palette is near it.
        float paper = max(dot(area, LUMA), PAPER_FLOOR);

        // Both sides raw, so an output gain cancels out of the ratio.
        float opacity = clamp(1.0 - casterLum / paper, 0.0, 1.0);

        col *= 1.0 - dp_shadow * opacity * covS.x * covS.y;
    }

    // The base is clamped because pow(0, g) is undefined and returns NaN on
    // real drivers. 1e-8, not 1e-5, which would lift pure black to 1/255.
    if (abs(dp_gamma - 1.0) > 0.001) {
        col = pow(max(col, 1e-8), vec3(dp_gamma));
    }

    FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
