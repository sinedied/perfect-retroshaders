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
//   dp_grid           0.00 - 1.00  Grid visibility. 0 disables it.
//   dp_gap            0.25 - 2.00  Grid line thickness, in pixels.
//   dp_shadow         0.00 - 1.00  Cast shadow under each dot. 0 disables it.
//   dp_shadow_offset  0.25 - 3.00  How far the shadow falls, in pixels.
//   dp_brightness     0.25 - 4.00  Output gain.
//   dp_gamma          0.50 - 2.00  Output gamma. 1.00 disables it.
// -----------------------------------------------------------------------------
// Draws a Game Boy's dot matrix over a pixel-perfect scale. It reproduces, in a
// single pass, what you get by drawing the matrix at a whole scale factor and
// then scaling that up: the grid line is one pixel wide at the whole scale that
// fits the screen, and the image and the grid are filtered together rather than
// multiplied, so the cells stay even at a fractional scale instead of breaking
// into a pattern.
//
// A DMG has no backlight and its crystal is normally white, so the gaps between
// pixels - which have no electrode and can never be driven - sit permanently at
// the lightest state. Its matrix is therefore lighter than a lit pixel, the
// opposite of every backlit panel, and the grid is invisible on white and
// strongest on dark content, which is how a real DMG reads.
//
// Notes:
// - Render at the output resolution, 1:1 with the display.
// - dp_gap is a thickness in output pixels, not a share of a cell, so 1.00 is
//   the line dmg_dot_matrix draws and the panel reads the same at 640x480 as at
//   1024x768. At a whole scale factor the two are identical pixel for pixel.
// - dp_shadow lifts the dots off the substrate. It is off by default and the
//   branch is uniform, so it costs nothing until it is asked for. It buys that
//   look with pattern, faster than the grid does: measured 0.18, 0.36 and 0.64
//   at 0.15, 0.35 and 0.50, where anything past ~0.4 starts to show. Keep it
//   low. Avoid an offset near 1.00 exactly - a one pixel lobe has no solid
//   core, so it wobbles, and it measures worst of any distance.
// - Set dp_brightness 1.20 and dp_gamma 1.40 for dmg_dot_matrix's own tone.
//   Both sit after the blend, so they trade a little of the evenness the rest
//   of this buys; the defaults leave them neutral and the trade to you.

#pragma parameter dp_grid          "Grid visibility"       0.30 0.00 1.00 0.01
#pragma parameter dp_gap           "Grid line px"          1.00 0.25 2.00 0.05
#pragma parameter dp_shadow        "Dot shadow"            0.00 0.00 1.00 0.01
#pragma parameter dp_shadow_offset "Shadow distance px"    1.50 0.25 3.00 0.05
#pragma parameter dp_brightness    "Brightness"            1.00 0.25 4.00 0.05
#pragma parameter dp_gamma         "Gamma"                 1.00 0.50 2.00 0.05

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
uniform COMPAT_PRECISION float dp_shadow;
uniform COMPAT_PRECISION float dp_shadow_offset;
uniform COMPAT_PRECISION float dp_brightness;
uniform COMPAT_PRECISION float dp_gamma;
#else
#define dp_grid 0.30
#define dp_gap 1.0
#define dp_shadow 0.0
#define dp_shadow_offset 1.5
#define dp_brightness 1.0
#define dp_gamma 1.0
#endif

// The substrate a DMG's gaps show: undriven crystal at its lightest state.
#define DMG_SUBSTRATE 1.0

