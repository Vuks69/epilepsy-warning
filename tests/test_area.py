"""Unit tests for tiling and area normalization."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from epilepsy_warning.area import TileGrid, tile_frame


class TileFrameTests(unittest.TestCase):
    def test_same_size_grid_skips_resize(self) -> None:
        frame = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
        grid = TileGrid(width=5, height=4, cols=5, rows=4)

        tiled = tile_frame(frame, grid)

        np.testing.assert_array_equal(tiled, frame.astype(np.float32) / 255.0)

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
