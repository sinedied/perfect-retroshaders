#!/usr/bin/env python3
"""Render PNG comparisons of the shaders, so a look can be judged by eye.

Everything else in tools/ reports numbers. Numbers settle whether a shader is
correct and what it costs; they do not settle whether it looks right, and this
repo's shaders exist to look right.

Renders on the GPU through the same path gl_check.py uses, so vendored shaders
appear alongside ours under identical conditions - a comparison against lcd1x is
only worth anything if lcd1x went through the same scaler-free pipeline it
normally does, at the same scale, on the same source.

Output goes to tools/preview/, which is gitignored.

Run:  cd tools && PYTHONPATH=. ../.venv/bin/python preview.py
      ... preview.py --crop 240      crop to a 240px square instead of scaling
      ... preview.py lcd1x.glsl lcd-perfect-v2a.glsl
"""

import os
import sys

import numpy as np
from PIL import Image

import moderngl

from crt_preview import SOURCES
from gl_check import gl_render, stage_source
from paths import TOOLS, list_shaders, shader_path
from shaders import REGISTRY

OUT = os.path.join(TOOLS, "preview")

# The scales that matter on the target, and what content sits at each.
CASES = [
    ("GB    160x144", (160, 144), (1024, 768)),
    ("GBA   240x160", (240, 160), (1024, 768)),
    ("NDS   256x192", (256, 192), (1024, 768)),
    ("240p  320x240", (320, 240), (1024, 768)),
    ("240p  320x240", (320, 240), (640, 480)),
    ("GB    160x144", (160, 144), (640, 480)),
]

# Vendored references have no entry in the registry, so their parameters live
# here. Anything not listed renders at whatever its #pragma defaults are.
VENDOR_PARAMS = {
    "lcd1x.glsl": dict(BRIGHTEN_SCANLINES=16.0, BRIGHTEN_LCD=4.0),
    "lcd3x.glsl": {},
    "sharp-shimmerless-grid.glsl": dict(GRID_RATIO_X=0.3, GRID_RATIO_Y=0.3,
                                        GRID_OPACITY_X=0.3, GRID_OPACITY_Y=0.3),
    "pixellate.glsl": {},
}

LABEL_H = 14


def params_for(name):
    if name in REGISTRY:
        return dict(REGISTRY[name].defaults)
    return dict(VENDOR_PARAMS.get(name, {}))


def label(text, width):
    """A tiny 5x7 bitmap label, so the images are self-describing without
    depending on a font being installed."""
    from PIL import ImageDraw
    img = Image.new("RGB", (width, LABEL_H), (24, 24, 28))
    ImageDraw.Draw(img).text((4, 2), text, fill=(210, 210, 215))
    return np.asarray(img)


def render_one(ctx, name, src, out_w, out_h):
    txt = open(shader_path(name)).read()
    prog = ctx.program(vertex_shader=stage_source(txt, "vert"),
                       fragment_shader=stage_source(txt, "frag"))
    img = gl_render(ctx, prog, src, out_w, out_h, params_for(name))
    # the FBO readback is bottom-up, as GL always is
    return img[::-1]


def main(argv):
    crop = None
    if "--crop" in argv:
        i = argv.index("--crop")
        crop = int(argv[i + 1])
        del argv[i:i + 2]

    names = argv[1:] or [n for n in list_shaders() if n.startswith("lcd-")] + \
        ["lcd1x.glsl", "lcd3x.glsl"]
    missing = [n for n in names if not os.path.isfile(shader_path(n))]
    if missing:
        print(f"not found: {', '.join(missing)}")
        return 2

    os.makedirs(OUT, exist_ok=True)
    ctx = moderngl.create_standalone_context()

    for sname in ("white", "scene", "bars"):
        for case, (sw, sh), (ow, oh) in CASES:
            src = SOURCES[sname](sw, sh)
            tiles = []
            for name in names:
                try:
                    img = render_one(ctx, name, src, ow, oh)
                except Exception as exc:
                    print(f"  {name}: skipped ({str(exc)[:60]})")
                    continue
                if crop:
                    y0 = (oh - crop) // 2
                    x0 = (ow - crop) // 2
                    img = img[y0:y0 + crop, x0:x0 + crop]
                tiles.append(np.vstack([label(name.replace(".glsl", ""),
                                              img.shape[1]), img]))
            if not tiles:
                continue
            sheet = np.hstack(tiles)
            tag = f"{sname}_{sw}x{sh}_to_{ow}x{oh}" + (f"_crop{crop}" if crop else "")
            path = os.path.join(OUT, f"{tag}.png")
            Image.fromarray(sheet).save(path)
            print(f"wrote {path}   ({case} -> {ow}x{oh}, {len(tiles)} shaders)")

    print(f"\n{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
