#!/usr/bin/env python3
"""Offline preview of the crt-perfect family.

Faithful numpy reimplementation of the fragment shaders so the look can be
iterated on without a device. Mirrors the GLSL step for step; see
render_crt() for the correspondence.

render_crt_v5(after=True) is the shipped crt-perfect.glsl. The lower-numbered
renderers mirror the archived iterations under tools/iterations/.

Run:  /tmp/crtvenv/bin/python crt_preview.py
"""

import math
import os

import numpy as np
from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview")

GAMMA = 2.0  # matches the shader: x*x on input, sqrt on output (13 fewer pow per fragment)

DEFAULTS_PP = dict(
    pp_sharpness=1.0,
)

DEFAULTS_V5 = dict(
    cp_scanlines=0.55,
    cp_rgb_mask=0.40,
    cp_mask_type=1.0,
    cp_mask_size=1.0,
    cp_brightness=1.25,
    cp_min_pitch=3.0,
    cp_gamma=1.0,
)

DEFAULTS_V4 = dict(
    Scanlines=0.55,
    RGB_Mask=0.40,
    Mask_Type=1.0,
    Mask_Size=1.0,
    Brightness=1.25,
    Min_Pitch=3.0,
)

DEFAULTS_V3 = dict(
    Scanlines=0.55,
    RGB_Mask=0.40,
    Mask_Type=1.0,
    Mask_Size=1.0,
    Brightness=1.25,
)

DEFAULTS_V2 = dict(
    Scanlines=0.55,
    Beam_Width=0.65,
    RGB_Mask=0.35,
    Mask_Type=1.0,
    Mask_Size=1.0,
    Brightness=1.25,
    Scanline_Min=2.0,
)

DEFAULTS = dict(
    Scanlines=0.55,
    Beam_Width=0.65,
    RGB_Mask=0.35,
    Mask_Type=1.0,
    Mask_Size=1.0,
    Brightness=1.25,
    Fade_Below_Scale=2.0,
)


# ---------------------------------------------------------------- helpers


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def box_sinc(f):
    """Exact average of a unit sinusoid of frequency f (cycles/output px) over
    one pixel-wide box. numpy's sinc is already sin(pi x)/(pi x)."""
    return np.sinc(np.maximum(f, 1e-4))


def nyquist_fade(f):
    return 1.0 - smoothstep(0.34, 0.5, f)


def render_crt_v3(src_u8, out_w, out_h, p=None):
    """Mirrors crt-perfect-v3.glsl: gamma-space blend, pure sinusoids, sinc."""
    p = dict(DEFAULTS_V3, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]
    tex_w, tex_h = in_w, in_h

    u = (np.arange(out_w) + 0.5) / out_w
    v = (np.arange(out_h) + 0.5) / out_h

    rng_x = abs(in_w / (out_w * tex_w)) / 2.0 * 0.999
    rng_y = abs(in_h / (out_h * tex_h)) / 2.0 * 0.999
    texel_x, texel_y = 1.0 / tex_w, 1.0 / tex_h

    left, right = u - rng_x, u + rng_x
    bottom, top = v - rng_y, v + rng_y
    ix_l = np.clip(np.floor(left / texel_x).astype(int), 0, tex_w - 1)
    ix_r = np.clip(np.floor(right / texel_x).astype(int), 0, tex_w - 1)
    iy_b = np.clip(np.floor(bottom / texel_y).astype(int), 0, tex_h - 1)
    iy_t = np.clip(np.floor(top / texel_y).astype(int), 0, tex_h - 1)
    border_x = np.clip(np.floor(u / texel_x + 0.5) * texel_x, left, right)
    border_y = np.clip(np.floor(v / texel_y + 0.5) * texel_y, bottom, top)
    wl = (border_x - left) / (2.0 * rng_x)
    wt = (top - border_y) / (2.0 * rng_y)
    wr, wb = 1.0 - wl, 1.0 - wt

    # NOTE: blended in gamma space, no x*x here
    col = (
        src[np.ix_(iy_b, ix_l)] * (wb[:, None] * wl[None, :])[..., None]
        + src[np.ix_(iy_b, ix_r)] * (wb[:, None] * wr[None, :])[..., None]
        + src[np.ix_(iy_t, ix_l)] * (wt[:, None] * wl[None, :])[..., None]
        + src[np.ix_(iy_t, ix_r)] * (wt[:, None] * wr[None, :])[..., None]
    )

    scan_f = in_h / max(out_h, 1)
    scan_amp = p["Scanlines"] * nyquist_fade(scan_f)
    scan = np.ones(out_h)
    if scan_amp > 0.0:
        ph = np.mod(v * in_h, 1.0)
        scan = (1.0 - 0.5 * scan_amp) - 0.5 * scan_amp * box_sinc(scan_f) * np.cos(
            2.0 * math.pi * ph)

    mask_f = (in_w * p["Mask_Size"]) / max(out_w, 1)
    mask_amp = p["RGB_Mask"] * nyquist_fade(mask_f)
    mask = np.ones((out_h, out_w, 3))
    if mask_amp > 0.0 and p["Mask_Type"] >= 0.5:
        phase = u * in_w * p["Mask_Size"] - 1.0 / 6.0
        ph = np.repeat(phase[None, :], out_h, axis=0)
        if p["Mask_Type"] >= 1.5:
            odd = np.mod(np.floor(v * in_h), 2.0)
            ph = ph + 0.5 * odd[:, None]
        dc = 1.0 - 0.5 * mask_amp
        ac = 0.5 * mask_amp * box_sinc(mask_f)
        off = np.array([0.0, 1.0 / 3.0])
        rg = dc + ac * np.cos(2.0 * math.pi * (np.mod(ph, 1.0)[..., None] - off))
        mask = np.concatenate([rg, (3.0 * dc - rg[..., :1] - rg[..., 1:2])], axis=2)

    gain = np.sqrt(mask * (scan[:, None, None] * p["Brightness"]))
    out = np.clip(col * gain, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8)


