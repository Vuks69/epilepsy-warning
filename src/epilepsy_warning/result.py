"""Result schema v2.

Results are plain data and JSON-serializable.  They report measurements,
working values, and assumptions alongside the verdict so a consumer can tell
what was actually checked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 2


@dataclass(frozen=True)
class StandardInfo:
    id: str
    version: str
    profile_coverage: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "profile_coverage": self.profile_coverage,
        }


@dataclass(frozen=True)
class Measurements:
    luminance_transitions: int = 0
    red_transitions: int = 0
    max_luminance_transitions_per_second: int = 0
    max_red_transitions_per_second: int = 0
    max_luminance_flashes_per_second: float = 0.0
    max_red_flashes_per_second: float = 0.0
    max_flashes_per_second: float = 0.0
    max_area_px2: float = 0.0
    area_threshold_px2: float = 0.0
    max_flashing_area_ratio: float = 0.0
    max_flashing_area_screen_fraction: float = 0.0
    max_transition_duration_ms: float = 0.0
    synchronized_area_merges: int = 0
    fast_flash_sequences: int = 0
    merged_fast_flash_transitions: int = 0
    duration_seconds: float = 0.0
    frames_analyzed: int = 0
    sampled_fps: float = 0.0

    def to_dict(self) -> dict:
        return {
            "luminance_transitions": self.luminance_transitions,
            "red_transitions": self.red_transitions,
            "max_luminance_transitions_per_second": self.max_luminance_transitions_per_second,
            "max_red_transitions_per_second": self.max_red_transitions_per_second,
            "max_luminance_flashes_per_second": round(self.max_luminance_flashes_per_second, 3),
            "max_red_flashes_per_second": round(self.max_red_flashes_per_second, 3),
            "max_flashes_per_second": round(self.max_flashes_per_second, 3),
            "max_area_px2": round(self.max_area_px2, 2),
            "area_threshold_px2": round(self.area_threshold_px2, 2),
            "max_flashing_area_ratio": round(self.max_flashing_area_ratio, 4),
            "max_flashing_area_screen_fraction": round(self.max_flashing_area_screen_fraction, 4),
            "max_transition_duration_ms": round(self.max_transition_duration_ms, 3),
            "synchronized_area_merges": self.synchronized_area_merges,
            "fast_flash_sequences": self.fast_flash_sequences,
            "merged_fast_flash_transitions": self.merged_fast_flash_transitions,
            "duration_seconds": round(self.duration_seconds, 4),
            "frames_analyzed": self.frames_analyzed,
            "sampled_fps": round(self.sampled_fps, 3),
        }


@dataclass(frozen=True)
class Assumptions:
    color_space: str
    luminance_model: str
    reference_luminance_cd_m2: float
    max_transition_duration_ms: float
    synchronicity_window_ms: float
    fast_flash_hz: float
    fast_flash_merge_enabled: bool
    flash_area_overlap_ratio: float
    flash_area_union_scale: float
    flash_area_scaled_overlap_ratio: float
    flash_area_frame_fraction: float
    max_flashes_per_second: float
    max_transitions_per_second: int
    area_model: str
    area_subarea_css_px: Tuple[int, int]
    display_assumed: bool
    display_geometry: Optional[Dict[str, float]]
    tile_grid: Dict[str, Any]
    field_width_px: float
    field_height_px: float
    area_base_threshold_px2: float
    area_source_scaled: bool

    def to_dict(self) -> dict:
        return {
            "color_space": self.color_space,
            "luminance_model": self.luminance_model,
            "reference_luminance_cd_m2": self.reference_luminance_cd_m2,
            "max_transition_duration_ms": self.max_transition_duration_ms,
            "synchronicity_window_ms": self.synchronicity_window_ms,
            "fast_flash_hz": self.fast_flash_hz,
            "fast_flash_merge_enabled": self.fast_flash_merge_enabled,
            "flash_area_overlap_ratio": self.flash_area_overlap_ratio,
            "flash_area_union_scale": self.flash_area_union_scale,
            "flash_area_scaled_overlap_ratio": self.flash_area_scaled_overlap_ratio,
            "flash_area_frame_fraction": self.flash_area_frame_fraction,
            "max_flashes_per_second": self.max_flashes_per_second,
            "max_transitions_per_second": self.max_transitions_per_second,
            "area_model": self.area_model,
            "area_subarea_css_px": list(self.area_subarea_css_px),
            "display_assumed": self.display_assumed,
            "display_geometry": self.display_geometry,
            "tile_grid": self.tile_grid,
            "field_width_px": round(self.field_width_px, 3),
            "field_height_px": round(self.field_height_px, 3),
            "area_base_threshold_px2": round(self.area_base_threshold_px2, 3),
            "area_source_scaled": self.area_source_scaled,
        }


@dataclass(frozen=True)
class MediaInfo:
    format: str
    width: int
    height: int
    bytes: Optional[int]
    color_space: str
    transfer: str

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "bytes": self.bytes,
            "color_space": self.color_space,
            "transfer": self.transfer,
        }


@dataclass(frozen=True)
class AnalyzerInfo:
    name: str
    version: str
    options_hash: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "options_hash": self.options_hash,
        }


@dataclass(frozen=True)
class AnalysisResult:
    standard: StandardInfo
    is_triggering: bool
    risk: str
    inconclusive: bool
    reasons: List[str]
    measurements: Measurements
    assumptions: Assumptions
    media: MediaInfo
    warnings: List[str]
    analyzer: AnalyzerInfo
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "standard": self.standard.to_dict(),
            "is_triggering": self.is_triggering,
            "risk": self.risk,
            "inconclusive": self.inconclusive,
            "reasons": list(self.reasons),
            "measurements": self.measurements.to_dict(),
            "assumptions": self.assumptions.to_dict(),
            "media": self.media.to_dict(),
            "warnings": list(self.warnings),
            "analyzer": self.analyzer.to_dict(),
        }

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)
