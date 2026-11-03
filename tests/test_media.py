"""Decoder and CLI integration tests using small generated media."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from epilepsy_warning import (
    AnalysisOptions,
    LimitExceededError,
    UnsupportedInputError,
    analyze_bytes,
    analyze_file,
)
from epilepsy_warning.area import AreaEvaluator, TileGrid
from epilepsy_warning.cli import main
from epilepsy_warning.decode import _alpha_composite_rgba, decode_file
from epilepsy_warning.engine import _QUICK_MAX_CONFIRMATIONS, TransitionEngine
from epilepsy_warning.standards import get_profile


def options(**overrides):
    base = {"area_model": "screen_fraction", "tile_grid_max": 64}
    base.update(overrides)
    return AnalysisOptions(**base)


def alternating_frames(count=8, size=48):
    return [
        np.full((size, size, 3), 0 if index % 2 == 0 else 255, dtype=np.uint8)
        for index in range(count)
    ]


def solid(value: int) -> np.ndarray:
    return np.full((48, 48, 3), value, dtype=np.uint8)


def make_engine(quick=True):
    """Build a TransitionEngine over a 48x48 screen_fraction grid.

    Frames are fed directly as tile-grid tiles (the grid is 48x48 at the test
    options' tile_grid_max=64), so one frame boundary is one transition.
    """
    grid = TileGrid.for_size(48, 48, 64)
    opts = options(quick=quick, area_model="screen_fraction")
    area = AreaEvaluator(grid, opts, "screen_fraction")
    return TransitionEngine(opts, get_profile("wcag22"), area)


def write_gif(path):
    frames = [Image.fromarray(frame, mode="RGB") for frame in alternating_frames()]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=40,
        loop=0,
    )


def write_transparent_gif(path):
    """An opaque frame, then transparent frames with disposal to background."""
    opaque = Image.new("RGBA", (48, 48), (0, 0, 0, 255))
    frames = [opaque]
    for top in (18, 10):
        frame = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
        for y in range(top, top + 12):
            for x in range(top, top + 12):
                frame.putpixel((x, y), (255, 255, 255, 255))
        frames.append(frame)
    opaque.save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=[40, 40, 40],
        # Use a finite loop count so this stays a compositing test.  With
        # loop=0 the decoder repeats the short clip for a full analysis window,
        # and the black/white cycle becomes a real flash.
        loop=1,
        disposal=[2, 2, 2],
        optimize=False,
    )


def write_disposal_previous_gif(path):
    """Frame 1 must be undone before frame 2 (disposal method 3)."""
    black = Image.new("RGBA", (48, 48), (0, 0, 0, 255))

    white_patch = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    for y in range(18, 30):
        for x in range(18, 30):
            white_patch.putpixel((x, y), (255, 255, 255, 255))

    red_patch = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    for y in range(6, 18):
        for x in range(6, 18):
            red_patch.putpixel((x, y), (255, 0, 0, 255))

    black.save(
        path,
        save_all=True,
        append_images=[white_patch, red_patch],
        duration=[40, 40, 40],
        loop=1,
        disposal=[1, 3, 1],
        optimize=False,
    )


class AlphaCompositeTests(unittest.TestCase):
    def test_numpy_compositing_matches_pillow(self) -> None:
        rng = np.random.default_rng(5)
        for _ in range(20):
            height, width = (int(value) for value in rng.integers(1, 8, 2))
            destination = rng.integers(0, 256, (height, width, 4), dtype=np.uint8)
            source = rng.integers(0, 256, (height, width, 4), dtype=np.uint8)
            expected = np.asarray(
                Image.alpha_composite(
                    Image.fromarray(destination, mode="RGBA"),
                    Image.fromarray(source, mode="RGBA"),
                )
            )
            np.testing.assert_array_equal(_alpha_composite_rgba(destination, source), expected)

    def test_opaque_and_transparent_sources_take_cheap_paths(self) -> None:
        destination = np.full((2, 2, 4), 7, dtype=np.uint8)
        opaque = np.full((2, 2, 4), 9, dtype=np.uint8)
        opaque[..., 3] = 255
        transparent = np.zeros((2, 2, 4), dtype=np.uint8)
        transparent[..., :3] = 200

        self.assertIs(_alpha_composite_rgba(destination, opaque), opaque)
        self.assertIs(_alpha_composite_rgba(destination, transparent), destination)


class MediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.gif_path = os.path.join(self.temporary.name, "flash.gif")
        write_gif(self.gif_path)

    def test_analyze_gif_file(self) -> None:
        result = analyze_file(self.gif_path, options())
        self.assertTrue(result.is_triggering)
        self.assertEqual(result.media.format, "gif")
        self.assertEqual((result.media.width, result.media.height), (48, 48))
        self.assertGreaterEqual(result.measurements.frames_analyzed, 8)
        self.assertIn("gif_loop_repeated_analysis", result.warnings)

    def test_analyze_gif_bytes(self) -> None:
        with open(self.gif_path, "rb") as handle:
            data = handle.read()
        result = analyze_bytes(data, options())
        self.assertTrue(result.is_triggering)
        self.assertEqual(result.media.format, "gif")

    def test_transparent_gif_is_composited_over_white(self) -> None:
        path = os.path.join(self.temporary.name, "transparent.gif")
        write_transparent_gif(path)

        records, state = decode_file(path, options())
        frames = [np.asarray(record.data) for record in records]
        self.assertIn("transparency_composited_white", state.warnings)
        self.assertTrue(np.all(frames[0][0, 0] < 10))
        # Disposal 2 clears the opaque first frame to the white canvas, so the
        # transparent corner of frame 1 must not show the previous dark frame.
        self.assertTrue(np.all(frames[1][0, 0] > 245))

        result = analyze_file(path, options())
        self.assertFalse(result.is_triggering)
        self.assertIn("transparency_composited_white", result.warnings)

    def test_disposal_previous_restores_the_canvas(self) -> None:
        path = os.path.join(self.temporary.name, "disposal-previous.gif")
        write_disposal_previous_gif(path)

        records, _ = decode_file(path, options())
        frames = [np.asarray(record.data) for record in records]
        self.assertEqual(len(frames), 3)

        # Frame 1 paints a white patch, then disposal 3 restores the black
        # canvas before frame 2.  The old patch location must be black again.
        self.assertTrue(np.all(frames[1][24, 24] > 245))
        self.assertTrue(np.all(frames[2][24, 24] < 10))
        self.assertGreater(int(frames[2][12, 12, 0]), 200)
        self.assertTrue(np.all(frames[2][12, 12, 1:] < 10))

    def test_static_image_is_safe(self) -> None:
        path = os.path.join(self.temporary.name, "still.png")
        Image.fromarray(alternating_frames(1)[0], mode="RGB").save(path)
        result = analyze_file(path, options())
        self.assertFalse(result.is_triggering)
        self.assertEqual(result.risk, "none")
        self.assertEqual(result.measurements.luminance_transitions, 0)
        self.assertIn("single_frame_media", result.warnings)

    def test_quick_mode_marks_a_partial_triggering_result(self) -> None:
        result = analyze_file(self.gif_path, options(quick=True))
        self.assertTrue(result.is_triggering)
        self.assertTrue(result.quick)
        self.assertIn("analysis_early_stopped", result.warnings)
        # It stops before the repeated-cycle scan completes.
        self.assertLess(result.measurements.frames_analyzed, 20)

    def test_quick_mode_full_scans_benign_content(self) -> None:
        path = os.path.join(self.temporary.name, "still.png")
        Image.fromarray(alternating_frames(1)[0], mode="RGB").save(path)
        result = analyze_file(path, options(quick=True))
        self.assertFalse(result.is_triggering)
        self.assertFalse(result.quick)
        self.assertNotIn("analysis_early_stopped", result.warnings)

    def test_quick_mode_keeps_media_duration_separate_from_analyzed_span(self) -> None:
        # A looping GIF reports its true media duration even though quick mode
        # stops after several synthetic repeat cycles. Media duration must never
        # be fabricated from synthetic timestamps; here the decoder was
        # abandoned, so media duration is unknown (0) while analyzed_span tells
        # how much was actually scanned.
        result = analyze_file(self.gif_path, options(quick=True, area_model="screen_fraction"))
        self.assertTrue(result.quick)
        self.assertGreater(result.measurements.analyzed_span_seconds, 0.0)
        self.assertEqual(result.measurements.duration_seconds, 0.0)

    def test_full_scan_reports_analyzed_span_seconds(self) -> None:
        # analyzed_span_seconds is populated for every result, not only for an
        # early-stop: a full scan reports how much was actually scanned.
        result = analyze_file(self.gif_path, options(area_model="screen_fraction"))
        self.assertFalse(result.quick)
        self.assertGreater(result.measurements.analyzed_span_seconds, 0.0)
        self.assertGreater(result.measurements.frames_analyzed, 8)

    def test_short_looping_gif_full_span_exceeds_media_duration(self) -> None:
        # A short looping GIF is repeated through several cycles for a full
        # scan, so the analyzed span exceeds the media's own one-loop duration.
        # The two values stay distinct: duration is the media's own duration,
        # analyzed_span is how much was actually scanned.
        result = analyze_file(self.gif_path, options(area_model="screen_fraction"))
        self.assertGreater(
            result.measurements.analyzed_span_seconds, result.measurements.duration_seconds
        )
        self.assertGreater(result.measurements.duration_seconds, 0.0)

    def test_quick_guard_counts_raw_transitions_before_qualification(self) -> None:
        # The quick guard trips on raw qualifying transitions measured *before*
        # area qualification, so it over-counts and errs toward flagging. This
        # deliberate recall bias is a probe, not a verdict: confirmation is the
        # authoritative finish, so content the full pass qualifies out is never
        # stopped on.
        engine = make_engine(quick=True)
        t = 0.0
        for i in range(60):
            t = i * 0.03
            frame = solid(0)
            frame[10:25, 10:25] = 255 if i % 2 == 0 else 0
            engine.add_frame(t, frame)
            engine.quick_should_finish(t)

        # Many raw buckets were created, but the qualifying full pass is safe:
        # each tiny flash is below the area threshold.
        self.assertGreater(len(engine._bucket_created_at), 6)
        verdict = engine.quick_finish()
        self.assertFalse(verdict.is_triggering)

    def test_quick_confirmations_are_throttled_to_max(self) -> None:
        # A dense stream of transitions trips the guard repeatedly; confirmations
        # are throttled to the cap so dense-but-safe content cannot drive
        # unbounded work.
        engine = make_engine(quick=True)
        t = 0.0
        for i in range(120):
            t = i * 0.015
            frame = solid(255 if i % 2 == 0 else 0)
            engine.add_frame(t, frame)
            if engine.quick_should_finish(t):
                engine.quick_finish()

        self.assertEqual(engine._quick_confirmations, _QUICK_MAX_CONFIRMATIONS)
        # Once capped, further probes stop running confirmations.
        for _ in range(30):
            if engine.quick_should_finish(t):
                engine.quick_finish()
        self.assertEqual(engine._quick_confirmations, _QUICK_MAX_CONFIRMATIONS)

    def test_quick_bucket_window_is_trimmed_not_growing(self) -> None:
        # The bucket deque is trimmed to ~1s before the cap check, so it holds at
        # most one second of transitions rather than the whole scan.
        engine = make_engine(quick=True)
        t = 0.0
        total = 0
        for i in range(90):
            t = i * 0.03
            frame = solid(255 if i % 2 == 0 else 0)
            engine.add_frame(t, frame)
            total += 1
        for _ in range(5):
            engine.quick_should_finish(t)

        self.assertLess(len(engine._bucket_created_at), total)
        self.assertGreaterEqual(len(engine._bucket_created_at), 15)

    def test_video_bytes_are_rejected(self) -> None:
        data = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
        with self.assertRaises(UnsupportedInputError):
            analyze_bytes(data, options())

    def test_byte_limit_is_enforced(self) -> None:
        with open(self.gif_path, "rb") as handle:
            data = handle.read()
        with self.assertRaises(LimitExceededError):
            analyze_bytes(data, options(max_bytes=8))


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.gif_path = os.path.join(self.temporary.name, "flash.gif")
        write_gif(self.gif_path)

    def test_json_output_and_exit_code(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--json", "--area-model", "screen_fraction", self.gif_path])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertTrue(payload["is_triggering"])
        self.assertEqual(payload["path"], self.gif_path)
        self.assertEqual(payload["schema_version"], 2)

    def test_default_output_is_one_line_with_reasons(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--area-model", "screen_fraction", self.gif_path])
        self.assertEqual(code, 1)
        lines = output.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("TRIGGERING", lines[0])
        self.assertIn(self.gif_path, lines[0])
        self.assertIn("luminance_transition_rate_exceeded", lines[0])
        self.assertNotIn("rate:", lines[0])

    def test_verbose_output_includes_measurements(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--verbose", "--area-model", "screen_fraction", self.gif_path])
        self.assertEqual(code, 1)
        text = output.getvalue()
        self.assertGreater(len(text.strip().splitlines()), 1)
        self.assertIn("rate:", text)
        self.assertIn("media:", text)
        self.assertIn("warnings:", text)

    def test_brief_output_omits_reasons(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--brief", "--area-model", "screen_fraction", self.gif_path])
        self.assertEqual(code, 1)
        lines = output.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("TRIGGERING", lines[0])
        self.assertIn(self.gif_path, lines[0])
        self.assertNotIn("luminance_transition_rate_exceeded", lines[0])
        self.assertNotIn("rate:", lines[0])

    def test_list_standards(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--list-standards"])
        self.assertEqual(code, 0)
        self.assertIn("wcag22", output.getvalue())

    def test_quick_output_is_minimal_with_brief(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--quick", "--brief", "--area-model", "screen_fraction", self.gif_path])
        self.assertEqual(code, 1)
        lines = output.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("TRIGGERING", lines[0])
        self.assertNotIn("luminance_transition_rate_exceeded", lines[0])

    def test_quick_alone_uses_default_output_with_reasons(self) -> None:
        # --quick only controls early stopping; output is governed by --brief/--json/--verbose/default.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--quick", "--area-model", "screen_fraction", self.gif_path])
        self.assertEqual(code, 1)
        line = output.getvalue().strip().splitlines()[-1]
        self.assertIn("TRIGGERING", line)
        self.assertIn("luminance_transition_rate_exceeded", line)

    def test_quick_on_safe_image_exits_zero(self) -> None:
        path = os.path.join(self.temporary.name, "still.png")
        Image.fromarray(alternating_frames(1)[0], mode="RGB").save(path)
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--quick", path])
        self.assertEqual(code, 0)

    def test_quick_json_carries_quick_flag_and_analyzed_span(self) -> None:
        # --quick --json carries the quick verdict and the analyzed span.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--quick", "--json", "--area-model", "screen_fraction", self.gif_path])
        self.assertEqual(code, 1)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["quick"])
        self.assertIn("analysis_early_stopped", payload["warnings"])
        self.assertGreater(payload["measurements"]["analyzed_span_seconds"], 0.0)
        self.assertIn("luminance_transition_rate_exceeded", payload["reasons"])

    def test_brief_json_outputs_both_formats(self) -> None:
        # --brief controls printing; --json controls JSON; they compose.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--brief", "--json", "--area-model", "screen_fraction", self.gif_path])
        text = output.getvalue()
        self.assertEqual(code, 1)
        lines = text.strip().splitlines()
        # A minimal human line plus a single JSON payload.
        self.assertEqual(len(lines), 2)
        self.assertIn("TRIGGERING", lines[0])
        self.assertNotIn("luminance_transition_rate_exceeded", lines[0])
        payload = json.loads(lines[1])
        self.assertEqual(payload["schema_version"], 2)

    def test_missing_file_exits_with_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            code = main([os.path.join(self.temporary.name, "missing.mp4")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
