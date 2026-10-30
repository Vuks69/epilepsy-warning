"""Analysis options and display assumptions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .errors import InvalidOptionsError
from .standards import StandardProfile, get_profile


@dataclass(frozen=True)
class DisplayGeometry:
    """Known display/viewing geometry used for the 10-degree area rule.

    The content is assumed to fill the display width.  A 23-inch Full HD monitor
    viewed at 71.1 cm is the paper's reference screen.
    """

    screen_diagonal_in: float
    viewing_distance_cm: float
    aspect_ratio: float = 16.0 / 9.0

    def __post_init__(self) -> None:
        if self.screen_diagonal_in <= 0:
            raise InvalidOptionsError("screen_diagonal_in must be positive")
        if self.viewing_distance_cm <= 0:
            raise InvalidOptionsError("viewing_distance_cm must be positive")
        if self.aspect_ratio <= 0:
            raise InvalidOptionsError("aspect_ratio must be positive")

    def to_dict(self) -> Dict[str, float]:
        return {
            "screen_diagonal_in": self.screen_diagonal_in,
            "viewing_distance_cm": self.viewing_distance_cm,
            "aspect_ratio": self.aspect_ratio,
        }


@dataclass(frozen=True)
class AnalysisOptions:
    """Configuration for one analysis.

    Defaults target WCAG 2.2 SC 2.3.1.  The 66 ms, 20 ms, and 65 Hz values are
    the paper's working values, not normative WCAG thresholds; they are reported
    in the result so callers can tell what was assumed.
    """

    standard: str = "wcag22"
    luminance_threshold: float = 0.10
    red_saturation: float = 0.80
    red_color_difference: float = 0.20
    max_flashes_per_second: float = 3.0
    max_transition_duration_ms: float = 66.0
    synchronicity_window_ms: float = 20.0
    fast_flash_hz: float = 65.0
    enable_fast_flash_merge: bool = True
    flash_area_overlap_ratio: float = 0.30
    flash_area_union_scale: float = 1.50
    area_model: Optional[str] = None
    area_subarea_css_px: Tuple[int, int] = (416, 416)
    display: Optional[DisplayGeometry] = None
    reference_luminance_cd_m2: float = 200.0
    color_space: str = "auto"
    motion_compensation: bool = False
    extended_exposure: bool = False
    max_bytes: int = 64 * 1024 * 1024
    max_duration_seconds: float = 60.0
    max_frames: int = 5000
    max_pixels: int = 1920 * 1080
    analysis_timeout_seconds: float = 60.0
    sample_fps: Optional[float] = None
    tile_grid_max: int = 192
    strict_limits: bool = False

    def __post_init__(self) -> None:
        get_profile(self.standard)

        if not 0.0 < self.luminance_threshold <= 1.0:
            raise InvalidOptionsError("luminance_threshold must be in (0, 1]")
        if not 0.0 <= self.red_saturation <= 1.0:
            raise InvalidOptionsError("red_saturation must be in [0, 1]")
        if not 0.0 < self.red_color_difference <= 2.0:
            raise InvalidOptionsError("red_color_difference must be in (0, 2]")
        if self.max_flashes_per_second <= 0:
            raise InvalidOptionsError("max_flashes_per_second must be positive")
        if self.max_transition_duration_ms <= 0:
            raise InvalidOptionsError("max_transition_duration_ms must be positive")
        if self.synchronicity_window_ms < 0:
            raise InvalidOptionsError("synchronicity_window_ms cannot be negative")
        if self.fast_flash_hz <= 0:
            raise InvalidOptionsError("fast_flash_hz must be positive")
        if not 0.0 <= self.flash_area_overlap_ratio <= 1.0:
            raise InvalidOptionsError("flash_area_overlap_ratio must be in [0, 1]")
        if self.flash_area_union_scale < 1.0:
            raise InvalidOptionsError("flash_area_union_scale must be at least 1.0")
        if self.reference_luminance_cd_m2 <= 0:
            raise InvalidOptionsError("reference_luminance_cd_m2 must be positive")
        if self.color_space.lower() not in ("auto", "srgb"):
            raise InvalidOptionsError("color_space must be 'auto' or 'srgb'")
        if self.area_model is not None and self.area_model not in (
            "wcag_solid_angle",
            "screen_fraction",
        ):
            raise InvalidOptionsError(
                "area_model must be 'wcag_solid_angle', 'screen_fraction', or None"
            )

        subarea = tuple(self.area_subarea_css_px)
        if len(subarea) != 2 or subarea[0] <= 0 or subarea[1] <= 0:
            raise InvalidOptionsError("area_subarea_css_px must contain two positive values")
        object.__setattr__(self, "area_subarea_css_px", (int(subarea[0]), int(subarea[1])))

        if self.motion_compensation:
            raise InvalidOptionsError(
                "motion_compensation is experimental and is not implemented in this prototype"
            )
        if self.max_bytes <= 0 or self.max_frames <= 0 or self.max_pixels <= 0:
            raise InvalidOptionsError("resource limits must be positive")
        if self.max_duration_seconds <= 0 or self.analysis_timeout_seconds <= 0:
            raise InvalidOptionsError("time limits must be positive")
        if self.sample_fps is not None and self.sample_fps <= 0:
            raise InvalidOptionsError("sample_fps must be positive when set")
        if not 8 <= self.tile_grid_max <= 256:
            raise InvalidOptionsError("tile_grid_max must be between 8 and 256")

    def resolved_profile(self) -> StandardProfile:
        return get_profile(self.standard)

    def resolved_area_model(self, profile: Optional[StandardProfile] = None) -> str:
        if self.area_model is not None:
            return self.area_model
        return (profile or self.resolved_profile()).area_model

    @property
    def max_transitions_per_second(self) -> int:
        return int(round(self.max_flashes_per_second * 2.0))

    @property
    def effective_color_space(self) -> str:
        return "srgb"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "standard": self.standard,
            "luminance_threshold": self.luminance_threshold,
            "red_saturation": self.red_saturation,
            "red_color_difference": self.red_color_difference,
            "max_flashes_per_second": self.max_flashes_per_second,
            "max_transition_duration_ms": self.max_transition_duration_ms,
            "synchronicity_window_ms": self.synchronicity_window_ms,
            "fast_flash_hz": self.fast_flash_hz,
            "enable_fast_flash_merge": self.enable_fast_flash_merge,
            "flash_area_overlap_ratio": self.flash_area_overlap_ratio,
            "flash_area_union_scale": self.flash_area_union_scale,
            "area_model": self.area_model,
            "area_subarea_css_px": list(self.area_subarea_css_px),
            "display": self.display.to_dict() if self.display else None,
            "reference_luminance_cd_m2": self.reference_luminance_cd_m2,
            "color_space": self.color_space,
            "motion_compensation": self.motion_compensation,
            "extended_exposure": self.extended_exposure,
            "max_bytes": self.max_bytes,
            "max_duration_seconds": self.max_duration_seconds,
            "max_frames": self.max_frames,
            "max_pixels": self.max_pixels,
            "analysis_timeout_seconds": self.analysis_timeout_seconds,
            "sample_fps": self.sample_fps,
            "tile_grid_max": self.tile_grid_max,
            "strict_limits": self.strict_limits,
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
