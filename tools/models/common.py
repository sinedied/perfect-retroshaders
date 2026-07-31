#!/usr/bin/env python3
"""Numerics shared by every model.

These were defined once per model file - smoothstep in three, box_sinc and
nyquist_fade in two - and had already started to drift apart in spelling if not
in value. A model is only worth anything as an independent check of the GLSL, so
the *shader logic* stays written out separately in each; it is the arithmetic
underneath that belongs in one place.
"""

import numpy as np


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def box_sinc(f):
    """Exact mean of a unit sinusoid of f cycles per output pixel over one
    pixel. numpy's sinc is already sin(pi x)/(pi x)."""
    return np.sinc(np.maximum(f, 1e-4))


def nyquist_fade(f):
    """Nothing above Nyquist can be represented, so the pattern is faded out
    entirely there - amplitude and darkening together, leaving no dimming."""
    return 1.0 - smoothstep(0.34, 0.5, f)
