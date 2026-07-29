#!/usr/bin/env python3
"""Measure CRT pattern geometry: scanline/mask period, contrast, mean level.

Works on either a reference overlay (RGBA, composited over white) or a rendered
preview (opaque). Lets generated output be compared numerically to the
reference images.

Run:  /tmp/crtvenv/bin/python measure.py <image> [<image> ...]
"""

import sys

import numpy as np
from PIL import Image


def load_over_white(path):
    im = Image.open(path)
    a = np.asarray(im.convert("RGBA")).astype(np.float64)
    rgb, alpha = a[..., :3], a[..., 3:] / 255.0
    return rgb * alpha + 255.0 * (1.0 - alpha)


def dominant_period(sig, lo=2.0, hi=40.0):
    """Sub-sample-accurate dominant period via zero-mean autocorrelation."""
    c = sig - sig.mean()
    if np.allclose(c, 0):
        return None, 0.0
    n = len(c)
    ac = np.correlate(c, c, mode="full")[n - 1 :] / (np.arange(n, 0, -1))
    ac = ac / ac[0]
    lags = np.arange(len(ac))
    win = (lags >= lo) & (lags <= hi)
    if not win.any():
        return None, 0.0
    i = int(lags[win][np.argmax(ac[win])])
    # the max often lands on a harmonic; walk back to the fundamental
    peak = ac[i]
    for j in range(int(np.ceil(lo)), i):
        if ac[j] >= 0.90 * peak and ac[j] > ac[j - 1] and ac[j] >= ac[j + 1]:
            i = j
            break
    # parabolic refinement around the peak
    if 0 < i < len(ac) - 1:
        y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]
        d = y0 - 2 * y1 + y2
        if d != 0:
            i = i + 0.5 * (y0 - y2) / d
    return float(i), float(ac[int(round(i))] if int(round(i)) < len(ac) else 0)


def report(path):
    img = load_over_white(path)
    h, w = img.shape[:2]
    y0, y1 = h // 4, 3 * h // 4
    x0, x1 = w // 4, 3 * w // 4
    patch = img[y0:y1, x0:x1]

    lum = patch.mean(axis=2)
    rows = lum.mean(axis=1)
    cols = lum.mean(axis=0)

    per_v, str_v = dominant_period(rows)
    per_h, str_h = dominant_period(cols)

    # per-channel horizontal swing = how strong the RGB mask reads
    chan = patch.mean(axis=0)
    chan_swing = (chan.max(axis=0) - chan.min(axis=0)).mean()
    # channel separation: how much R/G/B disagree column to column
    sep = np.abs(chan - chan.mean(axis=1, keepdims=True)).mean() * 2.0

    print(f"{path}")
    print(f"  size            {w}x{h}")
    print(f"  mean level      {lum.mean():6.1f} / 255   ({lum.mean()/255*100:.1f}%)")
    print(f"  scanline period {per_v if per_v is None else round(per_v,2)} px"
          f"   -> {None if not per_v else round(h/per_v)} lines over {h}px"
          f"   (autocorr {str_v:.2f})")
    print(f"  row swing       {rows.max()-rows.min():6.1f}"
          f"   min {rows.min():5.1f}  max {rows.max():5.1f}")
    print(f"  mask period     {per_h if per_h is None else round(per_h,2)} px"
          f"   (autocorr {str_h:.2f})")
    print(f"  col swing       {cols.max()-cols.min():6.1f}"
          f"   per-channel swing {chan_swing:5.1f}   rgb separation {sep:5.1f}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        report(p)
