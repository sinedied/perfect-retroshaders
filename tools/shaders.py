"""Which numpy model belongs to which shader, and what to check it with.

gl_check.py walks this registry: for every entry it compiles the real shipped
.glsl, runs it on the GPU, runs the model over the same input, and diffs. The two
implementations are independent on purpose - an error has to be made identically
in GLSL and in numpy to slip through.

Add a shader by adding an entry. Nothing else needs wiring.
"""

from crt_preview import (
    DEFAULTS, DEFAULTS_V2, DEFAULTS_V3, DEFAULTS_V4, DEFAULTS_V5,
    render_crt, render_crt_v3, render_crt_v4, render_crt_v5,
)
from lcd_preview import (
    # aliased: crt_preview exports a DEFAULTS_V3 of its own, and a bare
    # import here silently shadowed it, handing crt-perfect-v3 the LCD
    # defaults and a 255/255 mismatch that looked like a shader bug
    DEFAULTS_V3 as DEFAULTS_LCD_V3, render_lcd_v3,
    DEFAULTS_LCD, DEFAULTS_PP, DEFAULTS_PP_V2, DEFAULTS_V2A, DEFAULTS_V2B,
    render_pixel_perfect_v2,
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
                 cases=None, tolerance=1, reason=""):
        self.render = render
        self.defaults = defaults
        # (label, param overrides) - defaults are always checked as well
        self.variants = list(variants)
        self.sources = sources
        self.cases = cases or CASES
        self.tolerance = tolerance
        self.reason = reason


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
    "pixel-perfect.glsl": Model(
        render=render_pixel_perfect,
        defaults=DEFAULTS_PP,
        variants=[("crisp", dict(pp_sharpness=0.3))],
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
