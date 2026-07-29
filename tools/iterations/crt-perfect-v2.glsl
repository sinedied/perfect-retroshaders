/*
    crt-perfect-v2 - pixel-perfect scaling with CRT scanlines and an RGB subpixel mask.

    Author:  sinedied
    Licence: MIT - Copyright (c) 2026 sinedied

    Permission is hereby granted, free of charge, to any person obtaining a copy of
    this software and associated documentation files (the "Software"), to deal in
    the Software without restriction, including without limitation the rights to
    use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
    of the Software, and to permit persons to whom the Software is furnished to do
    so, subject to the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial portions of
    the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

    v2 of crt-perfect.glsl. Same look at normal scale factors, but the
    anti-aliasing guards are corrected and the mask costs one cosine less.
    See CHANGES FROM V1 at the bottom of this comment.

    Does the whole CRT chain in a single pass: area-averaged upscale straight to
    the final on-screen size, horizontal scanlines whose count follows the source
    vertical resolution, and a luma-neutral RGB triad mask locked to the source
    pixel grid.

    REQUIRED PASS SETTINGS  (Shader > Shader 1 in the in-game menu)

        minarch_nrofshaders       = 1
        minarch_shader1           = crt-perfect-v2.glsl
        minarch_shader1_filter    = NEAREST
        minarch_shader1_srctype   = source
        minarch_shader1_scaletype = source
        minarch_shader1_upscale   = screen      <-- important
        minarch_scale_filter      = NEAREST

    "upscale = screen" makes this pass render at exactly the final on-screen size,
    so one output pixel is one device pixel and the mask lands on real pixels.
    Any other upscale value resamples the result a second time and both the mask
    and the scanlines will alias.

    PARAMETERS

        Scanlines         visibility of the scanlines, 0 turns them off
        Beam_Width        0.2 = fat dark gap / thin beam, 1.0 = thin dark line
        RGB_Mask          visibility of the RGB mask, 0 turns it off
        Mask_Type         0 = off, 1 = aperture grille, 2 = offset (slot) grille
        Mask_Size         triads per source pixel (1.0 = one RGB triad per pixel)
        Brightness        gain applied at the end, compensates the darkening
        Scanline_Min      scanlines are off at or below this vertical scale
                          factor and reach full strength one step above it

    The scanline count is always the source vertical resolution: 224p content
    gets 224 scanlines, no configuration needed.

    Scanlines and mask darken the image, exactly like a real CRT and like the
    overlay images this was matched against. Brightness compensates for that.
    Note that at the default 1.25 the beam peaks hard-clip to white: this is a
    plain clamp, not a bloom, so highlight detail above ~0.89 is lost. Set
    Brightness to 1.0 for a strictly non-clipping image.

    SAMPLING LIMITS

    A pattern needs at least two output pixels per cycle to exist at all, and a
    colour triad needs three to show distinct R/G/B. Both effects therefore
    switch themselves off rather than fold into moire:

      - scanlines fade out at or below Scanline_Min output pixels per source
        line (default 2.0) and reach full strength at Scanline_Min + 1.
      - the mask fades out below 2 output pixels per triad and reaches full
        strength at 3.
      - the beam profile is pushed towards a pure cosine as the scale factor
        drops, because pow(cosine, k) generates harmonics for any k != 1 and
        those harmonics alias before the fundamental does.

    OTHER LIMITS

      - Requires fragment highp (all GLES 3.x targets provide it). The scanline
        and mask phases reach several hundred before fract(), which mediump
        cannot represent.
      - The four-tap area average is an upscaler. It assumes an output pixel
        footprint spans at most two source texels per axis, so it does not
        correctly downsample when the source is larger than the on-screen rect.
        (Same limitation as the stock pixellate.glsl it derives from.)

    CHANGES FROM V1

      1. Scanline fade window moved up one octave. v1 faded between scale 1 and
         2, but a scanline pattern already exceeds Nyquist below scale 2, so v1
         drew a wrong, coarser pattern at near-full strength for 400p-480p
         content (e.g. 480p on 720p produced a 3.00px pattern instead of 1.50px).
         v2 is silent at or below 2.0 and ramps to full at 3.0.
      2. Fixes v1 going completely flat at exactly 2x vertical scale, where the
         sampled phases pin to 0.25/0.75 and give an identical beam value: the
         image was uniformly darkened ~20% with no scanlines visible at all.
      3. Beam exponent is blended towards 1.0 (a pure, harmonic-free cosine) at
         low scale factors. No visible change at 224p/240p.
      4. Mask fade edge moved from 1.5 to 2.0 output pixels per triad; below 2
         no modulation can be represented at all.
      5. The pow() guard no longer lifts the black floor. v1 clamped the base to
         1e-5 to dodge a driver NaN, which at Beam_Width 1.0 turned an intended
         0 into 0.056 (60/255). v2 keeps the clamp but restores the exact zero.
      6. One less cosine per fragment: the three mask primaries sum to a
         constant, so blue is derived from red and green instead of computed.
      7. Area weights are applied separably, which drops the 1/(w*h)-sized
         totalArea divisor.

*/

