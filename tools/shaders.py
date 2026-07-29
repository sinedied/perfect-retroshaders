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
    DEFAULTS_LCD, DEFAULTS_PP, render_lcd, render_pixel_perfect,
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

# lp_subpixels or lp_grid at full strength drives the modulation to exactly 0,
# and sqrt() has unbounded slope there, so the ~1e-5 float32 error already
# present in the interpolated texcoord lands in the output magnified. Confirmed
# by re-running the model itself in float32: it reproduces the same 3/255 on the
# same 6 columns of 1024. Defaults and every other variant sit at 1.
SQRT0 = ("full-strength modulation reaches 0, where sqrt() amplifies the float32 "
         "texcoord error; ~0.09% of pixels, reproduced by the model in float32")


REGISTRY = {
    "crt-perfect.glsl": Model(
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
    "crt-perfect-v5.glsl": Model(
        render=render_crt_v5,
        defaults=DEFAULTS_V5,
        variants=[
            ("slot mask", dict(cp_mask_type=2.0)),
            ("gamma 0.7", dict(cp_gamma=0.7)),
            ("gamma 1.6", dict(cp_gamma=1.6)),
        ],
    ),
    "crt-perfect-v5b.glsl": Model(
        render=lambda s, w, h, p: render_crt_v5(s, w, h, p, after=True),
        defaults=DEFAULTS_V5,
        variants=[("gamma 1.6", dict(cp_gamma=1.6))],
    ),
    "lcd-perfect.glsl": Model(
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
        tolerance=3, reason=SQRT0,
    ),
    "pixel-perfect.glsl": Model(
        render=render_pixel_perfect,
        defaults=DEFAULTS_PP,
        variants=[("crisp", dict(pp_sharpness=0.3))],
    ),
}
