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


# ---------------------------------------------------------------------------
# HDR transfer functions (ST 2084 PQ / ARIB STD-B67 HLG).
#
# sRGB, HLG and PQ all decode here to *relative* linear light, where 1.0 is the
# reference white the cd/m2 path scales by (``reference_luminance_cd_m2``); the
# engine multiplies the decoded relative luminance by that reference, so the
# decoded value reads 1.0 at reference white.  sRGB already does that (code 1.0
# -> linear 1.0).  These two follow the same convention:
#
#   * PQ (ST 2084): the electro-optical EOTF returns cd/m^2 for a peak of
#     ``reference``; the normalized EOTF (peak code == relative 1.0) is the
#     inverse, so the maximum code maps to the reference ceiling.
#   * HLG (ARIB STD-B67): the inverse OETF returns light where code 0.5 is
#     reference white (relative 1.0) and code 1.0 is the HDR ceiling (~12x).
#
# These paths run only for non-sRGB media; the sRGB path is byte-identical.
# ---------------------------------------------------------------------------

_PQ_M1 = 2610 / 4096 * (1 / 4)
_PQ_M2 = 2523 / 4096 * 128
_PQ_C1 = 3424 / 4096
_PQ_C2 = 2413 / 4096 * 32
_PQ_C3 = 2392 / 4096 * 32

_HLG_A = 0.17883277
_HLG_B = 0.28466892
_HLG_C = 0.55991073
_HLG_R = 0.5


@profile
def pq_to_linear(code: np.ndarray) -> np.ndarray:
    """Decode SMPTE ST 2084 (PQ) codes in 0..1 to relative linear light.

    The normalized EOTF makes the maximum code (1.0) the reference ceiling, so
    the decoded value reads 1.0 at the reference luminance the cd/m2 path scales
    by.  ``code`` values are the encoded 8/10/12-bit samples rescaled to 0..1.
    """
    values = np.clip(np.asarray(code, dtype=np.float32), 0.0, 1.0)
    exponent = 1.0 / _PQ_M2
    v = np.power(values, exponent, dtype=np.float32)
    n = np.maximum(0.0, v - _PQ_C1)
    denom = _PQ_C2 - _PQ_C3 * v
    ratio = np.divide(n, denom, out=np.zeros_like(n), where=denom > 0)
    return np.power(ratio, 1.0 / _PQ_M1, dtype=np.float32)


@profile
def hlg_to_linear(code: np.ndarray) -> np.ndarray:
    """Decode ARIB STD-B67 (HLG) codes in 0..1 to relative linear light.

    The inverse OETF returns light where code 0.5 is reference white (relative
    1.0) and code 1.0 is the HDR ceiling (~12x reference).  ``code`` values are
    the encoded samples rescaled to 0..1.
    """
    values = np.clip(np.asarray(code, dtype=np.float32), 0.0, 1.0)
    lower = (values / _HLG_R) ** 2.0  # codes at or below reference white
    upper = np.exp((values - _HLG_C) / _HLG_A) + _HLG_B  # codes above reference white
    return np.where(values <= _HLG_R, lower, upper).astype(np.float32)


# Source-linear RGB -> sRGB-linear matrices (validated: white -> white and
# luminance preserved for both).  Applied only after transfer decode, for
# wide-gamut content; sRGB and Rec.709 share primaries, so they are identity.
_P3_D65_TO_SRGB = np.array(
    [
        [0.96063374, 0.00000000, 0.03936657],
        [0.00353933, 0.99494033, 0.00151441],
        [0.04907332, 0.00000000, 0.95092563],
    ],
    dtype=np.float32,
)
_BT2020_TO_SRGB = np.array(
    [
        [1.01034394, 0.00000000, -0.01034394],
        [0.01201382, 0.98966724, -0.00168050],
        [0.06171234, 0.00000000, 0.93828705],
    ],
    dtype=np.float32,
)

# Gamut aliases -> canonical matrix key (None means "no conversion / identity").
_GAMUT_MATRICES = {
    "p3_d65": _P3_D65_TO_SRGB,
    "bt2020": _BT2020_TO_SRGB,
}


def convert_to_srgb_linear(linear: np.ndarray, color_space: str) -> np.ndarray:
    """Convert source-linear RGB to sRGB-linear for the given canonical gamut.

    sRGB and Rec.709 share primaries (identity), and an unrecognized gamut falls
    back to identity so the transfer-decoded luminance is still valid.  The
    result is clamped at the low end: out-of-sRGB colors clamp toward black,
    while in-gamut values are untouched and HDR values above 1.0 are preserved.
    """
    values = np.asarray(linear, dtype=np.float32)
    matrix = _GAMUT_MATRICES.get(color_space)
    if matrix is None:
        return values
    converted = values @ matrix.T
    return np.clip(converted, 0.0, None).astype(np.float32)


@profile
def decode_to_srgb_linear(
    tiles: np.ndarray,
    color_space: str,
    transfer: str,
) -> np.ndarray:
    """Decode encoded (gamma) tiles to sRGB-linear relative light.

    ``tiles`` are the encoded samples rescaled to 0..1.  Transfer is decoded
    first (into the source gamut), then the gamut is converted to sRGB.  This is
    the decode path used for non-sRGB media; the default sRGB path in the engine
    stays on the byte-identical uint8 + sRGB-LUT route.
    """
    values = np.clip(np.asarray(tiles, dtype=np.float32), 0.0, None)
    if transfer == "pq":
        linear = pq_to_linear(values)
    elif transfer == "hlg":
        linear = hlg_to_linear(values)
    else:
        linear = srgb_to_linear(values)
    return convert_to_srgb_linear(linear, color_space)
