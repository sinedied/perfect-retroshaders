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
      ... preview.py --zoom 4        magnify the tiles, nearest, after cropping
      ... preview.py --diff          add a row of differences against the FIRST
                                     shader named, amplified x8
      ... preview.py --only snes,psp  restrict the screenshots by name
      ... preview.py --samples DIR    where the screenshots live
      ... preview.py lcd1x.glsl lcd-perfect.glsl
"""

import os
import sys

import numpy as np
from PIL import Image

import moderngl

from models.crt import SOURCES
from core.gpu import gl_render
from core.shader_source import stage_source, pragma_defaults
from core import manifest
from core.paths import TOOLS, list_shaders, shader_path
from models.registry import REGISTRY

OUT = os.path.join(TOOLS, "preview")

# The scales that matter on the target, and what content sits at each.
CASES = [
    ("GB    160x144", (160, 144), (1024, 768)),
    ("GBA   240x160", (240, 160), (1024, 768)),
    ("NDS   256x192", (256, 192), (1024, 768)),
    ("SNES  256x224", (256, 224), (1024, 768)),
    ("240p  320x240", (320, 240), (1024, 768)),
    ("PSP   480x272", (480, 272), (1024, 768)),
    ("240p  320x240", (320, 240), (640, 480)),
    ("PSP   480x272", (480, 272), (640, 480)),
    ("GB    160x144", (160, 144), (640, 480)),
]

# Real screenshots beat synthetic patterns for judging a look: a white field
# shows what the grid does, a game frame shows whether you would want to play
# through it. These live in RetroShader Lab and are NOT copied here - they are
# third-party game captures under their own notice, and this repo is MIT.
SAMPLES_DEFAULT = os.path.expanduser(
    "~/projects/retroshader-lab/public/samples")

OUTPUTS = [(1024, 768), (640, 480)]

# Vendored references have no entry in the registry. Anything not listed renders
# at its own #pragma defaults; these are deliberate departures from them, and
# they LAYER ON TOP rather than replace - an empty dict here used to mean "no
# uniforms set at all", which is not the defaults but zero for every parameter.
VENDOR_PARAMS = {
    "lcd1x.glsl": dict(BRIGHTEN_SCANLINES=16.0, BRIGHTEN_LCD=4.0),
    "lcd3x.glsl": {},
    "sharp-shimmerless-grid.glsl": dict(GRID_RATIO_X=0.3, GRID_RATIO_Y=0.3,
                                        GRID_OPACITY_X=0.3, GRID_OPACITY_Y=0.3),
    "pixellate.glsl": {},
    "dmg_dot_matrix.glsl": dict(dmg_edge_alpha=0.3,
                                dmg_brightness_correction=1.2,
                                dmg_grid_lightness=1.0, dmg_gamma=1.4),
}

LABEL_H = 14

# Differences worth looking at here are 1-2/255, so an unamplified diff row is
# a black rectangle. 8 puts 1/255 at 8/255 - visible, and still far from
# saturating a real 30/255 disagreement.
DIFF_GAIN = 8

# Curvature defaults to 0, which is the right default for a shader and the wrong
# one for a preview - a curvature variant rendered flat looks identical to every
# other version and tells you nothing. Turn it on for anything that has it.
# Some parameters default to off because that is the right default for a
# shader and the wrong one for a picture of it: a curvature variant rendered
# flat is indistinguishable from every other version and says nothing. Keyed by
# parameter rather than by filename - listing v6, v7 and v8 by name meant v9 and
# v10 previewed flat the moment they existed, and the sheet looked fine.
PREVIEW_OVERRIDES = {
    "cp_curvature": 0.10,
}


def params_for(name):
    if name in REGISTRY:
        p = dict(REGISTRY[name].defaults)
        p.update({k: v for k, v in PREVIEW_OVERRIDES.items() if k in p})
        return p
    return dict(pragma_defaults(name), **VENDOR_PARAMS.get(name, {}))


def label(text, width):
    """A tiny 5x7 bitmap label, so the images are self-describing without
    depending on a font being installed."""
    from PIL import ImageDraw
    img = Image.new("RGB", (width, LABEL_H), (24, 24, 28))
    ImageDraw.Draw(img).text((4, 2), text, fill=(210, 210, 215))
    return np.asarray(img)


def border_grid(w=320, h=240, step=20):
    """A grid whose four edges are each a different colour.

    For geometry, not for looks. Anything that warps the image has to be judged
    on what happens to the *border*, and neither a screenshot nor a plain grid
    shows that: crt-perfect-v7 shipped having quietly cropped its entire border
    off-screen, which every number in the harness read as perfect and one look
    at this pattern makes obvious. Red top and bottom, blue left and right,
    green centre lines.
    """
    img = np.full((h, w, 3), 20, np.uint8)
    img[::step, :] = 255
    img[:, ::step] = 255
    img[0:3, :] = img[-3:, :] = (255, 60, 60)
    img[:, 0:3] = img[:, -3:] = (60, 160, 255)
    img[h // 2 - 2:h // 2 + 2, :] = (60, 255, 60)
    img[:, w // 2 - 2:w // 2 + 2] = (60, 255, 60)
    return img


def load_samples(folder, only=None):
    """Real screenshots, each at its console's native resolution, so the image
    itself decides the source size. Returns [] if the folder is not there."""
    out = []
    if not only or any(k in "border-grid" for k in only):
        out.append(("border-grid", border_grid()))
    if not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".png"):
            continue
        stem = fn[:-4]
        if only and not any(k in stem for k in only):
            continue
        img = Image.open(os.path.join(folder, fn)).convert("RGB")
        out.append((stem, np.asarray(img)))
    return out


def render_one(ctx, name, src, out_w, out_h):
    txt = open(shader_path(name)).read()
    prog = ctx.program(vertex_shader=stage_source(txt, "vert"),
                       fragment_shader=stage_source(txt, "frag"))
    # No flip. gl_render() already returns rows in the same order as the source
    # array - the texture upload and the framebuffer readback are both bottom-up,
    # so they cancel, which is exactly why gl_check.py can index the model
    # directly against it.
    #
    # This used to flip the source in and flip the result back. That pair is an
    # identity for *content*, so every screenshot came out the right way up and
    # nothing looked wrong for a year - but the shader ran on a flipped image, so
    # anything with a direction came out mirrored in y. A grid, a scanline and a
    # mask are all symmetric and cannot show it; dmg-perfect's cast shadow can,
    # and it rendered up-and-right here while gl_check.py had it down-and-right
    # from the same shader. Judge a handed effect only in this convention.
    return gl_render(ctx, prog, src, out_w, out_h, params_for(name),
                     filter_linear=manifest.sampler(name) == manifest.LINEAR)


def sheet_for(ctx, names, src, ow, oh, crop, zoom=1, diff=False):
    """One row per requested view: the renders, optionally a difference row.

    A side-by-side of two correct scalers is uninformative by construction -
    they agree, so the eye sees one picture four times and learns nothing. The
    difference row is what says *whether* they agree and by how much, and it is
    the only view that separates "the same shader" from "close enough to fool
    a screenshot". Amplified, because the interesting differences are 1/255.
    """
    imgs, tiles = [], []
    for name in names:
        try:
            img = render_one(ctx, name, src, ow, oh)
        except Exception as exc:
            print(f"  {name}: skipped ({str(exc)[:60]})")
            continue
        if crop:
            y0, x0 = (oh - crop) // 2, (ow - crop) // 2
            img = img[max(y0, 0):y0 + crop, max(x0, 0):x0 + crop]
        img = img.repeat(zoom, 0).repeat(zoom, 1)
        imgs.append((name, img))
        tiles.append(np.vstack([label(name.replace(".glsl", ""),
                                      img.shape[1]), img]))
    if not tiles:
        return None
    rows = [np.hstack(tiles)]
    if diff and len(imgs) > 1:
        ref_name, ref = imgs[0]
        drow = []
        for name, img in imgs:
            d = np.abs(img.astype(int) - ref.astype(int)).max(axis=2)
            amp = np.clip(d * DIFF_GAIN, 0, 255).astype(np.uint8)
            drow.append(np.vstack([
                label(f"diff x{DIFF_GAIN} vs {ref_name.replace('.glsl','')}"
                      f"  max {int(d.max())}/255", img.shape[1]),
                amp[..., None].repeat(3, 2)]))
        rows.append(np.hstack(drow))
    return np.vstack(rows)


def main(argv):
    crop = None
    if "--crop" in argv:
        i = argv.index("--crop")
        crop = int(argv[i + 1])
        del argv[i:i + 2]

    zoom = 1
    if "--zoom" in argv:
        i = argv.index("--zoom")
        zoom = int(argv[i + 1])
        del argv[i:i + 2]

    diff = "--diff" in argv
    if diff:
        argv.remove("--diff")

    samples_dir = SAMPLES_DEFAULT
    if "--samples" in argv:
        i = argv.index("--samples")
        samples_dir = os.path.expanduser(argv[i + 1])
        del argv[i:i + 2]

    only = None
    if "--only" in argv:
        i = argv.index("--only")
        only = argv[i + 1].split(",")
        del argv[i:i + 2]

    from core import manifest
    names = argv[1:] or [manifest.current(f) for f in manifest.families()]
    missing = [n for n in names if not os.path.isfile(shader_path(n))]
    if missing:
        print(f"not found: {', '.join(missing)}")
        return 2

    os.makedirs(OUT, exist_ok=True)
    ctx = moderngl.create_standalone_context()

    for sname in ("white", "scene", "bars"):
        for case, (sw, sh), (ow, oh) in CASES:
            sheet = sheet_for(ctx, names, SOURCES[sname](sw, sh), ow, oh,
                              crop, zoom, diff)
            if sheet is None:
                continue
            tag = (f"{sname}_{sw}x{sh}_to_{ow}x{oh}"
                   + (f"_crop{crop}" if crop else "")
                   + (f"_x{zoom}" if zoom > 1 else "")
                   + ("_diff" if diff else ""))
            path = os.path.join(OUT, f"{tag}.png")
            Image.fromarray(sheet).save(path)
            print(f"wrote {path}   ({case} -> {ow}x{oh})")

    samples = load_samples(samples_dir, only)
    if not samples:
        print(f"\nno screenshots at {samples_dir} - synthetic sources only."
              f"\npass --samples DIR to point at them.")
    for stem, src in samples:
        sh, sw = src.shape[:2]
        for ow, oh in OUTPUTS:
            sheet = sheet_for(ctx, names, src, ow, oh, crop, zoom, diff)
            if sheet is None:
                continue
            tag = (f"{stem}_to_{ow}x{oh}"
                   + (f"_crop{crop}" if crop else "")
                   + (f"_x{zoom}" if zoom > 1 else "")
                   + ("_diff" if diff else ""))
            path = os.path.join(OUT, f"{tag}.png")
            Image.fromarray(sheet).save(path)
            print(f"wrote {path}   ({sw}x{sh} -> {ow}x{oh})")

    print(f"\n{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