def render_crt_v4(src_u8, out_w, out_h, p=None):
    """Mirrors crt-perfect-v4.glsl: v3 plus a minimum output-space pitch."""
    p = dict(DEFAULTS_V4, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]
    tex_w, tex_h = in_w, in_h

    u = (np.arange(out_w) + 0.5) / out_w
    v = (np.arange(out_h) + 0.5) / out_h

    rng_x = abs(in_w / (out_w * tex_w)) / 2.0 * 0.999
    rng_y = abs(in_h / (out_h * tex_h)) / 2.0 * 0.999
    texel_x, texel_y = 1.0 / tex_w, 1.0 / tex_h
    left, right = u - rng_x, u + rng_x
    bottom, top = v - rng_y, v + rng_y
    ix_l = np.clip(np.floor(left / texel_x).astype(int), 0, tex_w - 1)
    ix_r = np.clip(np.floor(right / texel_x).astype(int), 0, tex_w - 1)
    iy_b = np.clip(np.floor(bottom / texel_y).astype(int), 0, tex_h - 1)
    iy_t = np.clip(np.floor(top / texel_y).astype(int), 0, tex_h - 1)
    border_x = np.clip(np.floor(u / texel_x + 0.5) * texel_x, left, right)
    border_y = np.clip(np.floor(v / texel_y + 0.5) * texel_y, bottom, top)
    wl = (border_x - left) / (2.0 * rng_x)
    wt = (top - border_y) / (2.0 * rng_y)
    wr, wb = 1.0 - wl, 1.0 - wt

    col = (
        src[np.ix_(iy_b, ix_l)] * (wb[:, None] * wl[None, :])[..., None]
        + src[np.ix_(iy_b, ix_r)] * (wb[:, None] * wr[None, :])[..., None]
        + src[np.ix_(iy_t, ix_l)] * (wt[:, None] * wl[None, :])[..., None]
        + src[np.ix_(iy_t, ix_r)] * (wt[:, None] * wr[None, :])[..., None]
    )

    mp = p["Min_Pitch"]

    scan_src = out_h / max(in_h, 1)
    scan_pitch = max(scan_src, mp)
    # continuous blend, mirroring the shader: an exact comparison here is unsafe
    # because GPUs evaluate a/b as a*rcp(b)
    scan_locked = 1.0 - smoothstep(mp * 1.001, mp * 1.02, scan_src)
    scan_f = 1.0 / scan_pitch
    scan_amp = p["Scanlines"] * (nyquist_fade(scan_f) * (1 - scan_locked) + scan_locked)
    scan_ac = 0.5 * scan_amp * (box_sinc(scan_f) * (1 - scan_locked) + scan_locked)

    scan = np.ones(out_h)
    if scan_amp > 0.0:
        y = v * out_h - 0.5 * scan_locked
        scan = (1.0 - 0.5 * scan_amp) - scan_ac * np.cos(
            2.0 * math.pi * np.mod(y * scan_f, 1.0))

    mask_src = out_w / max(in_w * p["Mask_Size"], 1)
    mask_pitch = max(mask_src, mp)
    mask_locked = 1.0 - smoothstep(mp * 1.001, mp * 1.02, mask_src)
    mask_f = 1.0 / mask_pitch
    mask_amp = p["RGB_Mask"] * (nyquist_fade(mask_f) * (1 - mask_locked) + mask_locked)

    mask = np.ones((out_h, out_w, 3))
    if mask_amp > 0.0 and p["Mask_Type"] >= 0.5:
        x = u * out_w - 0.5 * mask_locked
        phase = x * mask_f - 1.0 / 6.0
        ph = np.repeat(phase[None, :], out_h, axis=0)
        if p["Mask_Type"] >= 1.5:
            row = np.floor((v * out_h - 0.5 * scan_locked) * scan_f + 1e-3)
            ph = ph + 0.5 * np.mod(row, 2.0)[:, None]
        dc = 1.0 - 0.5 * mask_amp
        ac = 0.5 * mask_amp * (box_sinc(mask_f) * (1 - mask_locked) + mask_locked)
        off = np.array([0.0, 1.0 / 3.0])
        rg = dc + ac * np.cos(2.0 * math.pi * (np.mod(ph, 1.0)[..., None] - off))
        b = np.maximum(3.0 * dc - rg[..., :1] - rg[..., 1:2], 0.0)
        mask = np.concatenate([rg, b], axis=2)

    gain = np.sqrt(np.maximum(mask * (scan[:, None, None] * p["Brightness"]), 0.0))
    return (np.clip(col * gain, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def render_crt_v5(src_u8, out_w, out_h, p=None, after=False, quantise=True):
    """Mirrors crt-perfect.glsl (after=True, gamma applied to the scaled image)
    or the archived crt-perfect-v5.glsl (after=False, gamma applied per tap).

    The two are bit-identical at cp_gamma 1.00 and only diverge away from it."""
    p = dict(DEFAULTS_V5, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]
    tex_w, tex_h = in_w, in_h

    u = (np.arange(out_w) + 0.5) / out_w
    v = (np.arange(out_h) + 0.5) / out_h

    rng_x = abs(in_w / (out_w * tex_w)) / 2.0 * 0.999
    rng_y = abs(in_h / (out_h * tex_h)) / 2.0 * 0.999
    texel_x, texel_y = 1.0 / tex_w, 1.0 / tex_h
    left, right = u - rng_x, u + rng_x
    bottom, top = v - rng_y, v + rng_y
    ix_l = np.clip(np.floor(left / texel_x).astype(int), 0, tex_w - 1)
    ix_r = np.clip(np.floor(right / texel_x).astype(int), 0, tex_w - 1)
    iy_b = np.clip(np.floor(bottom / texel_y).astype(int), 0, tex_h - 1)
    iy_t = np.clip(np.floor(top / texel_y).astype(int), 0, tex_h - 1)
    border_x = np.clip(np.floor(u / texel_x + 0.5) * texel_x, left, right)
    border_y = np.clip(np.floor(v / texel_y + 0.5) * texel_y, bottom, top)
    wl = (border_x - left) / (2.0 * rng_x)
    wt = (top - border_y) / (2.0 * rng_y)
    wr, wb = 1.0 - wl, 1.0 - wt

    taps = [src[np.ix_(iy_b, ix_l)], src[np.ix_(iy_b, ix_r)],
            src[np.ix_(iy_t, ix_l)], src[np.ix_(iy_t, ix_r)]]
    if abs(p["cp_gamma"] - 1.0) > 0.001 and not after:
        taps = [np.power(np.maximum(t, 1e-8), p["cp_gamma"]) for t in taps]

    col = (taps[0] * (wb[:, None] * wl[None, :])[..., None]
           + taps[1] * (wb[:, None] * wr[None, :])[..., None]
           + taps[2] * (wt[:, None] * wl[None, :])[..., None]
           + taps[3] * (wt[:, None] * wr[None, :])[..., None])

    if abs(p["cp_gamma"] - 1.0) > 0.001 and after:
        col = np.power(np.maximum(col, 1e-8), p["cp_gamma"])

    mp = p["cp_min_pitch"]

    scan_src = out_h / max(in_h, 1)
    scan_pitch = max(scan_src, mp)
    scan_locked = 1.0 - smoothstep(mp * 1.001, mp * 1.02, scan_src)
    scan_f = 1.0 / scan_pitch
    scan_amp = p["cp_scanlines"] * (nyquist_fade(scan_f) * (1 - scan_locked) + scan_locked)
    scan_ac = 0.5 * scan_amp * (box_sinc(scan_f) * (1 - scan_locked) + scan_locked)

    scan = np.ones(out_h)
    if scan_amp > 0.0:
        y = v * out_h - 0.5 * scan_locked
        scan = (1.0 - 0.5 * scan_amp) - scan_ac * np.cos(
            2.0 * math.pi * np.mod(y * scan_f, 1.0))

    mask_src = out_w / max(in_w * p["cp_mask_size"], 1)
    mask_pitch = max(mask_src, mp)
    mask_locked = 1.0 - smoothstep(mp * 1.001, mp * 1.02, mask_src)
    mask_f = 1.0 / mask_pitch
    mask_amp = p["cp_rgb_mask"] * (nyquist_fade(mask_f) * (1 - mask_locked) + mask_locked)

    mask = np.ones((out_h, out_w, 3))
    if mask_amp > 0.0 and p["cp_mask_type"] >= 0.5:
        x = u * out_w - 0.5 * mask_locked
        phase = x * mask_f - 1.0 / 6.0
        ph = np.repeat(phase[None, :], out_h, axis=0)
        if p["cp_mask_type"] >= 1.5:
            row = np.floor((v * out_h - 0.5 * scan_locked) * scan_f + 1e-3)
            ph = ph + 0.5 * np.mod(row, 2.0)[:, None]
        dc = 1.0 - 0.5 * mask_amp
        ac = 0.5 * mask_amp * (box_sinc(mask_f) * (1 - mask_locked) + mask_locked)
        off = np.array([0.0, 1.0 / 3.0])
        rg = dc + ac * np.cos(2.0 * math.pi * (np.mod(ph, 1.0)[..., None] - off))
        b = np.maximum(3.0 * dc - rg[..., :1] - rg[..., 1:2], 0.0)
        mask = np.concatenate([rg, b], axis=2)

    gain = np.sqrt(np.maximum(mask * (scan[:, None, None] * p["cp_brightness"]), 0.0))
    out = np.clip(col * gain, 0.0, 1.0)
    # quantise=False returns 0..1 floats. Only the output format changes; beat.py
    # needs them unquantised because the figures it reports are smaller than one
    # 8-bit level.
    return (out * 255.0 + 0.5).astype(np.uint8) if quantise else out


def render_pixel_perfect(src_u8, out_w, out_h, p=None):
    """Mirrors pixel-perfect.glsl: four nearest taps, separable weights, no gamma."""
    p = dict(DEFAULTS_PP, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]

    px = (np.arange(out_w) + 0.5) / out_w * in_w
    py = (np.arange(out_h) + 0.5) / out_h * in_h
    hx = max(0.4995 * p["pp_sharpness"] * in_w / out_w, 1e-6)
    hy = max(0.4995 * p["pp_sharpness"] * in_h / out_h, 1e-6)

    Bx = np.floor(px + 0.5)
    By = np.floor(py + 0.5)
    wx = np.clip((Bx - px + hx) / (2.0 * hx), 0.0, 1.0)
    wy = np.clip((By - py + hy) / (2.0 * hy), 0.0, 1.0)

    lox = np.clip((Bx - 1).astype(int), 0, in_w - 1)
    hix = np.clip(Bx.astype(int), 0, in_w - 1)
    loy = np.clip((By - 1).astype(int), 0, in_h - 1)
    hiy = np.clip(By.astype(int), 0, in_h - 1)

    a = src[np.ix_(loy, lox)]
    b = src[np.ix_(loy, hix)]
    c = src[np.ix_(hiy, lox)]
    d = src[np.ix_(hiy, hix)]

    WX = wx[None, :, None]
    WY = wy[:, None, None]
    top = d * (1.0 - WX) + c * WX
    bot = b * (1.0 - WX) + a * WX
    out = top * (1.0 - WY) + bot * WY
    return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def beam_exponent(beam_width):
    """Beam_Width 0.2 (fat dark line) .. 1.0 (thin dark line) -> cosine exponent.

    Fitted to the two reference overlays: crt.png folds to k ~= 0.7,
    240p.png to k ~= 0.25.
    """
    return 2.0 ** ((0.5 - beam_width) * 4.0)


def mod_mean(k, s, m):
    """Mean gain of the combined modulation, for reporting only.

    Mean of (0.5-0.5*cos(2*pi*p))^k is gamma(k+0.5)/(sqrt(pi)*gamma(k+1)),
    well approximated by inversesqrt(1+3k).
    """
    beam = 1.0 / np.sqrt(1.0 + 3.0 * k)
    return (1.0 - s + s * beam) * (1.0 - m * 0.5)


# ---------------------------------------------------------------- the shader


def render_crt(src_u8, out_w, out_h, p=None, v2=False):
    """src_u8: (H,W,3) uint8 source frame -> (out_h,out_w,3) uint8 output.

    v2=True mirrors crt-perfect-v2.glsl (corrected sampling guards).
    """
    p = dict(DEFAULTS_V2 if v2 else DEFAULTS, **(p or {}))
    src = src_u8.astype(np.float64) / 255.0
    in_h, in_w = src.shape[:2]

    # Pass is configured srctype=source / scaletype=source, so
    # InputSize == TextureSize == source size, OutputSize == on-screen rect.
    tex_w, tex_h = in_w, in_h

    # texcoords at output pixel centres
    u = (np.arange(out_w) + 0.5) / out_w
    v = (np.arange(out_h) + 0.5) / out_h

    # --- 1. pixellate-style area average (separable) --------------------
    # range = InputSize / (OutputSize * TextureSize) / 2 * 0.999, in texcoords
    rng_x = abs(in_w / (out_w * tex_w)) / 2.0 * 0.999
    rng_y = abs(in_h / (out_h * tex_h)) / 2.0 * 0.999
    texel_x, texel_y = 1.0 / tex_w, 1.0 / tex_h

    left, right = u - rng_x, u + rng_x
    bottom, top = v - rng_y, v + rng_y

    ix_l = np.clip(np.floor(left / texel_x).astype(int), 0, tex_w - 1)
    ix_r = np.clip(np.floor(right / texel_x).astype(int), 0, tex_w - 1)
    iy_b = np.clip(np.floor(bottom / texel_y).astype(int), 0, tex_h - 1)
    iy_t = np.clip(np.floor(top / texel_y).astype(int), 0, tex_h - 1)

    border_x = np.clip(np.floor(u / texel_x + 0.5) * texel_x, left, right)
    border_y = np.clip(np.floor(v / texel_y + 0.5) * texel_y, bottom, top)

    wl = (border_x - left) / (2.0 * rng_x)  # weight of the left texel
    wb = (border_y - bottom) / (2.0 * rng_y)  # weight of the bottom texel
    wr, wt = 1.0 - wl, 1.0 - wb

    lin = np.power(src, GAMMA)
    col = (
        lin[np.ix_(iy_b, ix_l)] * (wb[:, None] * wl[None, :])[..., None]
        + lin[np.ix_(iy_b, ix_r)] * (wb[:, None] * wr[None, :])[..., None]
        + lin[np.ix_(iy_t, ix_l)] * (wt[:, None] * wl[None, :])[..., None]
        + lin[np.ix_(iy_t, ix_r)] * (wt[:, None] * wr[None, :])[..., None]
    )

    # --- 2. scanlines, count = source vertical resolution ---------------
    vscale = out_h / in_h  # output pixels per source line
    if v2:
        lo = p["Scanline_Min"]
        s = p["Scanlines"] * smoothstep(lo, lo + 1.0, vscale)
    else:
        s = p["Scanlines"] * smoothstep(1.0, max(p["Fade_Below_Scale"], 1.001), vscale)

    if s > 0.0:
        k = beam_exponent(p["Beam_Width"])
        if v2:
            # pull towards a pure cosine at low scale: pow(cos,k) has harmonics
            # for k != 1 and they alias before the fundamental does
            k = 1.0 + (k - 1.0) * smoothstep(2.0, 3.5, vscale)
        row = v * in_h
        # base clamped away from 0 to mirror the shader, where pow(0,k) is
        # undefined and returns NaN on real drivers
        raw = 0.5 - 0.5 * np.cos(2.0 * math.pi * row)
        beam = np.power(np.maximum(raw, 1e-5), k)  # 1 at line centre
        if v2:
            beam = beam * (raw >= 1e-5)  # restore the exact zero the clamp lifts
        col *= (1.0 - s + s * beam)[:, None, None]

    # --- 3. RGB mask, one triad per source pixel ------------------------
    triad_px = out_w / (in_w * max(p["Mask_Size"], 0.01))  # output px per triad
    m = p["RGB_Mask"] * smoothstep(2.0 if v2 else 1.5, 3.0, triad_px)

    if m > 0.0 and p["Mask_Type"] >= 0.5:
        # -1/6 centres the triad on the source pixel: R at 1/6, G at 1/2, B at 5/6
        phase = u * in_w * p["Mask_Size"] - 1.0 / 6.0
        ph = np.repeat(phase[None, :], out_h, axis=0)
        if p["Mask_Type"] >= 1.5:  # slot mask: stagger alternate source rows
            odd = np.mod(np.floor(v * in_h), 2.0)
            ph = ph + 0.5 * odd[:, None]
        off = np.array([0.0, 1.0 / 3.0, 2.0 / 3.0])
        mask = 0.5 + 0.5 * np.cos(2.0 * math.pi * (ph[..., None] - off))
        col *= 1.0 - m + m * mask

    # --- 4. brightness + encode ----------------------------------------
    col = np.clip(col * p["Brightness"], 0.0, 1.0)
    return (np.power(col, 1.0 / GAMMA) * 255.0 + 0.5).astype(np.uint8)


# ---------------------------------------------------------------- sources


def src_white(w, h):
    return np.full((h, w, 3), 255, np.uint8)


def src_gray(w, h, level=128):
    return np.full((h, w, 3), level, np.uint8)


def src_bars(w, h):
    a = np.zeros((h, w, 3), np.uint8)
    cols = [
        (255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
        (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0),
    ]
    for i, c in enumerate(cols):
        a[: h // 2, i * w // 8 : (i + 1) * w // 8] = c
    ramp = (np.arange(w) * 255 // max(w - 1, 1)).astype(np.uint8)
    a[h // 2 : 3 * h // 4] = ramp[None, :, None]
    # 1px checker to expose scaling artefacts
    yy, xx = np.mgrid[3 * h // 4 : h, 0:w]
    a[3 * h // 4 :] = (((yy + xx) % 2) * 255).astype(np.uint8)[..., None]
    return a


def src_scene(w, h):
    """Synthetic 'game frame': sky gradient, sprites, fine detail, text blocks."""
    yy, xx = np.mgrid[0:h, 0:w]
    a = np.zeros((h, w, 3), np.float64)
    a[..., 0] = 40 + 60 * yy / h
    a[..., 1] = 90 + 90 * yy / h
    a[..., 2] = 200 - 40 * yy / h
    # ground
    g = yy > h * 0.72
    a[g] = np.array([70, 140, 60])
    a[(yy > h * 0.72) & ((xx // 4 + yy // 4) % 2 == 0)] = np.array([56, 116, 48])
    # bricks
    for by in range(int(h * 0.4), int(h * 0.72), 8):
        for bx in range((by // 8 % 2) * 8, w, 16):
            a[by : by + 7, bx : bx + 15] = np.array([180, 90, 40])
    # sprite: bright saturated blocks
    sx, sy = w // 3, int(h * 0.45)
    a[sy : sy + 16, sx : sx + 14] = np.array([230, 40, 40])
    a[sy + 4 : sy + 9, sx + 3 : sx + 11] = np.array([250, 220, 170])
    a[sy + 16 : sy + 24, sx + 2 : sx + 12] = np.array([40, 60, 220])
    # 1px white grid + text-like runs
    a[int(h * 0.1) : int(h * 0.1) + 1, :] = 255
    for i in range(0, w, 3):
        a[int(h * 0.15) : int(h * 0.15) + 5, i : i + 1] = 255
    a[int(h * 0.2) : int(h * 0.28), int(w * 0.6) : int(w * 0.95)] = np.array([250, 250, 250])
    return np.clip(a, 0, 255).astype(np.uint8)


SOURCES = {
    "white": src_white,
    "gray": src_gray,
    "bars": src_bars,
    "scene": src_scene,
}

# (name, source w/h, screen w/h)
CASES = [
    ("240p_1024x768", (320, 240), (1024, 768)),
    ("224p_1024x768", (256, 224), (1024, 768)),
    ("144p_1024x768", (160, 144), (1024, 768)),
    ("240p_1280x720", (320, 240), (1280, 720)),
    ("480p_1280x720", (640, 480), (1280, 720)),
]


def main(params=None, tag="default", sources=("white", "scene"), cases=None):
    os.makedirs(OUT, exist_ok=True)
    for name, (sw, sh), (ow, oh) in cases or CASES:
        for sname in sources:
            src = SOURCES[sname](sw, sh)
            img = render_crt(src, ow, oh, params)
            path = os.path.join(OUT, f"{tag}_{name}_{sname}.png")
            Image.fromarray(img).save(path)
            print("wrote", path)


if __name__ == "__main__":
    main()
