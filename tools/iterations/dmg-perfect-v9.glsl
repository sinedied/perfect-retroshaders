// dmg-perfect v9 - a Game Boy dot matrix over a pixel-perfect scale.
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
//   dp_brightness     0.25 - 4.00  Output gain.
//   dp_gamma          0.50 - 2.00  Output gamma. 1.00 disables it.
//   dp_temperature   -1.00 - 1.00  Warm above 0, cool below. 0.00 is off.
//   dp_tint          -1.00 - 1.00  Green above 0, magenta below. 0.00 is off.
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
// - dp_shadow is usable across most of its range: measured on a Game Boy
//   palette it costs 0.24 at 0.25, 0.29 at 0.45 and 0.39 at 0.70, against a
//   visible threshold of 0.4, so only the top of the range is worth avoiding.
// - dp_temperature and dp_tint are the two axes of a white balance, worth
//   having because Game Boy palettes vary a lot between cores and none of them
//   is neutral. Useful trims are small, roughly within 0.20; the rest of the
//   range is there for effect. They shift the overall level a little as well
//   as the colour, which dp_brightness can take back out.
// - Set dp_brightness 1.20 and dp_gamma 1.40 for dmg_dot_matrix's own tone.
//   Both sit after the blend, so they trade a little of the evenness the rest
//   of this buys; the defaults leave them neutral and the trade to you.

#pragma parameter dp_grid        "Grid visibility"          0.30  0.00 1.00 0.01
#pragma parameter dp_gap         "Grid line px"             1.00  0.25 2.00 0.05
#pragma parameter dp_shadow      "Dot shadow"               0.00  0.00 1.00 0.01
#pragma parameter dp_brightness  "Brightness"               1.00  0.25 4.00 0.05
#pragma parameter dp_gamma       "Gamma"                    1.00  0.50 2.00 0.05
#pragma parameter dp_temperature "Warm / cool balance"      0.00 -1.00 1.00 0.01
#pragma parameter dp_tint        "Green / magenta balance"  0.00 -1.00 1.00 0.01

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
uniform COMPAT_PRECISION float dp_brightness;
uniform COMPAT_PRECISION float dp_gamma;
uniform COMPAT_PRECISION float dp_temperature;
uniform COMPAT_PRECISION float dp_tint;
#else
#define dp_grid 0.30
#define dp_gap 1.0
#define dp_shadow 0.0
#define dp_brightness 1.0
#define dp_gamma 1.0
#define dp_temperature 0.0
#define dp_tint 0.0
#endif

// The substrate a DMG's gaps show: undriven crystal at its lightest state.
#define DMG_SUBSTRATE 1.0

#define LUMA vec3(0.299, 0.587, 0.114)

// Floor under the paper level the shadow measures opacity against. Stops the
// reference collapsing onto the ink in a large dark region, which would switch
// the shadow off where the picture is darkest. Must sit below the darkest
// palette anyone ships (Gambatte's DMG is 0.401) or it dims undriven pixels.
#define PAPER_FLOOR 0.35

// In source pixels, so the shadow holds its proportions at every scale. Down
// more than across, as a panel lit from above. Fixed, not exposed.
#define SHADOW_OFFSET vec2(0.50, 0.85)

// Extra half-width on the box that samples the displaced aperture. Free, since
// the coverage is already a box mean. Softens the aperture's gaps only, not the
// shadow's outer edge - that comes from the opacity field below.
#define APERTURE_SOFT 0.5

// Antiderivative of the dot profile: 1 across the lit part of a cell, 0 across
// the gap. Differencing it gives the exact box mean, with no transcendentals.
// Peak-normalised, so it is a coverage mask topping out at 1.
vec2 dotInt(vec2 x, vec2 w)
{
    vec2 n = floor(x);
    return n * w + clamp(x - n, vec2(0.0), w);
}

