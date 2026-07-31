"""Which numpy model belongs to which shader, and what to check it with.

gl_check.py walks this registry: for every entry it compiles the real shipped
.glsl, runs it on the GPU, runs the model over the same input, and diffs. The two
implementations are independent on purpose - an error has to be made identically
in GLSL and in numpy to slip through.

Add a shader by adding an entry. Nothing else needs wiring.
"""

from models.crt import (
    DEFAULTS, DEFAULTS_V2, DEFAULTS_V3, DEFAULTS_V4, DEFAULTS_V5, DEFAULTS_V6,
    DEFAULTS_V7, DEFAULTS_V8, DEFAULTS_V9, DEFAULTS_V10,
    render_crt, render_crt_v3, render_crt_v4, render_crt_v5, render_crt_v6,
    render_crt_v7, render_crt_v8, render_crt_v9, render_crt_v10,
)
from models.dmg import (
    DEFAULTS_DMG, DEFAULTS_DMG_V2, DEFAULTS_DMG_V3, DEFAULTS_DMG_V4,
    DEFAULTS_DMG_V5, DEFAULTS_DMG_V6, DEFAULTS_DMG_V7, DEFAULTS_DMG_V8,
    render_dmg, render_dmg_v2, render_dmg_v3, render_dmg_v4, render_dmg_v5,
    render_dmg_v6, render_dmg_v7, render_dmg_v8,
)
from models.lcd import (
    # aliased: crt_preview exports a DEFAULTS_V3 of its own, and a bare
    # import here silently shadowed it, handing crt-perfect-v3 the LCD
    # defaults and a 255/255 mismatch that looked like a shader bug
    DEFAULTS_V3 as DEFAULTS_LCD_V3, render_lcd_v3,
    DEFAULTS_LCD, DEFAULTS_PP, DEFAULTS_PP_V2, DEFAULTS_PP_V3, DEFAULTS_PP_V4,
    DEFAULTS_PP_V5, DEFAULTS_PP_V6, DEFAULTS_V2A, DEFAULTS_V2B,
    render_pixel_perfect_v2, render_pixel_perfect_v3, render_pixel_perfect_v4,
    render_pixel_perfect_v5, render_pixel_perfect_v6,
    render_lcd, render_lcd_v2a, render_pixel_perfect,
)

# (label, source size, output size) - the scale factors that matter on the
# target: 3.20, 4.00, 4.27, 6.40 at 1024x768, and 2.00, 2.50, 2.67 at 640x480,
# which are the awkward ones.
CASES = [
    ("240p -> 1024x768", (320, 240), (1024, 768)),
    ("224p -> 1024x768", (256, 224), (1024, 768)),
    ("NDS  -> 1024x768", (256, 192), (1024, 768)),
    ("GBA  -> 1024x768", (240, 160), (1024, 768)),
    ("GB   -> 1024x768", (160, 144), (1024, 768)),
    # PSP is the awkward one: 2.13 output pixels per cell across at 1024x768 and
    # only 1.33 at 640x480, which is below the two per cycle a pattern needs.
    ("PSP  -> 1024x768", (480, 272), (1024, 768)),
    ("PSP  ->  640x480", (480, 272), (640, 480)),
    ("240p ->  640x480", (320, 240), (640, 480)),
    ("NDS  ->  640x480", (256, 192), (640, 480)),
    ("240p -> 1280x720", (320, 240), (1280, 720)),
]

DEFAULT_SOURCES = ("scene", "bars", "white")


class Model:
    """A shader, its numpy twin, and the parameter sets to check them under.

    tolerance is in 8-bit levels and defaults to 1, which is pure
    float32-vs-float64 rounding. Raising it requires a reason: a divergence that
    has been traced to a mechanism and measured, not one that has been shrugged
    at. The reason is printed next to the result.
    """

    def __init__(self, render, defaults, variants=(), sources=DEFAULT_SOURCES,
                 cases=None, tolerance=1, reason="", outliers=0):
        self.render = render
        self.defaults = defaults
        # (label, param overrides) - defaults are always checked as well
        self.variants = list(variants)
        self.sources = sources
        self.cases = cases or CASES
        self.tolerance = tolerance
        self.reason = reason
        # How many individual pixels per case may be ignored before the
        # tolerance is applied. This is for knife-edge disagreements - a pixel
        # sitting within a few ULP of a decision boundary, where float32 and
        # float64 legitimately land on opposite sides - which are unbounded in
        # amplitude but countable. Raising `tolerance` to cover them would blind
        # the check to a real systematic error of the same size; this does not,
        # and the count is printed so it cannot creep up unnoticed.
        self.outliers = outliers


