"""Behavioral tests for transition counting and area qualification."""

from __future__ import annotations

import unittest

import numpy as np

from epilepsy_warning import AnalysisOptions, analyze_frames
from epilepsy_warning.area import AreaEvaluator, TileGrid
from epilepsy_warning.engine import TransitionEngine, TransitionEvent
from epilepsy_warning.result import SCHEMA_VERSION


def options(**overrides):
    base = {
        "area_model": "screen_fraction",
        "tile_grid_max": 64,
    }
    base.update(overrides)
    return AnalysisOptions(**base)


def uniform_sequence(count, dt=0.04, size=48):
    frames = []
    timestamps = []
    for index in range(count):
        value = 0 if index % 2 == 0 else 255
        frames.append(np.full((size, size, 3), value, dtype=np.uint8))
        timestamps.append(index * dt)
    return frames, timestamps


class TransitionRateTests(unittest.TestCase):
    def test_six_transitions_are_not_triggering(self) -> None:
        result = analyze_frames(*uniform_sequence(7), options=options())
        self.assertFalse(result.is_triggering)
        self.assertEqual(result.measurements.luminance_transitions, 6)
        self.assertEqual(result.measurements.max_luminance_transitions_per_second, 6)

    def test_seven_transitions_are_triggering(self) -> None:
        result = analyze_frames(*uniform_sequence(8), options=options())
        self.assertTrue(result.is_triggering)
        self.assertIn("luminance_transition_rate_exceeded", result.reasons)
        self.assertEqual(result.measurements.luminance_transitions, 7)
        self.assertEqual(result.measurements.max_luminance_transitions_per_second, 7)

    def test_slow_fade_is_not_a_transition(self) -> None:
        frames = []
        timestamps = []
        for index in range(11):
            value = int(round(255 * index / 10.0))
            frames.append(np.full((48, 48, 3), value, dtype=np.uint8))
            timestamps.append(index * 0.05)
        result = analyze_frames(frames, timestamps, options=options())
        self.assertFalse(result.is_triggering)
        self.assertEqual(result.measurements.luminance_transitions, 0)

    def test_sixty_millisecond_transition_is_counted(self) -> None:
        frames = [
            np.zeros((48, 48, 3), dtype=np.uint8),
            np.full((48, 48, 3), 255, dtype=np.uint8),
            np.zeros((48, 48, 3), dtype=np.uint8),
        ]
        result = analyze_frames(frames, [0.0, 0.06, 0.12], options=options())
        self.assertEqual(result.measurements.luminance_transitions, 2)
        self.assertAlmostEqual(result.measurements.max_transition_duration_ms, 60.0, places=3)

    def test_unresolved_single_frame_step_is_instantaneous(self) -> None:
        # A single-frame step sampled every 70 ms cannot resolve a transition
        # shorter than the 66 ms cutoff.  The engine keeps the only evidence of
        # a possible hard cut and reports it as instantaneous (duration 0)
        # instead of discarding it.
        frames = [
            np.zeros((48, 48, 3), dtype=np.uint8),
            np.full((48, 48, 3), 255, dtype=np.uint8),
            np.zeros((48, 48, 3), dtype=np.uint8),
        ]
        result = analyze_frames(frames, [0.0, 0.07, 0.14], options=options())
        self.assertEqual(result.measurements.luminance_transitions, 2)
        self.assertAlmostEqual(result.measurements.max_transition_duration_ms, 0.0, places=3)


class AreaTests(unittest.TestCase):
    @staticmethod
    def patch_sequence(patch: int):
        frames = []
        timestamps = []
        start = (48 - patch) // 2
        for index in range(8):
            frame = np.zeros((48, 48, 3), dtype=np.uint8)
            if index % 2 == 1:
                frame[start : start + patch, start : start + patch] = 255
            frames.append(frame)
            timestamps.append(index * 0.04)
        return frames, timestamps

    def test_small_area_is_not_counted(self) -> None:
        result = analyze_frames(*self.patch_sequence(20), options=options())
        self.assertFalse(result.is_triggering)
        self.assertEqual(result.measurements.luminance_transitions, 0)

    def test_large_area_is_counted(self) -> None:
        result = analyze_frames(*self.patch_sequence(26), options=options())
        self.assertTrue(result.is_triggering)
        self.assertEqual(result.measurements.luminance_transitions, 7)
        self.assertGreaterEqual(result.measurements.max_area_px2, 26 * 26)


