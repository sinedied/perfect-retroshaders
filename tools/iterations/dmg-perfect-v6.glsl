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
//   dp_shadow         0.00 - 1.00  Shadow cast by driven dots. 0 disables it.
//   dp_shadow_blur    0.00 - 1.00  Shadow softness, in source pixels.
//   dp_red            0.00 - 2.00  Red gain. 1.00 disables it.
//   dp_green          0.00 - 2.00  Green gain. 1.00 disables it.
//   dp_blue           0.00 - 2.00  Blue gain. 1.00 disables it.
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
// - dp_shadow lifts the dots off the panel. Only a driven pixel casts one: the
//   darker a dot is against the undriven panel around it, the more light it
//   blocks, and the palette's lightest shade casts nothing at all. It falls
//   behind everything, so it reads through the pale undriven cells and is
//   hidden by the dark driven ones, which is what makes the dots look raised
//   rather than outlined. Off by default, and the branch is uniform, so it
//   costs nothing until it is asked for.
// - The shadow's distance and softness are fixed in source pixels, so they
//   hold their proportions at every resolution rather than shrinking as the
//   screen grows.
// - dp_red, dp_green and dp_blue trim the colour balance, which is worth having
//   because Game Boy palettes vary a lot between cores and none of them is
//   neutral. They are plain gains, so above 1.00 they clip; the usual way to
//   warm or cool a picture is to pull the other two channels down instead.
// - dp_shadow is usable across most of its range: measured on a Game Boy
//   palette it costs 0.24 at 0.25, 0.29 at 0.45 and 0.39 at 0.70, against a
//   visible threshold of 0.4, so only the top of the range is worth avoiding.
// - Set dp_brightness 1.20 and dp_gamma 1.40 for dmg_dot_matrix's own tone.
//   Both sit after the blend, so they trade a little of the evenness the rest
//   of this buys; the defaults leave them neutral and the trade to you.

#pragma parameter dp_grid          "Grid visibility"       0.30 0.00 1.00 0.01
#pragma parameter dp_gap           "Grid line px"          1.00 0.25 2.00 0.05
#pragma parameter dp_shadow        "Dot shadow"            0.00 0.00 1.00 0.01
#pragma parameter dp_shadow_blur   "Shadow softness"       0.60 0.00 1.00 0.05
#pragma parameter dp_red           "Red gain"              1.00 0.00 2.00 0.01
#pragma parameter dp_green         "Green gain"            1.00 0.00 2.00 0.01
#pragma parameter dp_blue          "Blue gain"             1.00 0.00 2.00 0.01
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
uniform COMPAT_PRECISION float dp_shadow_blur;
uniform COMPAT_PRECISION float dp_red;
uniform COMPAT_PRECISION float dp_green;
uniform COMPAT_PRECISION float dp_blue;
uniform COMPAT_PRECISION float dp_brightness;
uniform COMPAT_PRECISION float dp_gamma;
#else
#define dp_grid 0.30
#define dp_gap 1.0
#define dp_shadow 0.0
#define dp_shadow_blur 0.6
#define dp_brightness 1.0
#define dp_gamma 1.0
#define dp_red 1.0
#define dp_green 1.0
#define dp_blue 1.0
#endif

// The substrate a DMG's gaps show: undriven crystal at its lightest state.
#define DMG_SUBSTRATE 1.0

#define LUMA vec3(0.299, 0.587, 0.114)

// Floor under the reference the shadow measures opacity against, as a luma.
//
// A pixel casts a shadow in proportion to how much light it blocks, which is
// 1 - its own level divided by the level of undriven panel. That divisor is the
// palette's lightest shade, and it is not knowable in advance: measured across
// the cores, Gambatte's DMG is 0.401, mGBA's DMG green 0.560, a Pocket palette
// 0.664 to 0.767, and a plain greyscale palette 1.000.
//
// The brightest of the four taps supplies it for free and can never be wrong on
// the high side, since undriven panel is by definition the brightest thing
// near a dot. What it cannot do is survive the middle of a large dark region,
// where all four taps are ink and the reference would collapse onto the ink
// itself, switching the shadow off exactly where the picture is darkest. Hence
// a floor - and it has to sit below the darkest paper anyone ships, because a
// floor above it dims every undriven pixel on screen, which is the whole fault
// this replaces. At 0.45 that is a 10.8% dimming of Gambatte's default palette.
#define PAPER_FLOOR 0.35

