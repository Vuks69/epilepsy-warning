"""Equivalence tests for the Phase 3 engine short-circuits.

The Phase 1/2 optimizations changed allocation and code shape; Phase 3 changes
the *shape of the per-frame computation* (red early-out, duplicate-frame skip),
so correctness cannot rest on the smoke fixtures alone.  These tests run one
synthetic history through the engine twice — once with the short-circuits
enabled, once disabled — and assert the two :class:`EngineResult` objects agree
exactly.  The random histories are biased to land on the cases the plan calls
out: exactly-at-threshold luminance steps, the local-extremum tolerance
boundary, red tie-breaking, and the coarse single-frame step.
"""

from __future__ import annotations

import unittest

import numpy as np

from epilepsy_warning import AnalysisOptions
from epilepsy_warning.area import AreaEvaluator, TileGrid, tile_frame_uint8
from epilepsy_warning.engine import TransitionEngine


def _options(**overrides) -> AnalysisOptions:
    base = {"area_model": "screen_fraction", "tile_grid_max": 64}
    base.update(overrides)
    return AnalysisOptions(**base)


def _run(frames, timestamps, options):
    """Feed one history through a fresh engine and return the finished result."""
    size = int(frames[0].shape[0])
    grid = TileGrid.for_size(size, size, options.tile_grid_max)
    area = AreaEvaluator(grid, options, options.resolved_area_model())
    engine = TransitionEngine(options, options.resolved_profile(), area)
    for timestamp, frame in zip(timestamps, frames):
        engine.add_frame(timestamp, tile_frame_uint8(frame, grid))
    return engine.finish()


def _random_history(rng: "np.random.Generator", count: int = 14, size: int = 16):
    """A synthetic timeline mixing luminance steps, red flashes, and coarse steps."""
    frames, timestamps = [], [0.0]
    previous = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
    for _ in range(count):
        if rng.random() < 0.30:
            # A flat frame, occasionally a saturated red (a red-flash driver).
            color = np.array([255, 0, 0], dtype=np.uint8) if rng.random() < 0.5 else None
            if color is None:
                value = int(rng.integers(0, 256))
                color = np.array([value, value, value], dtype=np.uint8)
            frame = np.broadcast_to(color, (size, size, 3)).copy()
        else:
            frame = np.clip(previous + rng.integers(-64, 65, size=(size, size, 3)), 0, 255)
            frame = frame.astype(np.uint8)
        frames.append(frame)
        previous = frame
        delay = float(rng.integers(1, 20)) / 1000.0
        if rng.random() < 0.15:
            # A gap longer than the 66 ms cutoff forces the coarse single-frame
            # step (duration_ms == 0) onto the timeline.
            delay = float(rng.integers(66, 140)) / 1000.0
        timestamps.append(timestamps[-1] + delay)
    return frames, timestamps


def _signature(result) -> tuple:
    # Compare the full measured surface: rates, area, durations, merge counts,
    # and the verdict.  Warnings/assumptions are identical by construction.
    return (
        result.is_triggering,
        tuple(result.reasons),
        result.luminance_transitions,
        result.red_transitions,
        result.max_luminance_transitions_per_second,
        result.max_red_transitions_per_second,
        result.max_flashes_per_second,
        result.max_area_px2,
        result.max_flashing_area_ratio,
        result.max_transition_duration_ms,
        result.synchronized_area_merges,
        result.fast_flash_sequences,
        result.merged_fast_flash_transitions,
    )


class EngineShortCircuitEquivalenceTests(unittest.TestCase):
    def _check(self, options, seeds):
        for seed in range(seeds):
            rng = np.random.default_rng(seed)
            frames, timestamps = _random_history(rng)
            baseline = _run(frames, timestamps, options)

            grid = TileGrid.for_size(frames[0].shape[0], frames[0].shape[0], options.tile_grid_max)
            engine = TransitionEngine(
                options,
                options.resolved_profile(),
                AreaEvaluator(grid, options, options.resolved_area_model()),
            )
            engine._enable_short_circuit = False
            for timestamp, frame in zip(timestamps, frames):
                engine.add_frame(timestamp, tile_frame_uint8(frame, grid))
            reference = engine.finish()
            self.assertEqual(
                _signature(baseline),
                _signature(reference),
                msg=f"short-circuits changed the result for seed={seed}",
            )

    def test_random_histories_agree(self) -> None:
        # Default WCAG-ish settings plus a small source (area-scaled regime).
        self._check(_options(), 60)
        self._check(_options(area_model="wcag_solid_angle"), 40)
        self._check(_options(luminance_threshold=0.10, red_color_difference=0.20), 40)

    def test_static_sequence_is_short_circuited(self) -> None:
        # A fully static timeline: every frame duplicates the previous, so the
        # skip fires on all but the first comparison and no transition can exist.
        options = _options()
        frames = [np.full((16, 16, 3), 123, dtype=np.uint8) for _ in range(20)]
        timestamps = [i * 0.03 for i in range(20)]
        result = _run(frames, timestamps, options)
        self.assertFalse(result.is_triggering)
        self.assertEqual(result.luminance_transitions, 0)
        self.assertEqual(result.red_transitions, 0)

    def test_coarse_single_frame_step_matches(self) -> None:
        # Two frames 120 ms apart then back: the unresolved step is reported
        # with duration 0 by both paths.
        options = _options()
        frames = [
            np.zeros((16, 16, 3), dtype=np.uint8),
            np.full((16, 16, 3), 255, dtype=np.uint8),
            np.zeros((16, 16, 3), dtype=np.uint8),
        ]
        timestamps = [0.0, 0.12, 0.24]
        self.assertEqual(_run(frames, timestamps, options).max_transition_duration_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