class RedTests(unittest.TestCase):
    def test_saturated_red_flashes_are_counted_separately(self) -> None:
        red = np.array([255, 0, 0], dtype=np.uint8)
        # sRGB 128 has almost exactly the same relative luminance as pure red.
        gray = np.array([128, 128, 128], dtype=np.uint8)
        frames = []
        timestamps = []
        for index in range(8):
            color = red if index % 2 == 1 else gray
            frames.append(np.broadcast_to(color, (48, 48, 3)).copy())
            timestamps.append(index * 0.04)

        result = analyze_frames(frames, timestamps, options=options())
        self.assertTrue(result.is_triggering)
        self.assertIn("red_transition_rate_exceeded", result.reasons)
        self.assertEqual(result.measurements.red_transitions, 7)
        self.assertEqual(result.measurements.luminance_transitions, 0)


class FastFlashTests(unittest.TestCase):
    def test_fast_sequence_is_merged(self) -> None:
        frames, timestamps = uniform_sequence(220, dt=0.005)
        merged = analyze_frames(frames, timestamps, options=options())
        unmerged = analyze_frames(
            frames,
            timestamps,
            options=options(enable_fast_flash_merge=False),
        )

        self.assertFalse(merged.is_triggering)
        self.assertEqual(merged.measurements.luminance_transitions, 2)
        self.assertEqual(merged.measurements.fast_flash_sequences, 1)
        self.assertTrue(unmerged.is_triggering)


class FlashAreaMotionTests(unittest.TestCase):
    """Opposing transitions must change the same region, not just move edges."""

    def setUp(self) -> None:
        settings = options()
        self.grid = TileGrid.for_size(48, 48, settings.tile_grid_max)
        self.area = AreaEvaluator(self.grid, settings, "screen_fraction")
        self.engine = TransitionEngine(
            settings,
            settings.resolved_profile(),
            self.area,
        )
        self.assertAlmostEqual(self.area.threshold_px2, 576.0)

    def mask(self, start: int, stop: int) -> np.ndarray:
        mask = np.zeros((self.grid.rows, self.grid.cols), dtype=bool)
        mask.ravel()[start:stop] = True
        return mask

    def event(self, direction: int, mask: np.ndarray, timestamp: float) -> TransitionEvent:
        return TransitionEvent(
            kind="luminance",
            direction=direction,
            start_time=timestamp,
            duration_ms=40.0,
            mask=mask,
            area=self.area.evaluate(mask),
        )

    def test_disjoint_edges_are_not_a_flash(self) -> None:
        # Union is 700 tiles (above the 576 px2 threshold but below the 1.5x
        # large-area escape), and only 100 tiles overlap.
        events = [
            self.event(1, self.mask(0, 400), 0.0),
            self.event(-1, self.mask(300, 700), 0.04),
        ]
        self.assertEqual(self.engine._qualify_by_flash_area(events), [])

    def test_overlapping_edges_are_a_flash(self) -> None:
        events = [
            self.event(1, self.mask(0, 400), 0.0),
            self.event(-1, self.mask(50, 700), 0.04),
        ]
        self.assertEqual(len(self.engine._qualify_by_flash_area(events)), 2)

    def test_large_changed_area_skips_the_overlap_guard(self) -> None:
        # Texture fragments the overlap; a whole-screen change is kept.
        events = [
            self.event(1, self.mask(0, 900), 0.0),
            self.event(-1, self.mask(900, 1800), 0.04),
        ]
        self.assertEqual(len(self.engine._qualify_by_flash_area(events)), 2)


class ResultSchemaTests(unittest.TestCase):
    def test_result_contains_assumptions_and_provenance(self) -> None:
        result = analyze_frames(*uniform_sequence(8), options=options())
        payload = result.to_dict()

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["standard"]["id"], "wcag22")
        self.assertEqual(payload["standard"]["profile_coverage"], "partial")
        self.assertEqual(payload["risk"], "triggering")
        self.assertIn("not_a_compliance_determination", payload["warnings"])
        self.assertIn("profile_coverage_partial", payload["warnings"])
        self.assertEqual(payload["assumptions"]["max_transition_duration_ms"], 66.0)
        self.assertEqual(payload["assumptions"]["synchronicity_window_ms"], 20.0)
        self.assertEqual(payload["assumptions"]["fast_flash_hz"], 65.0)
        self.assertEqual(payload["measurements"]["frames_analyzed"], 8)
        self.assertFalse(payload["assumptions"]["display_assumed"])

        import json

        self.assertEqual(json.loads(result.to_json())["schema_version"], SCHEMA_VERSION)

    def test_unknown_profile_is_rejected(self) -> None:
        from epilepsy_warning import InvalidOptionsError

        with self.assertRaises(InvalidOptionsError):
            AnalysisOptions(standard="not-a-standard")


if __name__ == "__main__":
    unittest.main()
