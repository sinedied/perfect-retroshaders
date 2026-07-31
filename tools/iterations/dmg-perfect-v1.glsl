// dmg-perfect - a Game Boy dot matrix over a pixel-perfect scale.
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
//   dp_grid        0.00 - 1.00  Grid visibility. 0 disables it.
//   dp_gap         0.00 - 0.50  Gap thickness, as a share of a cell.
//   dp_level       0.00 - 1.00  What the gap shows. 1 substrate, 0 black.
//   dp_brightness  0.25 - 4.00  Output gain.
//   dp_gamma       0.50 - 2.00  Output gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// Draws a Game Boy's dot matrix over a pixel-perfect scale: every source pixel
// becomes an even block with a gap along two of its edges. The gap is a share
// of a cell rather than a fixed number of output pixels, so the panel reads the
// same at 640x480 as at 1024x768 instead of coarsening as the screen shrinks.
// Coverage is integrated exactly over each output pixel, so the lines stay
// evenly spaced at a fractional scale, where a hard-edged grid has to alternate
// six and seven pixels apart.
//
// A DMG has no backlight and its crystal is normally white, so the gaps between
// pixels - which have no electrode and can never be driven - sit permanently at
// the lightest state. Its matrix is therefore lighter than a lit pixel, the
// opposite of every backlit panel. dp_level 1.00 is that; 0.00 gives the dark
// matrix a backlit Pocket or Light shows.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - The line never falls below one output pixel wide, nor below two at a
//   fractional scale, whatever share dp_gap asks for. A thinner line is mostly
//   soft edge, and how much of it is soft shifts from cell to cell.
// - Set dp_brightness 1.20 and dp_gamma 1.40 to reproduce dmg_dot_matrix,
//   which at a whole scale factor is then identical pixel for pixel. Both sit
//   after the blend, so they trade a little of the evenness the rest of this
//   buys; the defaults leave them neutral and the trade to you.
// - Unlike the others here, this shader does not darken what it draws on - a
//   DMG grid is invisible on white - so a gain above 1.00 clips rather than
//   restores. On a Game Boy palette, which peaks well below white, it does not.

#pragma parameter dp_grid       "Grid visibility"        0.30 0.00 1.00 0.01
#pragma parameter dp_gap        "Gap thickness"          0.20 0.00 0.50 0.01
#pragma parameter dp_level      "Gap 0=dark 1=light"     1.00 0.00 1.00 0.01
#pragma parameter dp_brightness "Brightness"             1.00 0.25 4.00 0.05
#pragma parameter dp_gamma      "Gamma"                  1.00 0.50 2.00 0.05

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
uniform COMPAT_PRECISION float dp_grid;
uniform COMPAT_PRECISION float dp_gap;
uniform COMPAT_PRECISION float dp_level;
uniform COMPAT_PRECISION float dp_brightness;
uniform COMPAT_PRECISION float dp_gamma;
#else
#define dp_grid 0.30
#define dp_gap 0.20
#define dp_level 1.0
#define dp_brightness 1.0
#define dp_gamma 1.0
#endif

// Antiderivative of the dot profile, which is 1 across the lit part of a cell
// and 0 across the gap at its trailing edge. Differencing it over an output
// pixel's footprint gives that pixel's exact dot coverage, 0 to 1 - the true box
// filter, and with no transcendentals. Peak-normalised, not mean-normalised:
// this is a coverage mask so it has to top out at 1, where lcd-perfect's
// mean-normalised aperture peaks near 3 and would drive the mix past white.
vec2 dotInt(vec2 x, vec2 w)
{
    vec2 n = floor(x);
    return n * w + clamp(x - n, vec2(0.0), w);
}

