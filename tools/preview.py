#!/usr/bin/env python3
"""Render PNG comparisons, so a look can be judged by eye.

Everything else in tools/ reports numbers. Numbers settle whether a shader is
correct and what it costs; they do not settle whether it looks right, and these
shaders exist to look right. crt-perfect-v7 passed every number in the harness
while having cropped its entire image border off-screen.

Renders through the same path test.py uses, so a vendored reference appears
under identical conditions - a comparison against lcd1x is worth nothing if
lcd1x went through a different pipeline or a different sampler.

    python tools/preview.py                            current version per family
    python tools/preview.py crt-perfect.glsl crt-perfect-v10.glsl
    python tools/preview.py --diff                     add an amplified diff row
    python tools/preview.py --crop 240 --zoom 4        look closely
    python tools/preview.py --case 480x272->640x480    one scale only
    python tools/preview.py --moire                    show only the beat band
    python tools/preview.py --as-shipped               no preview overrides
    python tools/preview.py --source scene             one source only
    python tools/preview.py --samples DIR              real screenshots

Output goes to tools/preview/, which is gitignored.
"""

import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

OUT = c.PREVIEW
LABEL_H = 14

# Differences worth looking at are 1-2/255, so an unamplified diff row is a
# black rectangle. 8 puts 1/255 at 8/255 - visible, and still far from
# saturating a real 30/255 disagreement.
DIFF_GAIN = 8

# Real screenshots beat synthetic patterns for judging a look: a white field
# shows what the grid does, a game frame shows whether you would want to play
# through it. These are NOT copied here - they are third-party game captures
# under their own notice, and this repo is MIT.
SAMPLES_DEFAULT = os.path.expanduser("~/projects/retroshader-lab/public/samples")


AS_SHIPPED = False


def params_for(name):
    """A shader's own defaults, plus the preview departures declared for it.

    --as-shipped drops the departures. Use it when the question is what a user
    sees, rather than what a feature does: a curvature override makes a great
    picture of curvature and a misleading picture of anything else.
    """
    p = c.defaults(name)
    if AS_SHIPPED:
        return p
    p.update({k: v for k, v in c.SETTINGS.get("preview", {}).items() if k in p})
    p.update(c.SHADERS_DECLARED.get(name, {}).get("preview", {}))
    return p


def label(text, width):
    from PIL import ImageDraw
    img = Image.new("RGB", (width, LABEL_H), (24, 24, 28))
    ImageDraw.Draw(img).text((4, 2), text, fill=(210, 210, 215))
    return np.asarray(img)