void main()
{
    // Source texels: p is this pixel's centre, h its half footprint. The max()
    // guards an unset uniform, which is 0 and would make every pixel NaN.
    vec2 p = TEX0.xy * TextureSize;
    vec2 h = max(0.4995 * InputSize / OutputSize, 1e-6);
    vec2 B = floor(p + 0.5);

    // N is the whole scale that fits, which is what the two-pass pipeline this
    // reproduces renders at. A dp_gap line there is dp_gap/N of a cell here, so
    // the line stays about a pixel wide at any scale and exactly one at a whole
    // one. The nudge guards floor() on a division landing a ULP short of 5.0.
    vec2 sc = OutputSize / max(InputSize, 1.0);
    float N = max(floor(min(sc.x, sc.y) + 1e-3), 1.0);
    vec2 lit = clamp(vec2(1.0 - dp_gap / N), 1e-3, 1.0);

    // Coverage of the lit dot over this output pixel, exactly, per axis.
    vec2 Alo = dotInt(p - h, lit);
    vec2 Ahi = dotInt(p + h, lit);
    vec2 Iap = max(Ahi - Alo, vec2(1e-6));
    vec2 cov = Iap / (2.0 * h);

    // Two weightings of the same four taps. wA splits the footprint by area,
    // giving mean(source); wL splits it by how much of the dot falls each side,
    // giving mean(source x dot). The grid owes the second - the area mean alone
    // is what made this break up at a fractional scale. In a gap wL is 0/0, so
    // it falls back to wA rather than to whatever the hardware picks.
    vec2 wA = clamp((B - p + h) / (2.0 * h), 0.0, 1.0);
    vec2 wL = mix(wA, clamp((B * lit - Alo) / Iap, 0.0, 1.0),
                  smoothstep(vec2(0.0), vec2(0.01), cov));

    // Below two output pixels per cell the pattern folds to a coarser pitch at
    // near-full amplitude, so it has to reach zero at two, not at one. The
    // window clears a whole 3x, the smallest scale a Game Boy meets.
    cov = mix(vec2(1.0), cov, smoothstep(vec2(2.0), vec2(2.9), sc));
    float dot2d = cov.x * cov.y;

    vec2 lo = (B - 0.5) / TextureSize;
    vec2 hi = (B + 0.5) / TextureSize;
    vec3 t00 = COMPAT_TEXTURE(Texture, vec2(lo.x, lo.y)).rgb;
    vec3 t10 = COMPAT_TEXTURE(Texture, vec2(hi.x, lo.y)).rgb;
    vec3 t01 = COMPAT_TEXTURE(Texture, vec2(lo.x, hi.y)).rgb;
    vec3 t11 = COMPAT_TEXTURE(Texture, vec2(hi.x, hi.y)).rgb;

    // mix() returns y at t == 1, so the low-side tap goes second on both axes.
    vec3 area = mix(mix(t11, t01, wA.x), mix(t10, t00, wA.x), wA.y);
    vec3 dotm = mix(mix(t11, t01, wL.x), mix(t10, t00, wL.x), wL.y);

    // area stays raw: the shadow reads opacity as a ratio of two source levels,
    // so an output gain has to cancel out of it rather than change how much
    // light a dot appears to block. Scaling into col keeps both, for free.
    vec3 col = mix(area * dp_brightness,
                   mix(vec3(DMG_SUBSTRATE), dotm * dp_brightness, dot2d),
                   dp_grid);

    // A cast shadow, so the dots sit above the panel rather than printed on it.
    // It multiplies everything, which is what the optics say: light crosses the
    // crystal, reflects off the substrate and crosses back, so a neighbour
    // shading the substrate scales whatever that cell finally shows. Darkening
    // the gap colour alone reads as a mesh drawn on top instead.
    //
    // The branch is uniform across the draw, so this costs nothing when off.
    if (dp_shadow > 0.0) {
        // In source pixels, so the offset is a fixed fraction of a cell.
        vec2 q = p - SHADOW_OFFSET;

        // The dot's own shape, displaced. Widening the averaging footprint is
        // a box blur of the aperture, and costs only the wider divide.
        vec2 hs = h + APERTURE_SOFT;
        vec2 covS = max(dotInt(q + hs, lit) - dotInt(q - hs, lit), vec2(0.0))
                    / (2.0 * hs);
        covS = mix(vec2(1.0), covS, smoothstep(vec2(2.0), vec2(2.9), sc));

        // How driven the casting cells are, as a smooth field. This is the
        // whole of the blur: opacity decides where the shadow ends, so
        // sampling it nearest puts a hard cell-sized edge on the result no
        // matter what the aperture does. Interpolating the four surrounding
        // cells turns that step into a ramp one cell wide.
        //
        // Four taps, inside the uniform branch, so free with the shadow off.
        //
        // No epsilon on this floor, and that is deliberate. The cell pair and
        // the interpolation weight have to come from the same value or they
        // disagree by a whole cell, which is what an epsilon on one of them
        // does. Biasing both together does not help either: the float32 error
        // already in the interpolated texcoord is larger than any epsilon worth
        // adding, so wherever the shifted point lands near a boundary the GPU
        // and a float64 model can pick different cells - and at a fractional
        // scale that is a great many pixels, not a few.
        //
        // It is harmless here, unlike the scaler's own floor(). The weight goes
        // to zero exactly where the pair changes, so both choices interpolate
        // to the same value; only the two ends of the pair swap. That is the
        // property to preserve if this is ever rewritten - not the epsilon,
        // and not a reduction over the same four values.
        vec2 g = q - 0.5;
        vec2 gi = floor(g);
        vec2 gf = g - gi;
        vec2 c0 = (gi + 0.5) / TextureSize;
        vec2 c1 = (gi + 1.5) / TextureSize;
        vec4 cl = vec4(
            dot(COMPAT_TEXTURE(Texture, vec2(c0.x, c0.y)).rgb, LUMA),
            dot(COMPAT_TEXTURE(Texture, vec2(c1.x, c0.y)).rgb, LUMA),
            dot(COMPAT_TEXTURE(Texture, vec2(c0.x, c1.y)).rgb, LUMA),
            dot(COMPAT_TEXTURE(Texture, vec2(c1.x, c1.y)).rgb, LUMA));
        float casterLum = mix(mix(cl.x, cl.y, gf.x),
                              mix(cl.z, cl.w, gf.x), gf.y);

        // The undriven level to measure opacity against. Not white: no Game
        // Boy palette is near it, and dividing by white judges every shade
        // most of the way opaque, dimming the picture instead of shadowing it.
        //
        // The luma of the area blend, already computed, before any output gain.
        // A blend rather than a max over neighbours: a reduction has to gate
        // each term by its blend weight, and that gate is a step, which prints
        // its own structure into the shadow. See docs/dmg-perfect.md.
        float paper = max(dot(area, LUMA), PAPER_FLOOR);

        // Both sides raw: opacity is a property of the panel, so an output
        // gain must cancel out of the ratio.
        float opacity = clamp(1.0 - casterLum / paper, 0.0, 1.0);

        col *= 1.0 - dp_shadow * opacity * covS.x * covS.y;
    }


    // White balance, for palettes that are not neutral - and none of the Game
    // Boy ones are. Two axes rather than three per-channel gains: a gain above
    // 1 on one channel only warms a picture by clipping it.
    //
    // A multiply is affine and the blend weights sum to one, so doing it here
    // is identical to doing it to the four taps at a quarter of the cost, and
    // it is not the kind of post-blend non-linearity that beats. On the
    // finished colour, so the substrate takes the same tint as the picture.
    // Not luma-normalised, so it shifts level a little; dp_brightness undoes
    // that.
    //
    // Tested separately, not summed, or a warm temperature could cancel a cool
    // tint into a false neutral. Uniform branch, so free when left alone.
    if (dp_temperature != 0.0 || dp_tint != 0.0) {
        col *= 1.0 + dp_temperature * vec3(1.0, 0.0, -1.0)
                   + dp_tint        * vec3(-0.5, 1.0, -0.5);
    }

    // Uniform branch, so a gamma of 1 costs nothing. pow(0, g) is undefined and
    // returns NaN on real drivers, hence the clamp; 1e-8 rather than 1e-5,
    // which would lift pure black to 1/255 at the lowest gamma.
    if (abs(dp_gamma - 1.0) > 0.001) {
        col = pow(max(col, 1e-8), vec3(dp_gamma));
    }

    FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}

#endif