void main()
{
    // Work in source texels: p is this output pixel's centre, h its half
    // footprint. The max() matters: a host that does not set the uniform leaves
    // it at 0, and h is a divisor below, so every pixel would come out NaN.
    vec2 p = TEX0.xy * TextureSize;
    vec2 h = max(0.4995 * InputSize / OutputSize, 1e-6);

    // B is the texel boundary nearest the footprint. w is the share of the
    // footprint on B's low side, and clamps to exactly 0 or 1 whenever the
    // footprint lies wholly inside one texel - which is most output pixels, and
    // is what keeps the blocks flat instead of gradients.
    vec2 B = floor(p + 0.5);
    vec2 w = clamp((B - p + h) / (2.0 * h), 0.0, 1.0);

    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;
    vec3 a = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 b = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 c = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 d = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    // mix(x, y, t) returns y at t == 1, so the low-side value is the second
    // argument on both axes.
    vec3 col = mix(mix(d, c, w.x), mix(b, a, w.x), w.y) * dp_brightness;

    // How wide the gap should actually be.
    //
    // dp_gap is a share of a cell, which is what keeps the look the same at
    // every resolution - but a share can land on an awkward number of output
    // pixels. A 1.28px line is mostly soft edge, and how much of it is soft
    // changes from cell to cell, which is what shows at a fractional scale.
    //
    // So: never thinner than one output pixel, and never thinner than two when
    // the scale is not whole, because only from two pixels up is a line
    // guaranteed a fully covered one at its core whatever its phase. At a whole
    // scale the floor is one pixel, which is exactly what dmg_dot_matrix draws.
    //
    // The second pixel is only taken while the cell can afford it. It is worth
    // 1/sc of a cell, so at five output pixels per cell it has already reached
    // 40% and below that it starts swallowing the dot rather than edging it -
    // at 640x480 a Game Boy cell is 3.33px down, where two pixels would be 60%.
    //
    // The whole-scale test is a smooth distance to the nearest integer, never an
    // equality: a scale that is mathematically whole can land a few ULP off it.
    vec2 sc = OutputSize / max(InputSize, 1.0);
    vec2 offs = abs(sc - floor(sc + 0.5));
    vec2 room = clamp(sc - 4.0, 0.0, 1.0);
    vec2 minpx = 1.0 + clamp(offs / 0.25, 0.0, 1.0) * room;
    // ... but a gap of zero means no gap, so the floor has to fade out with it
    // rather than hold a line open under a slider the user has closed.
    vec2 gapEff = max(vec2(dp_gap), minpx / sc * smoothstep(0.0, 0.01, dp_gap));

    // The guard is against a NaN screen rather than a look: downscaling is out
    // of scope, but at sc below 1 the floor asks for a gap wider than the cell,
    // and a negative width inverts the clamp inside dotInt.
    vec2 lit = max(vec2(1.0) - gapEff, vec2(1e-3));
    vec2 cov = (dotInt(p + h, lit) - dotInt(p - h, lit)) / (2.0 * h);

    // Below two output pixels per cell there is no room for a lit dot and a
    // line, and the pattern folds to a coarser pitch at near-full amplitude, so
    // it has to reach zero *at* two rather than at one. Per axis, on the
    // coverage rather than on the gap: thinning the line instead would leave a
    // sub-pixel feature, which is the thing being avoided. The window clears 3.0
    // with room to spare, so a whole 3x scale keeps the full grid even if it
    // lands a few ULP short.
    cov = mix(vec2(1.0), cov, smoothstep(vec2(2.0), vec2(2.9), sc));
    float dot2d = cov.x * cov.y;

    // A DMG gap shows the substrate, so by default it lightens rather than
    // darkens. dp_level 0 gives the dark matrix of a backlit panel instead.
    col = mix(vec3(dp_level), col, mix(1.0, dot2d, dp_grid));

    // The branch is uniform across the draw, so a gamma of 1 costs nothing. The
    // base is clamped because pow(0, g) is undefined and returns NaN on real
    // drivers, and black texels are everywhere; 1e-8 is small enough that pure
    // black still encodes to 0 even at the lowest gamma, where 1e-5 would lift
    // it to 1/255.
    if (abs(dp_gamma - 1.0) > 0.001) {
        col = pow(max(col, 1e-8), vec3(dp_gamma));
    }

    FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}

#endif