#pragma parameter Scanlines    "Scanline visibility"        0.55 0.00 1.00 0.05
#pragma parameter Beam_Width   "Scanline beam width"        0.65 0.20 1.00 0.05
#pragma parameter RGB_Mask     "RGB mask visibility"        0.35 0.00 1.00 0.05
#pragma parameter Mask_Type    "Mask 0off 1grille 2slot"    1.00 0.00 2.00 1.00
#pragma parameter Mask_Size    "Mask triads per pixel"      1.00 0.25 2.00 0.25
#pragma parameter Brightness   "Brightness"                 1.25 0.50 2.00 0.05
#pragma parameter Scanline_Min "Scanlines off below scale"  2.00 1.00 4.00 0.50

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

#define Source Texture
#define vTexCoord TEX0.xy
#define SourceSize vec4(TextureSize, 1.0 / TextureSize)
#define outsize vec4(OutputSize, 1.0 / OutputSize)

#define TAU 6.283185307

#ifdef PARAMETER_UNIFORM
uniform COMPAT_PRECISION float Scanlines;
uniform COMPAT_PRECISION float Beam_Width;
uniform COMPAT_PRECISION float RGB_Mask;
uniform COMPAT_PRECISION float Mask_Type;
uniform COMPAT_PRECISION float Mask_Size;
uniform COMPAT_PRECISION float Brightness;
uniform COMPAT_PRECISION float Scanline_Min;
#else
#define Scanlines 0.55
#define Beam_Width 0.65
#define RGB_Mask 0.35
#define Mask_Type 1.0
#define Mask_Size 1.0
#define Brightness 1.25
#define Scanline_Min 2.0
#endif