def border_grid(w=320, h=240, step=20):
    """A grid whose four edges are each a different colour, plus centre lines.

    For geometry, not for looks. Anything that warps the image has to be judged
    on what happens to the BORDER, and neither a screenshot nor a plain grid
    shows that. Red top and bottom, blue left and right, green centre.
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
        out.append((stem, np.asarray(
            Image.open(os.path.join(folder, fn)).convert("RGB"))))
    return out


def render_one(ctx, progs, name, src, out_w, out_h):
    """No flip anywhere.

    c.draw() returns rows in the same order as the source array - the texture
    upload and the framebuffer readback are both bottom-up, so they cancel. An
    earlier version flipped the source in and flipped the result back, which is
    an identity for CONTENT, so every screenshot came out the right way up and
    nothing looked wrong for a year. But the shader ran on a flipped image, so
    anything with a direction came out mirrored in y. A grid, a scanline and a
    mask are all symmetric and cannot show it; dmg-perfect's cast shadow can,
    and it rendered up-and-right here while the harness had it down-and-right
    from the same shader. Judge a handed effect only in this convention.
    """
    return c.render(ctx, progs, name, src, out_w, out_h, params=params_for(name))


def sheet_for(ctx, progs, names, src, ow, oh, crop=None, zoom=1, diff=False,
              moire=None):
    """One tile per shader, optionally a difference row against the first.

    A side-by-side of two correct scalers is uninformative by construction:
    they agree, so the eye sees one picture four times and learns nothing. The
    difference row is what says whether they agree and by how much, and it is
    the only view that separates "the same shader" from "close enough to fool
    a screenshot".
    """
    imgs, tiles = [], []
    for name in names:
        try:
            img = render_one(ctx, progs, name, src, ow, oh)
        except Exception as exc:
            print(f"  {name}: skipped ({str(exc)[:60]})")
            continue
        if crop:
            y0, x0 = (oh - crop) // 2, (ow - crop) // 2
            img = img[max(y0, 0):y0 + crop, max(x0, 0):x0 + crop]
        img = img.repeat(zoom, 0).repeat(zoom, 1)
        imgs.append((name, img))
        tiles.append(np.vstack([label(name.replace(".glsl", ""), img.shape[1]),
                                img]))
    if not tiles:
        return None
    rows = [np.hstack(tiles)]
    if moire:
        sw, sh = moire
        mrow = []
        for name, img in imgs:
            v = moire_view(img, sw, sh, name)
            mrow.append(np.vstack([label(f"moire band only, x24  {name}",
                                         v.shape[1]), v]))
        rows.append(np.hstack(mrow))
    if diff and len(imgs) > 1:
        ref_name, ref = imgs[0]
        drow = []
        for name, img in imgs:
            d = np.abs(img.astype(int) - ref.astype(int)).max(axis=2)
            amp = np.clip(d * DIFF_GAIN, 0, 255).astype(np.uint8)
            drow.append(np.vstack([
                label(f"diff x{DIFF_GAIN} vs {ref_name.replace('.glsl', '')}"
                      f"  max {int(d.max())}/255", img.shape[1]),
                amp[..., None].repeat(3, 2)]))
        rows.append(np.hstack(drow))
    return np.vstack(rows)


def moire_view(img, sw, sh, name, gain=24):
    """Only the band the moire metric integrates, amplified.

    The beat is low-frequency by definition, so at full scale it is invisible
    next to the shader's own pattern - which is exactly why it needs a number in
    the first place. This inverts that: throw away everything the metric ignores
    and look at what is left. Grey is zero, so lighter and darker are both beat.
    """
    import measure as m
    lum = img.astype(np.float64).mean(axis=2)
    oh, ow = lum.shape
    F = np.fft.fft2(lum)
    band = m._band(ow, oh, sw, sh, m.pattern_freq(name, sw, sh, ow, oh),
                   np.abs(np.fft.fftfreq(ow)), np.abs(np.fft.fftfreq(oh)))
    low = np.real(np.fft.ifft2(F * band))
    v = np.clip(128.0 + low * gain, 0, 255).astype(np.uint8)
    return v[..., None].repeat(3, 2)


def _opt(argv, flag, cast=str, default=None):
    if flag not in argv:
        return default
    i = argv.index(flag)
    v = cast(argv[i + 1])
    del argv[i:i + 2]
    return v


def main(argv):
    crop = _opt(argv, "--crop", int)
    zoom = _opt(argv, "--zoom", int, 1)
    samples_dir = _opt(argv, "--samples", os.path.expanduser, SAMPLES_DEFAULT)
    only = _opt(argv, "--only", lambda s: s.split(","))
    case_filter = _opt(argv, "--case")
    source_filter = _opt(argv, "--source")
    diff = "--diff" in argv
    if diff:
        argv.remove("--diff")
    show_moire = "--moire" in argv
    if show_moire:
        argv.remove("--moire")
    if "--as-shipped" in argv:
        argv.remove("--as-shipped")
        globals()["AS_SHIPPED"] = True

    args = [a for a in argv[1:] if not a.startswith("-")]
    names = args or [c.current(f) for f in c.families()]
    names = [n if n.endswith(".glsl") else n + ".glsl" for n in names]
    missing = [n for n in names if not os.path.exists(
        os.path.join(c.SHADERS, n)) and n not in c.SHADERS_DECLARED]
    if missing:
        print(f"not found: {', '.join(missing)}")
        return 2

    cases = [k for k in c.CASES
             if not case_filter or c.golden_key(k) == case_filter]
    if not cases:
        print(f"no case matches {case_filter}. Available:")
        for k in c.CASES:
            print("  " + c.golden_key(k))
        return 2

    sources = [s for s in ("flat", "scene", "bars", "checkerboard")
               if not source_filter or s == source_filter]

    os.makedirs(OUT, exist_ok=True)
    ctx = c.context()
    progs = c.Programs(ctx)
    written = []

    for sname in sources:
        for sw, sh, ow, oh in cases:
            src = c.SOURCES[sname](sw, sh)
            sheet = sheet_for(ctx, progs, names, src, ow, oh, crop, zoom, diff,
                              (sw, sh) if show_moire else None)
            if sheet is None:
                continue
            tag = (f"{sname}_{sw}x{sh}_to_{ow}x{oh}"
                   + ("_moire" if show_moire else "")
                   + ("_shipped" if AS_SHIPPED else "")
                   + (f"_crop{crop}" if crop else "")
                   + (f"_x{zoom}" if zoom > 1 else "")
                   + ("_diff" if diff else ""))
            path = os.path.join(OUT, f"{tag}.png")
            Image.fromarray(sheet).save(path)
            written.append(path)

    for stem, src in load_samples(samples_dir, only):
        sh, sw = src.shape[:2]
        for _sw, _sh, ow, oh in cases:
            sheet = sheet_for(ctx, progs, names, src, ow, oh, crop, zoom, diff,
                              (sw, sh) if show_moire else None)
            if sheet is None:
                continue
            tag = (f"{stem}_to_{ow}x{oh}"
                   + ("_moire" if show_moire else "")
                   + ("_shipped" if AS_SHIPPED else "")
                   + (f"_crop{crop}" if crop else "")
                   + (f"_x{zoom}" if zoom > 1 else "")
                   + ("_diff" if diff else ""))
            path = os.path.join(OUT, f"{tag}.png")
            Image.fromarray(sheet).save(path)
            written.append(path)

    for p in written:
        print(f"wrote {p}")
    print(f"\n{len(written)} sheets in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
