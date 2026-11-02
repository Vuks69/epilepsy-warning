"""Color science helpers used by the detector.

All RGB values entering this module are gamma-encoded sRGB in the range 0..1
unless a function name explicitly says ``linear``.  The WCAG red rules are
defined in linear RGB and CIE 1976 UCS, so those conversions live here.
"""

from __future__ import annotations

import numpy as np

try:
    from line_profiler import profile  # type: ignore
except ImportError:

    def profile(func):  # type: ignore
        return func


_SRGB_LINEAR_CUTOFF = 0.04045
_SRGB_SLOPE = 12.92
_SRGB_OFFSET = 0.055
_SRGB_SCALE = 1.055
_SRGB_EXPONENT = 2.4


# Precompute sRGB -> linear LUT for uint8 values (much faster than pow).  The
# entries are evaluated with the same float32 operations as the non-LUT path,
# so ``srgb_to_linear`` gives identical values for a uint8 value and for the
# corresponding ``value / 255`` float.
def _build_srgb_to_linear_lut() -> np.ndarray:
    values = np.arange(256, dtype=np.uint8).astype(np.float32)
    values /= np.float32(255.0)
    return np.where(
        values <= _SRGB_LINEAR_CUTOFF,
        values / _SRGB_SLOPE,
        ((values + _SRGB_OFFSET) / _SRGB_SCALE) ** _SRGB_EXPONENT,
    ).astype(np.float32)


_SRGB_TO_LINEAR_LUT = _build_srgb_to_linear_lut()


@profile
def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """Gamma-expand sRGB channel values into linear light."""
    values = np.asarray(rgb)
    if values.dtype == np.uint8:
        # Fast path using LUT
        return _SRGB_TO_LINEAR_LUT[values].astype(np.float32, copy=False)
    values = values.astype(np.float32)
    return np.where(
        values <= _SRGB_LINEAR_CUTOFF,
        values / _SRGB_SLOPE,
        ((values + _SRGB_OFFSET) / _SRGB_SCALE) ** _SRGB_EXPONENT,
    ).astype(np.float32)


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    """Encode linear RGB values as sRGB.  Mainly useful for fixtures/tests."""
    values = np.asarray(rgb, dtype=np.float32)
    return np.where(
        values <= 0.0031308,
        values * _SRGB_SLOPE,
        _SRGB_SCALE * np.power(values, 1.0 / _SRGB_EXPONENT) - _SRGB_OFFSET,
    ).astype(np.float32)


@profile
def linear_rgb_to_luminance(linear_rgb: np.ndarray) -> np.ndarray:
    """Relative luminance (Y) of linear sRGB."""
    values = np.asarray(linear_rgb, dtype=np.float32)
    return 0.2126 * values[..., 0] + 0.7152 * values[..., 1] + 0.0722 * values[..., 2]


@profile
def linear_rgb_to_xyz(linear_rgb: np.ndarray) -> np.ndarray:
    """Convert linear sRGB to CIE XYZ (D65)."""
    values = np.asarray(linear_rgb, dtype=np.float32)
    red = values[..., 0]
    green = values[..., 1]
    blue = values[..., 2]
    x = 0.4124564 * red + 0.3575761 * green + 0.1804375 * blue
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = 0.0193339 * red + 0.1191920 * green + 0.9503041 * blue
    return np.stack((x, y, z), axis=-1)


@profile
def linear_rgb_to_ucs(linear_rgb: np.ndarray) -> tuple:
    """Return CIE 1976 UCS chromaticity coordinates ``(u', v')``.

    The result is a pair of arrays with the spatial shape of the input.  A
    black input has no chromaticity; it maps to ``(0, 0)``.
    """
    xyz = linear_rgb_to_xyz(linear_rgb)
    x = xyz[..., 0]
    y = xyz[..., 1]
    z = xyz[..., 2]
    denominator = x + 15.0 * y + 3.0 * z
    u = np.divide(4.0 * x, denominator, out=np.zeros_like(x), where=denominator > 0)
    v = np.divide(9.0 * y, denominator, out=np.zeros_like(y), where=denominator > 0)
    return u, v


@profile
def linear_rgb_features(linear_rgb: np.ndarray, red_threshold: float = 0.8) -> tuple:
    """Compute the per-tile color quantities used by the engine in one pass.

    Returns ``(luminance, redness, red, u, v)``.  This is the fused equivalent
    of calling ``linear_rgb_to_luminance``, ``red_ratio``,
    ``is_saturated_red``, and ``linear_rgb_to_ucs``.  The red ratio is computed
    once and reused for the saturation mask instead of being recomputed, and
    the CIE UCS pair is derived without materializing the intermediate XYZ
    stack.
    """
    values = np.asarray(linear_rgb, dtype=np.float32)
    red = values[..., 0]
    green = values[..., 1]
    blue = values[..., 2]

    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue

    total = red + green + blue
    redness = np.divide(
        red,
        total,
        out=np.zeros_like(red),
        where=total > 0,
    )

    x = 0.4124564 * red + 0.3575761 * green + 0.1804375 * blue
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = 0.0193339 * red + 0.1191920 * green + 0.9503041 * blue
    denominator = x + 15.0 * y + 3.0 * z
    u = np.divide(4.0 * x, denominator, out=np.zeros_like(x), where=denominator > 0)
    v = np.divide(9.0 * y, denominator, out=np.zeros_like(y), where=denominator > 0)

    return luminance, redness, redness >= red_threshold, u, v


def ucs_distance_squared(
    u1: np.ndarray, v1: np.ndarray, u2: np.ndarray, v2: np.ndarray
) -> np.ndarray:
    return (u1 - u2) ** 2 + (v1 - v2) ** 2


def ucs_distance(u1: np.ndarray, v1: np.ndarray, u2: np.ndarray, v2: np.ndarray) -> np.ndarray:
    return np.sqrt(ucs_distance_squared(u1, v1, u2, v2))


def red_ratio(linear_rgb: np.ndarray) -> np.ndarray:
    """Linear ``R / (R + G + B)``, the saturated-red test quantity."""
    values = np.asarray(linear_rgb, dtype=np.float32)
    total = values[..., 0] + values[..., 1] + values[..., 2]
    return np.divide(
        values[..., 0],
        total,
        out=np.zeros_like(values[..., 0]),
        where=total > 0,
    )


@profile
def is_saturated_red(linear_rgb: np.ndarray, threshold: float = 0.8) -> np.ndarray:
    return red_ratio(linear_rgb) >= threshold


def luminance_to_srgb_gray(luminance: np.ndarray) -> np.ndarray:
    """Convert a neutral relative luminance to an sRGB gray value."""
    return linear_to_srgb(np.clip(np.asarray(luminance, dtype=np.float32), 0.0, 1.0))