# v1 to v3 predate the epsilon in the slot mask's row-parity floor(). Their
# argument crosses a whole number once per output line, so a few ULP flip an
# entire row's stagger - which is exactly the trap AGENTS.md records, and which
# v4 fixed with floor(x + 1e-3). Kept failing loudly would be noise; kept silent
# would lose the record. So they are tolerated with the mechanism named.
PARITY = ("pre-v4 slot mask: row parity from a bare floor(), flips a whole row "
          "on a few ULP at some scales; fixed in v4 by floor(x + 1e-3)")

# Note for the next person who drives a modulation to exactly 0: sqrt() has
# unbounded slope there, so the ~1e-5 float32 error already in the interpolated
# texcoord lands in the output magnified, and this check reads 3/255 rather than
# 1 with no logic error anywhere. It is confirmable by re-running the model in
# float32. lcd-perfect used to trip it; peak-normalising its modulation, which it
# does for unrelated reasons, keeps it off zero and the check back at 1.


REGISTRY = {
    # --- shipped ---------------------------------------------------------------
    "crt-perfect.glsl": Model(
        render=lambda s, w, h, p: render_crt_v5(s, w, h, p, after=True),
        defaults=DEFAULTS_V5,
        variants=[
            ("effects off", dict(cp_scanlines=0.0, cp_rgb_mask=0.0,
                                 cp_brightness=1.0)),
            ("slot mask", dict(cp_mask_type=2.0)),
            ("gamma 0.7", dict(cp_gamma=0.7)),
            ("gamma 1.6", dict(cp_gamma=1.6)),
        ],
    ),
    "crt-perfect-v10.glsl": Model(
        render=render_crt_v10,
        defaults=DEFAULTS_V10,
        variants=[
            ("curvature 0.05", dict(cp_curvature=0.05)),
            ("curvature 0.10", dict(cp_curvature=0.10)),
            ("curvature 0.15", dict(cp_curvature=0.15)),
            ("curved slot mask", dict(cp_curvature=0.10, cp_mask_type=2.0)),
            ("curved gamma 1.6", dict(cp_curvature=0.10, cp_gamma=1.6)),
            ("curved, mask off", dict(cp_curvature=0.10, cp_rgb_mask=0.0)),
        ],
        outliers=32,
        reason="slot-mask row parity: floor() knife-edge under warp, where the "
               "argument must cross an integer and float32/float64 disagree on "
               "which side; isolated pixels, never a region",
    ),
    "crt-perfect-v9.glsl": Model(
        render=render_crt_v9,
        defaults=DEFAULTS_V9,
        variants=[
            ("curvature 0.05", dict(cp_curvature=0.05)),
            ("curvature 0.10", dict(cp_curvature=0.10)),
            ("curvature 0.15", dict(cp_curvature=0.15)),
            ("curved slot mask", dict(cp_curvature=0.10, cp_mask_type=2.0)),
            ("curved gamma 1.6", dict(cp_curvature=0.10, cp_gamma=1.6)),
            ("curved, mask off", dict(cp_curvature=0.10, cp_rgb_mask=0.0)),
        ],
        # Same warped-parity knife edge as v7 and v8; the band-limiting change
        # does not touch the slot mask's row floor().
        outliers=32,
        reason="slot-mask row parity: floor() knife-edge under warp, where the "
               "argument must cross an integer and float32/float64 disagree on "
               "which side; isolated pixels, never a region",
    ),
    "crt-perfect-v8.glsl": Model(
        render=render_crt_v8,
        defaults=DEFAULTS_V8,
        variants=[
            ("curvature 0.05", dict(cp_curvature=0.05)),
            ("curvature 0.10", dict(cp_curvature=0.10)),
            ("curvature 0.15", dict(cp_curvature=0.15)),
            ("curved slot mask", dict(cp_curvature=0.10, cp_mask_type=2.0)),
            ("curved gamma 1.6", dict(cp_curvature=0.10, cp_gamma=1.6)),
            ("curved, mask off", dict(cp_curvature=0.10, cp_rgb_mask=0.0)),
        ],
        # Same knife edge as v7, and for the same reason: warping the slot
        # mask's row-parity floor() argument makes it cross integers across the
        # frame, where float32 and float64 can disagree. It is a property of
        # warping the parity, not of which constant the warp is normalised by.
        outliers=32,
        reason="slot-mask row parity: floor() knife-edge under warp, where the "
               "argument must cross an integer and float32/float64 disagree on "
               "which side; isolated pixels, never a region",
    ),
    "crt-perfect-v7.glsl": Model(
        render=render_crt_v7,
        defaults=DEFAULTS_V7,
        variants=[
            ("curvature 0.05", dict(cp_curvature=0.05)),
            ("curvature 0.10", dict(cp_curvature=0.10)),
            ("curved slot mask", dict(cp_curvature=0.10, cp_mask_type=2.0)),
            ("curved gamma 1.6", dict(cp_curvature=0.10, cp_gamma=1.6)),
            ("curved, mask off", dict(cp_curvature=0.10, cp_rgb_mask=0.0)),
            ("curved, big triads", dict(cp_curvature=0.10, cp_mask_size=0.5)),
        ],
        # The slot mask picks its row parity with floor(), and under curvature
        # that argument varies smoothly across the frame instead of being
        # constant along a row - so it *must* cross an integer somewhere, and
        # wherever it does, float32 and float64 can land on opposite sides and
        # the pixel takes the other row's half-cell stagger. No epsilon fixes
        # this; an epsilon only moves where the crossing happens. Measured at
        # curvature 0.10: 16 pixels of 786432, every one within 1.9e-5 of an
        # integer against a median distance of 0.25. Isolated single pixels,
        # invisible in practice, and only ever on the slot mask.
        outliers=32,
        reason="slot-mask row parity: floor() knife-edge under warp, where the "
               "argument must cross an integer and float32/float64 disagree on "
               "which side; isolated pixels, never a region",
    ),
    "crt-perfect-v6.glsl": Model(
        render=render_crt_v6,
        defaults=DEFAULTS_V6,
        variants=[
            ("curvature 0.05", dict(cp_curvature=0.05)),
            ("curvature 0.10", dict(cp_curvature=0.10)),
            ("curvature 0.15", dict(cp_curvature=0.15)),
            ("curved slot mask", dict(cp_curvature=0.10, cp_mask_type=2.0)),
            ("curved gamma 1.6", dict(cp_curvature=0.10, cp_gamma=1.6)),
        ],
    ),
    "lcd-perfect-v1.glsl": Model(
        render=render_lcd,
        defaults=DEFAULTS_LCD,
        variants=[
            ("effects off", dict(lp_grid=0.0, lp_subpixels=0.0)),
            ("grid only", dict(lp_subpixels=0.0)),
            ("stripes only", dict(lp_grid=0.0, lp_subpixels=1.0)),
            ("BGR", dict(lp_layout=1.0, lp_subpixels=1.0)),
            ("fat matrix", dict(lp_gap=0.35, lp_grid=1.0)),
            ("gamma 0.7", dict(lp_gamma=0.7)),
            ("gamma 1.6", dict(lp_gamma=1.6)),
            ("bright", dict(lp_brightness=1.6)),
        ],
    ),
    "lcd-perfect-v2b.glsl": Model(
        render=lambda s, w, h, p: render_lcd(s, w, h, p, balance=True),
        defaults=DEFAULTS_V2B,
        variants=[
            ("effects off", dict(lp_grid=0.0, lp_subpixels=0.0)),
            ("grid only", dict(lp_subpixels=0.0)),
            ("rows only", dict(lp_balance=0.0)),
            ("columns only", dict(lp_balance=1.0)),
            ("even balance", dict(lp_balance=0.5)),
            ("fat matrix", dict(lp_gap=0.35, lp_grid=1.0)),
            ("stripes only", dict(lp_grid=0.0, lp_subpixels=1.0)),
            ("BGR", dict(lp_layout=1.0, lp_subpixels=1.0)),
            ("gamma 0.7", dict(lp_gamma=0.7)),
            ("gamma 1.6", dict(lp_gamma=1.6)),
        ],
    ),
    "lcd-perfect-v2a.glsl": Model(
        render=render_lcd_v2a,
        defaults=DEFAULTS_V2A,
        variants=[
            ("effects off", dict(lp_grid=0.0, lp_subpixels=0.0)),
            ("grid only", dict(lp_subpixels=0.0)),
            ("rows only", dict(lp_balance=0.0)),
            ("columns only", dict(lp_balance=1.0)),
            ("even balance", dict(lp_balance=0.5)),
            ("full grid", dict(lp_grid=1.0)),
            ("stripes only", dict(lp_grid=0.0, lp_subpixels=1.0)),
            ("BGR", dict(lp_layout=1.0, lp_subpixels=1.0)),
            ("gamma 0.7", dict(lp_gamma=0.7)),
            ("gamma 1.6", dict(lp_gamma=1.6)),
            ("bright", dict(lp_brightness=1.6)),
        ],
    ),
    "lcd-perfect.glsl": Model(
        render=render_lcd_v3,
        defaults=DEFAULTS_LCD_V3,
        variants=[
            ("effects off", dict(lp_grid=0.0, lp_subpixels=0.0)),
            ("mesh only", dict(lp_subpixels=0.0)),
            ("rows only", dict(lp_balance=0.0)),
            ("columns only", dict(lp_balance=1.0)),
            ("stripes full", dict(lp_subpixels=1.0)),
            ("BGR", dict(lp_layout=1.0, lp_subpixels=1.0)),
            # both sides of the regime boundary, which is the whole point of v3
            ("min pitch 2", dict(lp_min_pitch=2.0)),
            ("min pitch 6", dict(lp_min_pitch=6.0)),
            ("gamma 0.7", dict(lp_gamma=0.7)),
            ("bright", dict(lp_brightness=1.6)),
        ],
    ),
    "pixel-perfect-v2.glsl": Model(
        render=render_pixel_perfect_v2,
        defaults=DEFAULTS_PP_V2,
        variants=[
            ("crisp", dict(pp_sharpness=0.3)),
            ("gamma 0.7", dict(pp_gamma=0.7)),
            ("gamma 1.4", dict(pp_gamma=1.4)),
            ("gamma 2.0", dict(pp_gamma=2.0)),
            ("crisp + gamma", dict(pp_sharpness=0.3, pp_gamma=0.8)),
        ],
    ),
    "pixel-perfect-v6.glsl": Model(
        render=render_pixel_perfect_v6,
        defaults=DEFAULTS_PP_V6,
        variants=[
            ("greyscale", dict(pp_saturation=0.0)),
            ("flat", dict(pp_contrast=0.4)),
            ("dim", dict(pp_brightness=0.6)),
            ("clipped gain", dict(pp_brightness=2.0)),
            ("gamma 1.4", dict(pp_gamma=1.4)),
            # each axis alone and both signs, so a swapped basis vector or a
            # sign error cannot hide behind the other axis
            ("warm", dict(pp_temperature=0.20)),
            ("cool", dict(pp_temperature=-0.20)),
            ("magenta", dict(pp_tint=0.20)),
            ("green", dict(pp_tint=-0.20)),
            # the corner where a channel gain goes negative, which only the
            # clamp saves
            ("cool + magenta, extreme", dict(pp_temperature=-1.0, pp_tint=1.0)),
            ("warm, extreme", dict(pp_temperature=1.0)),
            ("balance + grade", dict(pp_temperature=0.15, pp_tint=-0.08,
                                     pp_saturation=1.3, pp_contrast=1.2,
                                     pp_brightness=1.1)),
            ("balance + greyscale", dict(pp_temperature=0.2,
                                         pp_saturation=0.0)),
            # axes that cancel in a sum but not when tested separately
            ("cancelling axes", dict(pp_temperature=0.2, pp_tint=-0.2)),
        ],
    ),
    "pixel-perfect-v5.glsl": Model(
        render=render_pixel_perfect_v5,
        defaults=DEFAULTS_PP_V5,
        variants=[
            # the grade v4 already had, so the fold is checked against every
            # setting it used to handle rather than only against neutral
            ("greyscale", dict(pp_saturation=0.0)),
            ("flat", dict(pp_contrast=0.4)),
            ("dim", dict(pp_brightness=0.6)),
            ("clipped gain", dict(pp_brightness=2.0)),
            ("gamma 1.4", dict(pp_gamma=1.4)),
            # each channel on its own, so a swapped coefficient cannot hide
            ("red only", dict(pp_red=1.4)),
            ("green only", dict(pp_green=1.4)),
            ("blue only", dict(pp_blue=1.4)),
            ("red killed", dict(pp_red=0.0)),
            # the realistic uses: warm and cool by pulling channels down
            ("warm", dict(pp_blue=0.85, pp_green=0.95)),
            ("cool", dict(pp_red=0.85, pp_green=0.95)),
            ("clipping trim", dict(pp_red=2.0, pp_green=2.0, pp_blue=2.0)),
            # the trim interacting with the rest of the fold, which is where a
            # coefficient that is right alone but wrong in composition shows
            ("trim + grade", dict(pp_red=1.2, pp_blue=0.8, pp_saturation=1.4,
                                  pp_contrast=1.2, pp_brightness=1.1)),
            ("trim + greyscale", dict(pp_red=1.3, pp_blue=0.7,
                                      pp_saturation=0.0)),
            # gains that cancel in a sum but not when tested separately
            ("cancelling trim", dict(pp_red=1.1, pp_green=0.9)),
        ],
    ),
    "pixel-perfect-v4.glsl": Model(
        render=render_pixel_perfect_v4,
        defaults=DEFAULTS_PP_V4,
        variants=[
            ("greyscale", dict(pp_saturation=0.0)),
            ("oversaturated", dict(pp_saturation=1.8)),
            ("flat", dict(pp_contrast=0.4)),
            ("punchy", dict(pp_contrast=1.6)),
            ("dim", dict(pp_brightness=0.6)),
            ("gamma 0.7", dict(pp_gamma=0.7)),
            ("gamma 1.4", dict(pp_gamma=1.4)),
            ("clipped gain", dict(pp_brightness=2.0)),
            ("clipped contrast", dict(pp_contrast=2.0)),
            ("full grade", dict(pp_saturation=1.3, pp_contrast=1.2,
                                pp_brightness=1.1, pp_gamma=0.9)),
            # Near-neutral but not neutral: the guard is exact, so these take
            # the branch and must reproduce v3 exactly. A guard written with an
            # epsilon would skip them and quietly disagree with v3 over a whole
            # range of settings.
            ("barely graded", dict(pp_contrast=1.0003)),
            ("barely desaturated", dict(pp_saturation=0.9995)),
            # deviations that cancel in a sum of values but not when tested
            # separately; this is the shape a summed guard gets wrong
            ("cancelling deviations", dict(pp_brightness=1.1, pp_contrast=0.9)),
        ],
    ),
    "pixel-perfect-v3.glsl": Model(
        render=render_pixel_perfect_v3,
        defaults=DEFAULTS_PP_V3,
        variants=[
            # each control alone, both sides of neutral, so a sign error on one
            # cannot hide behind another
            ("greyscale", dict(pp_saturation=0.0)),
            ("oversaturated", dict(pp_saturation=1.8)),
            ("flat", dict(pp_contrast=0.4)),
            ("punchy", dict(pp_contrast=1.6)),
            ("dim", dict(pp_brightness=0.6)),
            ("gamma 0.7", dict(pp_gamma=0.7)),
            ("gamma 1.4", dict(pp_gamma=1.4)),
            # the clipping cases: the affine chain is exact, so these are the
            # only configurations where the post-blend clamp does anything
            ("clipped gain", dict(pp_brightness=2.0)),
            ("clipped contrast", dict(pp_contrast=2.0)),
            # the whole chain at once, which is where a fold that is right
            # term-by-term but wrong in composition would show
            ("full grade", dict(pp_saturation=1.3, pp_contrast=1.2,
                                pp_brightness=1.1, pp_gamma=0.9)),
        ],
    ),
    "pixel-perfect.glsl": Model(
        render=render_pixel_perfect,
        defaults=DEFAULTS_PP,
        variants=[("crisp", dict(pp_sharpness=0.3))],
    ),
    "dmg-perfect-v8.glsl": Model(
        render=render_dmg_v8,
        defaults=DEFAULTS_DMG_V8,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("full grid", dict(dp_grid=1.0)),
            ("thin line", dict(dp_gap=0.25)),
            ("fat line", dict(dp_gap=2.0)),
            ("shadow", dict(dp_shadow=0.45)),
            ("shadow strong", dict(dp_shadow=1.0)),
            ("shadow + fat", dict(dp_shadow=0.5, dp_gap=1.75)),
            ("shadow + bright", dict(dp_shadow=0.5, dp_brightness=1.6)),
            # the contrast wheel across its range. 0.00 is the whole picture
            # washed out into undriven panel, which is the one setting where
            # the substrate being the map's fixed point is visible rather than
            # merely convenient - the gaps must not move while everything else
            # collapses onto them.
            ("contrast 0.90", dict(dp_contrast=0.90)),
            ("contrast 0.65", dict(dp_contrast=0.65)),
            ("contrast 0.30", dict(dp_contrast=0.30)),
            ("contrast zero", dict(dp_contrast=0.0)),
            ("contrast + shadow", dict(dp_contrast=0.7, dp_shadow=0.5)),
            ("contrast + grid", dict(dp_contrast=0.7, dp_grid=0.8)),
            ("contrast + tone",
             dict(dp_contrast=0.75, dp_brightness=1.2, dp_gamma=1.4)),
            ("warm", dict(dp_green=0.94, dp_blue=0.85)),
            ("cool", dict(dp_red=0.88, dp_green=0.96)),
            ("trim past 1", dict(dp_red=1.4, dp_blue=1.2)),
            ("trim + shadow", dict(dp_shadow=0.5, dp_red=0.9, dp_blue=1.1)),
            ("reference tone", dict(dp_brightness=1.2, dp_gamma=1.4)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
        ],
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 4x integer", (160, 144), (640, 576)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB aspect 1024x768", (160, 144), (853, 768)),
            ("GB fill   1024x768", (160, 144), (1024, 768)),
            ("GB aspect  640x480", (160, 144), (533, 480)),
            ("GB fill    640x480", (160, 144), (640, 480)),
            ("GBA fill  1024x768", (240, 160), (1024, 768)),
        ],
    ),
    "dmg-perfect-v7.glsl": Model(
        render=render_dmg_v7,
        defaults=DEFAULTS_DMG_V7,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("full grid", dict(dp_grid=1.0)),
            ("thin line", dict(dp_gap=0.25)),
            ("fat line", dict(dp_gap=2.0)),
            ("shadow", dict(dp_shadow=0.45)),
            ("shadow strong", dict(dp_shadow=1.0)),
            ("shadow + fat", dict(dp_shadow=0.5, dp_gap=1.75)),
            ("shadow + bright", dict(dp_shadow=0.5, dp_brightness=1.6)),
            ("warm", dict(dp_green=0.94, dp_blue=0.85)),
            ("cool", dict(dp_red=0.88, dp_green=0.96)),
            ("trim past 1", dict(dp_red=1.4, dp_blue=1.2)),
            ("trim + shadow", dict(dp_shadow=0.5, dp_red=0.9, dp_blue=1.1)),
            ("reference tone", dict(dp_brightness=1.2, dp_gamma=1.4)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
        ],
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 4x integer", (160, 144), (640, 576)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB aspect 1024x768", (160, 144), (853, 768)),
            ("GB fill   1024x768", (160, 144), (1024, 768)),
            ("GB aspect  640x480", (160, 144), (533, 480)),
            ("GB fill    640x480", (160, 144), (640, 480)),
            ("GBA fill  1024x768", (240, 160), (1024, 768)),
        ],
    ),
    "dmg-perfect-v6.glsl": Model(
        render=render_dmg_v6,
        defaults=DEFAULTS_DMG_V6,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("shadow", dict(dp_shadow=0.45)),
            # both ends of the blur, and the point where it collapses to v5
            # blur is deliberately not taken to 0 here. At 0 the weight is a
            # hard step at the half-cell, so the GPU and a float64 model pick
            # opposite sides wherever the shifted point lands near it - an
            # unstable selection, not an arithmetic difference, and it measures
            # 11/255 over half a percent of the frame. It is a degenerate
            # setting of a softness control rather than a mode anyone runs, and
            # v7 removes the parameter precisely because nothing below full
            # softness was worth keeping.
            ("blur low", dict(dp_shadow=0.6, dp_shadow_blur=0.1)),
            ("blur full", dict(dp_shadow=0.6, dp_shadow_blur=1.0)),
            ("blur mid", dict(dp_shadow=0.6, dp_shadow_blur=0.30)),
            ("shadow + fat", dict(dp_shadow=0.5, dp_gap=1.75)),
            ("warm", dict(dp_green=0.94, dp_blue=0.85)),
            ("trim + shadow", dict(dp_shadow=0.5, dp_red=0.9, dp_blue=1.1)),
            ("reference tone", dict(dp_brightness=1.2, dp_gamma=1.4)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
        ],
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB aspect 1024x768", (160, 144), (853, 768)),
            ("GB fill   1024x768", (160, 144), (1024, 768)),
            ("GB aspect  640x480", (160, 144), (533, 480)),
            ("GB fill    640x480", (160, 144), (640, 480)),
        ],
    ),
    "dmg-perfect-v5.glsl": Model(
        render=render_dmg_v5,
        defaults=DEFAULTS_DMG_V5,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("full grid", dict(dp_grid=1.0)),
            ("thin line", dict(dp_gap=0.25)),
            ("fat line", dict(dp_gap=2.0)),
            ("shadow", dict(dp_shadow=0.45)),
            ("shadow strong", dict(dp_shadow=1.0)),
            ("shadow + fat", dict(dp_shadow=0.5, dp_gap=1.75)),
            ("shadow + bright", dict(dp_shadow=0.5, dp_brightness=1.6)),
            # the trim is a uniform branch, so both sides of it get exercised
            ("warm", dict(dp_green=0.94, dp_blue=0.85)),
            ("cool", dict(dp_red=0.88, dp_green=0.96)),
            ("red only", dict(dp_green=0.0, dp_blue=0.0)),
            ("trim past 1", dict(dp_red=1.4, dp_blue=1.2)),
            ("trim + shadow", dict(dp_shadow=0.5, dp_red=0.9, dp_blue=1.1)),
            ("trim + gamma", dict(dp_red=0.9, dp_gamma=1.4)),
            ("reference tone", dict(dp_brightness=1.2, dp_gamma=1.4)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
        ],
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 4x integer", (160, 144), (640, 576)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB aspect 1024x768", (160, 144), (853, 768)),
            ("GB fill   1024x768", (160, 144), (1024, 768)),
            ("GB aspect  640x480", (160, 144), (533, 480)),
            ("GB fill    640x480", (160, 144), (640, 480)),
            ("GBA fill  1024x768", (240, 160), (1024, 768)),
        ],
    ),
    "dmg-perfect-v4.glsl": Model(
        render=render_dmg_v4,
        defaults=DEFAULTS_DMG_V4,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("full grid", dict(dp_grid=1.0)),
            ("thin line", dict(dp_gap=0.25)),
            ("fat line", dict(dp_gap=2.0)),
            ("shadow", dict(dp_shadow=0.35)),
            ("shadow strong", dict(dp_shadow=0.8)),
            # both offsets to zero puts the shadow exactly under its own dot,
            # which is where the displaced aperture and the real one coincide
            ("shadow no offset", dict(dp_shadow=0.5, dp_shadow_x=0.0,
                                      dp_shadow_y=0.0)),
            ("shadow far", dict(dp_shadow=0.5, dp_shadow_x=3.0,
                                dp_shadow_y=3.0)),
            ("shadow sideways", dict(dp_shadow=0.5, dp_shadow_x=2.0,
                                     dp_shadow_y=0.0)),
            ("shadow + fat", dict(dp_shadow=0.5, dp_gap=1.75)),
            ("shadow + bright", dict(dp_shadow=0.5, dp_brightness=1.6)),
            ("shadow + gamma", dict(dp_shadow=0.5, dp_gamma=1.4)),
            ("reference tone", dict(dp_brightness=1.2, dp_gamma=1.4)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
        ],
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 4x integer", (160, 144), (640, 576)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB aspect 1024x768", (160, 144), (853, 768)),
            ("GB fill   1024x768", (160, 144), (1024, 768)),
            ("GB aspect  640x480", (160, 144), (533, 480)),
            ("GB fill    640x480", (160, 144), (640, 480)),
            ("GBA fill  1024x768", (240, 160), (1024, 768)),
        ],
    ),
    "dmg-perfect-v3.glsl": Model(
        render=render_dmg_v3,
        defaults=DEFAULTS_DMG_V3,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("full grid", dict(dp_grid=1.0)),
            ("thin line", dict(dp_gap=0.25)),
            ("fat line", dict(dp_gap=2.0)),
            # the shadow is the whole point of v3, so it is exercised at both
            # ends and against a source dark enough to drive the caster hard
            ("shadow", dict(dp_shadow=0.15)),
            ("shadow strong", dict(dp_shadow=0.6)),
            ("shadow near", dict(dp_shadow=0.4, dp_shadow_offset=0.25)),
            ("shadow far", dict(dp_shadow=0.4, dp_shadow_offset=3.0)),
            ("shadow + fat", dict(dp_shadow=0.4, dp_gap=1.75)),
            ("shadow + dim", dict(dp_shadow=0.4, dp_brightness=0.5)),
            ("reference tone", dict(dp_brightness=1.2, dp_gamma=1.4)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
            ("bright", dict(dp_brightness=1.6)),
        ],
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 4x integer", (160, 144), (640, 576)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB aspect 1024x768", (160, 144), (853, 768)),
            ("GB fill   1024x768", (160, 144), (1024, 768)),
            ("GB aspect  640x480", (160, 144), (533, 480)),
            ("GB fill    640x480", (160, 144), (640, 480)),
            ("GBA fill  1024x768", (240, 160), (1024, 768)),
        ],
    ),
    "dmg-perfect-v2.glsl": Model(
        render=render_dmg_v2,
        defaults=DEFAULTS_DMG_V2,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("full grid", dict(dp_grid=1.0)),
            ("thin line", dict(dp_gap=0.25)),
            ("fat line", dict(dp_gap=2.0)),
            ("shadow", dict(dp_shadow=0.35)),
            ("shadow far", dict(dp_shadow=0.6, dp_shadow_offset=2.5)),
            ("shadow + fat", dict(dp_shadow=0.5, dp_gap=1.75)),
            ("reference tone", dict(dp_brightness=1.2, dp_gamma=1.4)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
            ("bright", dict(dp_brightness=1.6)),
        ],
        # Both fill modes: a frontend either letterboxes, giving the same whole
        # scale on each axis, or stretches, giving different ones - and under a
        # stretch the two axes get different line widths on purpose, because the
        # two-pass pipeline stretches its 1px lines unequally too.
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 4x integer", (160, 144), (640, 576)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB aspect 1024x768", (160, 144), (853, 768)),
            ("GB fill   1024x768", (160, 144), (1024, 768)),
            ("GB aspect  640x480", (160, 144), (533, 480)),
            ("GB fill    640x480", (160, 144), (640, 480)),
            ("GBA fill  1024x768", (240, 160), (1024, 768)),
        ],
    ),
    "dmg-perfect-v1.glsl": Model(
        render=render_dmg,
        defaults=DEFAULTS_DMG,
        variants=[
            ("grid off", dict(dp_grid=0.0)),
            ("gap off", dict(dp_gap=0.0)),
            ("full grid", dict(dp_grid=1.0)),
            ("dark matrix", dict(dp_level=0.0)),
            ("fat gap", dict(dp_gap=0.45)),
            ("thin gap", dict(dp_gap=0.05)),
            ("gamma off", dict(dp_gamma=1.0)),
            ("gamma 0.7", dict(dp_gamma=0.7)),
            ("bright", dict(dp_brightness=1.6)),
            # both sides of the gap floor's room limit, which is the one
            # regime boundary in the shader
            ("dim", dict(dp_brightness=0.5)),
        ],
        # a Game Boy is the only source this shader is for, so the awkward
        # scales are its own: 5x letterboxed, 6.40x5.33 filled, and 4.00x3.33
        # at the minimum supported output
        cases=[
            ("GB 5x integer", (160, 144), (800, 720)),
            ("GB 4x integer", (160, 144), (640, 576)),
            ("GB 3x integer", (160, 144), (480, 432)),
            ("GB   -> 1024x768", (160, 144), (1024, 768)),
            ("GB   ->  640x480", (160, 144), (640, 480)),
            ("GBA  -> 1024x768", (240, 160), (1024, 768)),
            ("GBA  ->  640x480", (240, 160), (640, 480)),
        ],
    ),
    # --- iterations, kept verified so the archive cannot rot -------------------
    "crt-perfect-v1.glsl": Model(
        render=render_crt,
        defaults=DEFAULTS,
        variants=[
            ("effects off", dict(Scanlines=0.0, RGB_Mask=0.0, Brightness=1.0)),
            ("slot mask", dict(Mask_Type=2.0)),
        ],
        tolerance=27, reason=PARITY,
    ),
    "crt-perfect-v2.glsl": Model(
        render=lambda s, w, h, p: render_crt(s, w, h, p, v2=True),
        defaults=DEFAULTS_V2,
        variants=[("slot mask", dict(Mask_Type=2.0))],
        tolerance=23, reason=PARITY,
    ),
    "crt-perfect-v3.glsl": Model(
        render=render_crt_v3,
        defaults=DEFAULTS_V3,
        variants=[("slot mask", dict(Mask_Type=2.0))],
        tolerance=26, reason=PARITY,
    ),
    "crt-perfect-v4.glsl": Model(
        render=render_crt_v4,
        defaults=DEFAULTS_V4,
        variants=[("slot mask", dict(Mask_Type=2.0))],
    ),
    # Applies cp_gamma to the four taps instead of to the scaled image, so it
    # holds the moire fix at every gamma where the shipped shader does not
    # (0.13 flat, against 1.68 at gamma 1.4). Costs 32 SFU slots against 14.
    # Superseded on cost, not on quality - keep it reachable.
    "crt-perfect-v5.glsl": Model(
        render=render_crt_v5,
        defaults=DEFAULTS_V5,
        variants=[
            ("slot mask", dict(cp_mask_type=2.0)),
            ("gamma 0.7", dict(cp_gamma=0.7)),
            ("gamma 1.6", dict(cp_gamma=1.6)),
        ],
    ),
}