void main()
{
    vec2 texelSize = SourceSize.zw;

    // ------------------------------------------------------------------
    // Area-averaged upscale, straight to the output size. Each output pixel
    // integrates the source over its own footprint, so source pixels come out
    // as uniform blocks with a single soft pixel wherever a block boundary
    // falls between two output pixels. Integer scale factors stay exact.
    // Blending happens in linear light (x*x here, sqrt at the end); gamma 2.0
    // rather than 2.2 keeps this off the pow() path, which matters at
    // 1024x768 on a Mali G31.
    // ------------------------------------------------------------------
    vec2 range = vec2(abs(InputSize.x / (outsize.x * SourceSize.x)),
                      abs(InputSize.y / (outsize.y * SourceSize.y)));
    range = range / 2.0 * 0.999;

    float left   = vTexCoord.x - range.x;
    float top    = vTexCoord.y + range.y;
    float right  = vTexCoord.x + range.x;
    float bottom = vTexCoord.y - range.y;

    vec3 topLeft     = COMPAT_TEXTURE(Source, (floor(vec2(left,  top)    / texelSize) + 0.5) * texelSize).rgb;
    vec3 bottomRight = COMPAT_TEXTURE(Source, (floor(vec2(right, bottom) / texelSize) + 0.5) * texelSize).rgb;
    vec3 bottomLeft  = COMPAT_TEXTURE(Source, (floor(vec2(left,  bottom) / texelSize) + 0.5) * texelSize).rgb;
    vec3 topRight    = COMPAT_TEXTURE(Source, (floor(vec2(right, top)    / texelSize) + 0.5) * texelSize).rgb;

    topLeft     *= topLeft;
    bottomRight *= bottomRight;
    bottomLeft  *= bottomLeft;
    topRight    *= topRight;

    vec2 border = clamp(floor((vTexCoord / texelSize) + vec2(0.5)) * texelSize,
                        vec2(left, bottom), vec2(right, top));

    // separable weights: the footprint is a rectangle, so the four corner areas
    // factor into one horizontal and one vertical term
    float wLeft = (border.x - left)   / (2.0 * range.x);
    float wTop  = (top - border.y)    / (2.0 * range.y);

    vec3 color = mix(mix(bottomRight, bottomLeft, wLeft),
                     mix(topRight,    topLeft,    wLeft), wTop);

    // ------------------------------------------------------------------
    // Scanlines. The phase comes from the source row, so the line count is the
    // source vertical resolution automatically.
    //
    // A scanline pattern needs >= 2 output pixels per source line to exist;
    // below that it folds to a coarser, wrong pattern. So the strength is
    // zero at Scanline_Min and ramps in over the next unit of scale. The
    // beam exponent is also pulled towards 1.0 (a pure cosine) at low scale,
    // because pow(cosine, k) has harmonics for k != 1 and they alias first.
    // ------------------------------------------------------------------
    float vscale = OutputSize.y / max(InputSize.y, 1.0);
    float scanAmount = Scanlines * smoothstep(Scanline_Min, Scanline_Min + 1.0, vscale);

    if (scanAmount > 0.0) {
        float k = mix(1.0, exp2((0.5 - Beam_Width) * 4.0),
                      smoothstep(2.0, 3.5, vscale));
        float p = fract(vTexCoord.y * InputSize.y);
        float raw = 0.5 - 0.5 * cos(TAU * p);
        // pow() is undefined for a base of exactly 0, which fract() hits
        // whenever a source line boundary lands on an output pixel centre;
        // drivers return NaN there and the line renders black. Clamp the base,
        // then restore the exact zero the clamp would otherwise lift.
        float beam = pow(max(raw, 1e-5), k) * step(1e-5, raw);
        color *= mix(1.0, beam, scanAmount);
    }

    // ------------------------------------------------------------------
    // RGB mask, locked to the source pixel grid. Three primaries 120 degrees
    // apart sum to a constant, so the mask is luma neutral and introduces no
    // colour cast - and blue can be derived instead of computed, saving a
    // cosine. The -1/6 offset centres the triad on the source pixel: red at
    // 1/6, green at 1/2, blue at 5/6 across it.
    //
    // Below 2 output pixels per triad no modulation can be represented, and 3
    // are needed to resolve distinct R/G/B, so that is the fade window.
    // ------------------------------------------------------------------
    float triadPixels = OutputSize.x / max(InputSize.x * Mask_Size, 1.0);
    float maskAmount = RGB_Mask * smoothstep(2.0, 3.0, triadPixels);

    if (maskAmount > 0.0 && Mask_Type >= 0.5) {
        float phase = vTexCoord.x * InputSize.x * Mask_Size - (1.0 / 6.0);

        // offset grille: stagger the triads by half a cell on alternate source
        // rows. The vertical separation of a real slot mask comes from the
        // scanlines, so this reads as slots only with Scanlines > 0.
        if (Mask_Type >= 1.5) {
            phase += 0.5 * mod(floor(vTexCoord.y * InputSize.y), 2.0);
        }

        vec3 mask;
        mask.rg = 0.5 + 0.5 * cos(TAU * (fract(phase) - vec2(0.0, 1.0 / 3.0)));
        mask.b  = 1.5 - mask.r - mask.g;
        color *= mix(vec3(1.0), mask, maskAmount);
    }

    color = clamp(color * Brightness, 0.0, 1.0);

    FragColor = vec4(sqrt(color), 1.0);
}

#endif