// Antiderivative of the dot profile, which is 1 across the lit part of a cell
// and 0 across the gap at its trailing edge. Differencing it over an interval
// gives the exact mean of the profile there - the true box filter, and with no
// transcendentals. Peak-normalised, so it tops out at 1: this is a coverage
// mask, where lcd-perfect's mean-normalised aperture peaks near 3.
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
    vec2 B = floor(p + 0.5);

    // N is the whole scale that fits - what a frontend's integer mode would
    // pick, and what the two-pass pipeline this reproduces renders at. 5 at
    // 1024x768, 3 at 640x480. So a line of dp_gap pixels there is dp_gap/N of a
    // cell here, which keeps the line about a pixel wide at every scale and
    // exactly one pixel at a whole one.
    //
    // The nudge is not decoration: floor() on a division result is a trap this
    // family has been bitten by, and reading 4 instead of 5 at exactly 5.0
    // would break the whole-scale case that everything else is pinned to.
    vec2 sc = OutputSize / max(InputSize, 1.0);
    float N = max(floor(min(sc.x, sc.y) + 1e-3), 1.0);
    vec2 lit = clamp(vec2(1.0 - dp_gap / N), 1e-3, 1.0);

    // Coverage of the lit dot over this output pixel, exactly, per axis.
    vec2 Alo = dotInt(p - h, lit);
    vec2 Ahi = dotInt(p + h, lit);
    vec2 Iap = max(Ahi - Alo, vec2(1e-6));
    vec2 cov = Iap / (2.0 * h);

    // Two sets of blend weights over the same four taps.
    //
    // wA splits the footprint by area, which gives the mean of the source.
    // wL splits it by how much of the *dot* falls each side of the boundary,
    // which gives the mean of source x dot. Both are needed: what the grid owes
    // is mean(source x dot), and using the area mean alone is the fault that
    // made this shader break up at a fractional scale, while using the aperture
    // mean alone - which is what lcd-perfect does, for a pattern that peaks at
    // the cell centre rather than sitting on its edge - is worse still.
    //
    // Where an output pixel lands wholly in a gap there is no aperture to
    // weight by and wL is 0/0, so it falls back to wA. That value is otherwise
    // arbitrary, and float32 and float64 do not have to pick the same one.
    vec2 wA = clamp((B - p + h) / (2.0 * h), 0.0, 1.0);
    vec2 wL = mix(wA, clamp((B * lit - Alo) / Iap, 0.0, 1.0),
                  smoothstep(vec2(0.0), vec2(0.01), cov));

    // Below two output pixels per cell there is no room for a dot and a line,
    // and the pattern folds to a coarser pitch at near-full amplitude, so it
    // has to reach zero *at* two rather than at one. The window clears a whole
    // 3x with room to spare, so the smallest scale a Game Boy meets keeps its
    // full grid even if the ratio lands a few ULP short.
    cov = mix(vec2(1.0), cov, smoothstep(vec2(2.0), vec2(2.9), sc));
    float dot2d = cov.x * cov.y;

    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;
    vec3 t00 = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 t10 = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 t01 = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 t11 = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    // mix(x, y, t) returns y at t == 1, so the low-side tap is the second
    // argument on both axes.
    vec3 area = mix(mix(t11, t01, wA.x), mix(t10, t00, wA.x), wA.y);
    vec3 dotm = mix(mix(t11, t01, wL.x), mix(t10, t00, wL.x), wL.y);
    area *= dp_brightness;
    dotm *= dp_brightness;

    float substrate = DMG_SUBSTRATE;

    // A cast shadow, so the dots read as sitting above the substrate rather
    // than being holes in it. The same aperture again, shifted; where the
    // shifted dot lands and the real one does not, the substrate is in shade.
    // Built from the aperture field and folded in before the grid mix, never
    // multiplied over the finished image - a one-sided pattern locked to the
    // cell boundary is the worst case for that.
    //
    // The branch is uniform across the draw, so this costs nothing when off.
    if (dp_shadow > 0.0) {
        vec2 off = vec2(dp_shadow_offset) / sc;
        vec2 covS = max(dotInt(p - off + h, lit) - dotInt(p - off - h, lit),
                        vec2(0.0)) / (2.0 * h);
        covS = mix(vec2(1.0), covS, smoothstep(vec2(2.0), vec2(2.9), sc));
        // only the lobe the dot does not already cover, and only as dark as the
        // dot casting it. The darkness comes from the area mean, not the
        // aperture mean: this term is not multiplied by the coverage, so it
        // cannot use a value that is 0/0 wherever the coverage is zero.
        float lobe = max(covS.x * covS.y - dot2d, 0.0);
        float caster = clamp(1.0 - dot(area, vec3(0.299, 0.587, 0.114)),
                             0.0, 1.0);
        substrate -= dp_shadow * lobe * caster;
    }

    vec3 col = mix(area, mix(vec3(substrate), dotm, dot2d), dp_grid);

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
