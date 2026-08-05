#version 450
// unflat-mini v1 - barrel distortion and a tube edge.
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
// - Needs a LINEAR filter, set in the preset. The bend resamples the picture,
//   and under NEAREST there is nothing to interpolate.
// - Draws no pattern of its own. Use it after a shader that does like crt-mini,
//   or use it alone to bend the image.

layout(push_constant) uniform Push
{
	vec4 SourceSize;
	vec4 OriginalSize;
	vec4 OutputSize;
	float um_curvature;
	float um_corner;
} params;

layout(std140, set = 0, binding = 0) uniform UBO
{
	mat4 MVP;
} global;

#pragma parameter um_curvature "Screen curvature" 0.07 0.00 0.30 0.01
#pragma parameter um_corner "Corner softness" 1.00 0.00 4.00 0.25

// The names the shader body uses, mapped onto slang's. After the Push block, so
// they cannot rewrite its members. Everything below is the released shader.
#define TextureSize params.SourceSize.xy
#define InputSize params.OriginalSize.xy
#define OutputSize params.OutputSize.xy
#define Texture Source
#define COMPAT_TEXTURE texture
#define COMPAT_PRECISION
#define um_curvature params.um_curvature
#define um_corner params.um_corner

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
void main()
{
    vec2  uv   = vTexCoord;
    float tube = 1.0;

    if (um_curvature > 0.0) {
        // Dividing by the edge-midpoint value keeps the image edges on the
        // screen edges, so only the corners curve away and nothing is cropped.
        float norm = 1.0 / (1.0 + um_curvature);
        vec2  c    = uv * 2.0 - 1.0;
        vec2  cc   = c * c;
        float r2   = cc.x + cc.y;

        uv = c * (1.0 + um_curvature * r2) * norm * 0.5 + 0.5;

        // The corners now sample past the image, where the sampler would
        // stretch the border texel; mask them instead.
        vec2 e  = max(um_corner, 1e-4) / OutputSize;
        vec2 aa = clamp(uv / e, 0.0, 1.0) * clamp((1.0 - uv) / e, 0.0, 1.0);
        tube = aa.x * aa.y;
    }

    vec3 color = COMPAT_TEXTURE(Source, uv).rgb;

    FragColor = vec4(clamp(color * tube, 0.0, 1.0), 1.0);
}