// Where the shadow falls and how soft it is, both in source pixels so they hold
// their proportions at every resolution. Fixed rather than exposed: these are
// the values that look like a panel lit from above, and a shadow that can be
// aimed anywhere is a way to make it look wrong.
#define SHADOW_OFFSET vec2(0.50, 0.85)

// How much of dp_shadow_blur also goes into widening the box filter on the
// displaced aperture. That widening is free - the coverage is already the exact
// mean of the aperture over the output pixel's footprint, so a wider footprint
// is a wider box - but it only softens the aperture's own gaps, NOT the edge of
// the shadow as a whole. That edge comes from the per-cell opacity below, and
// blurring it needs real taps. v5 widened the box alone and the outer edge
// stayed exactly one output pixel wide, which is no blur at all.
#define APERTURE_SOFT 0.5

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

    vec3 col = mix(area, mix(vec3(DMG_SUBSTRATE), dotm, dot2d), dp_grid);

    // A cast shadow, so the dots read as sitting above the panel rather than
    // being printed on it.
    //
    // It goes *under* everything, which is both what it looks like and what the
    // optics say. On a reflective panel the light crosses the liquid crystal,
    // reflects off the substrate and crosses back, so a neighbour that shades
    // the substrate scales whatever that cell finally shows. An undriven cell
    // is transparent and the shadow reads through it clearly; a driven one is
    // already dark and hides it. That falls out of a single multiply, and it is
    // the whole difference from the previous version, which subtracted the
    // shadow from the gap colour alone - the gap is one output pixel wide, so
    // the shadow could only ever darken the grid lines, which reads as a mesh
    // drawn on top rather than as anything lying underneath.
    //
    // The branch is uniform across the draw, so this costs nothing when off.
    if (dp_shadow > 0.0) {
        // Offset in source pixels, not output pixels: a shadow is thrown by a
        // dot, so it sits a fixed fraction of a *cell* away and looks the same
        // at every scale. Further down than across, as a panel lit from above.
        vec2 q = p - SHADOW_OFFSET;

        // The dot's own shape, displaced and softened. hs is the footprint the
        // aperture is averaged over, so widening it past the output pixel is a
        // box blur of the aperture and costs nothing beyond the wider divide.
        vec2 hs = h + dp_shadow_blur * APERTURE_SOFT;
        vec2 covS = max(dotInt(q + hs, lit) - dotInt(q - hs, lit), vec2(0.0))
                    / (2.0 * hs);
        covS = mix(vec2(1.0), covS, smoothstep(vec2(2.0), vec2(2.9), sc));

        // How driven the casting cell is. One nearest tap: the offset is a
        // whole cell or more away, so it is outside the four the scaler holds,
        // and opacity is a per-cell quantity anyway - a dot is either driven or
        // it is not, and the displaced aperture above already supplies the
        // edges. Sampling the cell centre keeps it stable.
        // How driven the casting cells are, as a smooth field rather than a
        // per-cell step.
        //
        // This is the whole of the blur. Opacity is what decides where the
        // shadow ends, so sampling it nearest puts a hard cell-sized edge on
        // the result no matter what is done to the aperture - measured on a
        // block of dark cells, v5's outer edge fell from full to nothing in one
        // output pixel. Interpolating between the four surrounding cells turns
        // that step into a ramp, and dp_shadow_blur sets how wide the ramp is:
        // at 0 the weights collapse to a nearest pick and this is exactly v5,
        // at 1 they are plain bilinear and the gradient spans a whole cell.
        //
        // Four taps, which is the cost of the feature. They sit inside the
        // uniform branch, so nothing is paid for them with the shadow off.
        // No epsilon on this floor, and that is deliberate.
        //
        // The cell pair and the interpolation weight have to come from the same
        // value or they disagree by a whole cell, which is what an epsilon on
        // one of them does. Biasing both together does not help either: the
        // float32 error already in the interpolated texcoord is larger than any
        // epsilon worth adding, so wherever the shifted point lands near a
        // boundary the GPU and a float64 model can pick different cells - and
        // at a fractional scale that is a great many pixels, not a few.
        //
        // It is harmless here, unlike the scaler's own floor(). The weight goes
        // to zero exactly where the pair changes, so both choices interpolate
        // to the same value; only the two ends of the pair swap. That is the
        // property to preserve if this is ever rewritten - not the epsilon.
        vec2 g = q - 0.5;
        vec2 gi = floor(g);
        vec2 gf = g - gi;
        vec2 wb = clamp((gf - 0.5) / max(dp_shadow_blur, 1e-4) + 0.5, 0.0, 1.0);
        vec2 c0 = (gi + 0.5) / TextureSize;
        vec2 c1 = (gi + 1.5) / TextureSize;
        vec4 cl = vec4(
            dot(COMPAT_TEXTURE(Texture, vec2(c0.x, c0.y)).rgb, LUMA),
            dot(COMPAT_TEXTURE(Texture, vec2(c1.x, c0.y)).rgb, LUMA),
            dot(COMPAT_TEXTURE(Texture, vec2(c0.x, c1.y)).rgb, LUMA),
            dot(COMPAT_TEXTURE(Texture, vec2(c1.x, c1.y)).rgb, LUMA));
        float casterLum = mix(mix(cl.x, cl.y, wb.x),
                              mix(cl.z, cl.w, wb.x), wb.y);

        // The undriven level to measure that opacity against. Not white: no
        // Game Boy palette is anywhere near it, and dividing by white judges
        // every shade to be most of the way opaque, which dims the whole
        // picture instead of shadowing it. Taken as the brightest tap that
        // actually feeds this pixel, floored - see PAPER_FLOOR.
        //
        // Gating on the blend weight is what keeps it stable: B = floor(p+0.5)
        // picks the tap *pair*, and at an exact boundary - every other pixel at
        // a whole scale factor - it can land either side. The blend does not
        // care, since both choices carry the same texel at unit weight, but a
        // plain max over the pair swaps in a different neighbour and moves the
        // shadow by up to 29/255. Weighting first collapses both onto one tap.
        vec4 k = vec4(wA.x * wA.y, (1.0 - wA.x) * wA.y,
                      wA.x * (1.0 - wA.y), (1.0 - wA.x) * (1.0 - wA.y));
        k = smoothstep(vec4(0.0), vec4(0.02), k);
        vec4 lum = vec4(dot(t00, LUMA), dot(t10, LUMA),
                        dot(t01, LUMA), dot(t11, LUMA)) * k;
        float paper = max(max(max(lum.x, lum.y), max(lum.z, lum.w)),
                          PAPER_FLOOR);
        // Both sides of this ratio are raw source values, deliberately.
        // Opacity is a property of the panel, so an output gain has to cancel
        // out of it rather than change how much light a dot appears to block.
        float opacity = clamp(1.0 - casterLum / paper, 0.0, 1.0);

        col *= 1.0 - dp_shadow * opacity * covS.x * covS.y;
    }


    // The branch is uniform across the draw, so a gamma of 1 costs nothing. The
    // base is clamped because pow(0, g) is undefined and returns NaN on real
    // drivers, and black texels are everywhere; 1e-8 is small enough that pure
    // black still encodes to 0 even at the lowest gamma, where 1e-5 would lift
    // it to 1/255.
    // Per-channel trim. A gain is affine, so applying it here is identical to
    // applying it to the four taps - the blend weights sum to one - at a
    // quarter of the cost, and it is not the kind of post-blend non-linearity
    // that would beat against the pixel grid. It goes on the finished colour
    // rather than the taps on purpose: the substrate is part of the panel, so
    // it should take the same tint as the picture.
    //
    // The branch is uniform across the draw, so a neutral balance costs
    // nothing, which is the only reason it is a branch and not three multiplies.
    if (abs(dp_red - 1.0) + abs(dp_green - 1.0) + abs(dp_blue - 1.0) > 0.001) {
        col *= vec3(dp_red, dp_green, dp_blue);
    }

    if (abs(dp_gamma - 1.0) > 0.001) {
        col = pow(max(col, 1e-8), vec3(dp_gamma));
    }

    FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}

#endif
