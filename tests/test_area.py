"""Unit tests for tiling and area normalization."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from epilepsy_warning.area import TileGrid, _box_downsample, tile_frame, tile_frame_uint8


class TileFrameTests(unittest.TestCase):
    def test_same_size_grid_skips_resize(self) -> None:
        frame = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
        grid = TileGrid(width=5, height=4, cols=5, rows=4)

        tiled = tile_frame(frame, grid)

        np.testing.assert_array_equal(tiled, frame.astype(np.float32) / 255.0)

    def test_uint8_tiling_matches_float_tiling(self) -> None:
        rng = np.random.default_rng(2)
        frame = rng.integers(0, 256, (37, 41, 3), dtype=np.uint8)
        grid = TileGrid(width=41, height=37, cols=13, rows=11)

        np.testing.assert_array_equal(
            tile_frame_uint8(frame, grid).astype(np.float32) / 255.0,
            tile_frame(frame, grid),
        )

    def test_box_downsample_matches_pillow(self) -> None:
        rng = np.random.default_rng(0)
        frame = rng.integers(0, 256, (37, 41, 3), dtype=np.uint8)
        grid = TileGrid(width=41, height=37, cols=13, rows=11)

        tiled = tile_frame(frame, grid)
        expected = np.asarray(
            Image.fromarray(frame, mode="RGB").resize((grid.cols, grid.rows), Image.Resampling.BOX),
            dtype=np.float32,
        )
        expected /= 255.0

        np.testing.assert_array_equal(tiled, expected)

    def test_numpy_box_fallback_matches_pillow(self) -> None:
        # Exercise the numpy implementation directly: it is the fallback for
        # platforms without Pillow's resampler and must keep the same output.
        rng = np.random.default_rng(3)
        sizes = [
            (37, 41, 11, 13),
            (100, 3, 5, 2),
            (2, 100, 50, 7),
            (3, 4, 9, 10),
            (15, 15, 14, 14),
            (13, 13, 6, 6),
        ]
        for height, width, rows, cols in sizes:
            frame = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
            expected = np.asarray(
                Image.fromarray(frame, mode="RGB").resize((cols, rows), Image.Resampling.BOX)
            )
            np.testing.assert_array_equal(
                _box_downsample(frame, rows, cols), expected, err_msg=str(sizes)
            )

    def test_rgba_is_composited_over_black_before_tiling(self) -> None:
        frame = np.zeros((2, 2, 4), dtype=np.uint8)
        frame[..., 0] = 255
        frame[..., 3] = 128
        grid = TileGrid(width=2, height=2, cols=2, rows=2)

        tiled = tile_frame(frame, grid)

        # 255 * 128 / 255 is about 128, then normalized by 255.
        self.assertAlmostEqual(float(tiled[0, 0, 0]), 128.0 / 255.0, places=5)
        self.assertEqual(float(tiled[0, 0, 1]), 0.0)


if __name__ == "__main__":
    unittest.main()
