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
from epilepsy_warning.cli import main
from epilepsy_warning.decode import _alpha_composite_rgba, decode_file


def options(**overrides):
    base = {"area_model": "screen_fraction", "tile_grid_max": 64}
    base.update(overrides)
    return AnalysisOptions(**base)


def alternating_frames(count=8, size=48):
    return [
        np.full((size, size, 3), 0 if index % 2 == 0 else 255, dtype=np.uint8)
        for index in range(count)
    ]


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

    def test_list_standards(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--list-standards"])
        self.assertEqual(code, 0)
        self.assertIn("wcag22", output.getvalue())

    def test_missing_file_exits_with_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            code = main([os.path.join(self.temporary.name, "missing.mp4")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
