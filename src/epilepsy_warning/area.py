"""Tiling and area normalization.

The WCAG default is a solid-angle rule: 0.006 steradians within any 10-degree
field of view (25% of that field).  For an unknown screen the paper normalizes
this to 25% of any 416 x 416 CSS-pixel subarea.  Broadcast profiles may instead
request 25% of the displayed screen; that is an explicit, less conservative
choice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np
from PIL import Image

try:
    from line_profiler import profile  # type: ignore
except ImportError:
    def profile(func):  # type: ignore
        return func

from .options import AnalysisOptions, DisplayGeometry

_FIELD_OF_VIEW_DEGREES = 10.0


@dataclass(frozen=True)
class TileGrid:
    """A coarse spatial grid used for per-tile state tracking."""

    width: int
    height: int
    cols: int
    rows: int

    @classmethod
    def for_size(cls, width: int, height: int, max_tiles: int = 64) -> "TileGrid":
        if width <= 0 or height <= 0:
            raise ValueError("frame dimensions must be positive")
        scale = min(float(max_tiles) / float(width), float(max_tiles) / float(height), 1.0)
        cols = max(1, int(round(width * scale)))
        rows = max(1, int(round(height * scale)))
        cols = min(cols, max_tiles)
        rows = min(rows, max_tiles)
        return cls(width=width, height=height, cols=cols, rows=rows)

    @property
    def tile_width_px(self) -> float:
        return self.width / float(self.cols)

    @property
    def tile_height_px(self) -> float:
        return self.height / float(self.rows)

    @property
    def tile_area_px2(self) -> float:
        return self.tile_width_px * self.tile_height_px

    def to_dict(self) -> dict:
        return {
            "columns": self.cols,
            "rows": self.rows,
            "tile_width_px": round(self.tile_width_px, 4),
            "tile_height_px": round(self.tile_height_px, 4),
        }


@profile
def tile_frame(frame: np.ndarray, grid: TileGrid) -> np.ndarray:
    """Downsample an RGB(A) frame to the tile grid.

    Returns a float32 array in the range 0..1 with shape ``(rows, cols, 3)``.
    Tile colors are box-filtered sRGB averages before gamma expansion; that is
    an explicit approximation and is reported in the result warnings.
    """
    array = np.asarray(frame)
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError("frames must be HxWx3 or HxWx4")

    if array.dtype.kind == "f":
        array = (np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    elif array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)

    array = np.ascontiguousarray(array)
    if array.shape[2] == 3 and (grid.rows, grid.cols) == array.shape[:2]:
        # The grid is already at source resolution (small inputs).  A BOX
        # resize to the same size is a copy, so skip the PIL round trip.
        output = array.astype(np.float32)
        output /= 255.0
        return output

    if array.shape[2] == 4:
        rgba = Image.fromarray(array, mode="RGBA")
        background = Image.new("RGB", rgba.size, (0, 0, 0))
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = Image.fromarray(array, mode="RGB")

    resized = image.resize((grid.cols, grid.rows), Image.Resampling.BOX)
    # Convert in place: an out-of-place division would allocate a second
    # float32 array for every frame.  In-place division keeps the values
    # bit-for-bit identical to the previous implementation.
    output = np.asarray(resized, dtype=np.float32)
    output /= 255.0
    return output


@dataclass(frozen=True)
class AreaEvaluation:
    area_px2: float
    threshold_px2: float
    qualifies: bool
    screen_fraction: float

    @property
    def area_ratio(self) -> float:
        if self.threshold_px2 <= 0:
            return 0.0
        return self.area_px2 / self.threshold_px2

    def to_dict(self) -> dict:
        return {
            "area_px2": round(self.area_px2, 2),
            "threshold_px2": round(self.threshold_px2, 2),
            "area_ratio": round(self.area_ratio, 4),
            "screen_fraction": round(self.screen_fraction, 4),
            "qualifies": self.qualifies,
        }


class AreaEvaluator:
    """Evaluate a tile mask against the active area model."""

    def __init__(
        self,
        grid: TileGrid,
        options: AnalysisOptions,
        area_model: str,
    ) -> None:
        self.grid = grid
        self.options = options
        self.area_model = area_model
        nominal_width, nominal_height = self._compute_field_size()

        # With no display geometry the nominal 416 x 416 CSS-px field is an
        # upper bound on the content's assumed viewing size.  If the source
        # is smaller in either dimension, assume it can fill at least the
        # corresponding part of a 10-degree field; the effective field is then
        # clamped to the source.  This is an explicit display-size assumption,
        # not a measured geometry, and it only lowers the area threshold for
        # sources smaller than the nominal field.
        if area_model == "wcag_solid_angle" and options.display is None:
            self.field_width_px = min(nominal_width, float(grid.width))
            self.field_height_px = min(nominal_height, float(grid.height))
            self.source_scaled = (
                self.field_width_px < nominal_width or self.field_height_px < nominal_height
            )
        else:
            self.field_width_px = nominal_width
            self.field_height_px = nominal_height
            self.source_scaled = False

        if area_model == "screen_fraction":
            self.base_threshold_px2 = 0.25 * grid.width * grid.height
            self.threshold_px2 = self.base_threshold_px2
        elif area_model == "wcag_solid_angle":
            self.base_threshold_px2 = 0.25 * nominal_width * nominal_height
            self.threshold_px2 = 0.25 * self.field_width_px * self.field_height_px
        else:
            raise ValueError("unknown area model %r" % area_model)

        if self.field_width_px < grid.width:
            self._window_cols = min(
                grid.cols,
                max(1, int(math.ceil(self.field_width_px / grid.tile_width_px))),
            )
        else:
            self._window_cols = grid.cols
        if self.field_height_px < grid.height:
            self._window_rows = min(
                grid.rows,
                max(1, int(math.ceil(self.field_height_px / grid.tile_height_px))),
            )
        else:
            self._window_rows = grid.rows

    def _compute_field_size(self) -> Tuple[float, float]:
        if self.area_model != "wcag_solid_angle":
            return float(self.grid.width), float(self.grid.height)

        display = self.options.display
        if display is None:
            subarea = self.options.area_subarea_css_px
            return float(subarea[0]), float(subarea[1])
        return self._field_from_display(display)

    def _field_from_display(self, display: DisplayGeometry) -> Tuple[float, float]:
        """Map a 10-degree field onto content pixels for known geometry."""
        diagonal_cm = display.screen_diagonal_in * 2.54
        aspect = display.aspect_ratio
        screen_width_cm = diagonal_cm * aspect / math.sqrt(1.0 + aspect * aspect)
        screen_height_cm = screen_width_cm / aspect
        distance = display.viewing_distance_cm

        angular_width_deg = math.degrees(2.0 * math.atan((screen_width_cm / 2.0) / distance))
        angular_height_deg = math.degrees(2.0 * math.atan((screen_height_cm / 2.0) / distance))
        if angular_width_deg <= 0 or angular_height_deg <= 0:
            return float(self.grid.width), float(self.grid.height)

        field_width = self.grid.width * (_FIELD_OF_VIEW_DEGREES / angular_width_deg)
        field_height = self.grid.height * (_FIELD_OF_VIEW_DEGREES / angular_height_deg)
        return field_width, field_height

    @property
    def uses_assumed_display(self) -> bool:
        return self.area_model == "wcag_solid_angle" and self.options.display is None

    @profile
    def evaluate(self, mask: np.ndarray) -> AreaEvaluation:
        mask = np.asarray(mask, dtype=bool)
        if mask.shape != (self.grid.rows, self.grid.cols):
            raise ValueError("tile mask has the wrong shape")

        tile_area = self.grid.tile_area_px2
        total_area = float(mask.sum()) * tile_area
        if self.area_model == "screen_fraction":
            local_area = total_area
        elif self._window_cols == self.grid.cols and self._window_rows == self.grid.rows:
            local_area = total_area
        else:
            weighted = mask.astype(np.float64) * tile_area
            prefix = np.pad(weighted.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))
            rows = self._window_rows
            cols = self._window_cols
            sums = (
                prefix[rows:, cols:]
                - prefix[:-rows, cols:]
                - prefix[rows:, :-cols]
                + prefix[:-rows, :-cols]
            )
            local_area = float(sums.max()) if sums.size else total_area

        screen_area = float(self.grid.width * self.grid.height)
        return AreaEvaluation(
            area_px2=local_area,
            threshold_px2=self.threshold_px2,
            qualifies=local_area >= self.threshold_px2,
            screen_fraction=(local_area / screen_area) if screen_area > 0 else 0.0,
        )

    def to_dict(self) -> dict:
        return {
            "area_model": self.area_model,
            "field_width_px": round(self.field_width_px, 3),
            "field_height_px": round(self.field_height_px, 3),
            "base_threshold_px2": round(self.base_threshold_px2, 3),
            "threshold_px2": round(self.threshold_px2, 3),
            "source_scaled": self.source_scaled,
            "window_tiles": [self._window_cols, self._window_rows],
            "display_assumed": self.uses_assumed_display,
            "tile_grid": self.grid.to_dict(),
        }
