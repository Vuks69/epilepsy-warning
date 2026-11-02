"""Unit tests for the color helpers."""

from __future__ import annotations

import unittest

import numpy as np

from epilepsy_warning.color import (
    is_saturated_red,
    linear_rgb_features,
    linear_rgb_to_luminance,
    linear_rgb_to_ucs,
    linear_to_srgb,
    red_ratio,
    srgb_to_linear,
    ucs_distance,
)


class ColorTests(unittest.TestCase):
    def test_srgb_round_trip(self) -> None:
        rgb = np.array([0.0, 0.05, 0.5, 1.0], dtype=np.float32)
        np.testing.assert_allclose(linear_to_srgb(srgb_to_linear(rgb)), rgb, atol=1e-6)

    def test_relative_luminance(self) -> None:
        white = np.ones((1, 1, 3), dtype=np.float32)
        black = np.zeros((1, 1, 3), dtype=np.float32)
        self.assertAlmostEqual(
            float(linear_rgb_to_luminance(srgb_to_linear(white))[0, 0]), 1.0, places=5
        )
        self.assertAlmostEqual(
            float(linear_rgb_to_luminance(srgb_to_linear(black))[0, 0]), 0.0, places=5
        )

    def test_red_ratio_and_saturation(self) -> None:
        red = np.array([[[1.0, 0.0, 0.0]]], dtype=np.float32)
        white = np.array([[[1.0, 1.0, 1.0]]], dtype=np.float32)
        self.assertAlmostEqual(float(red_ratio(red)[0, 0]), 1.0)
        self.assertAlmostEqual(float(red_ratio(white)[0, 0]), 1.0 / 3.0)
        self.assertTrue(bool(is_saturated_red(red)[0, 0]))
        self.assertFalse(bool(is_saturated_red(white)[0, 0]))

    def test_red_ratio_uses_linear_light(self) -> None:
        # Mid-gray sRGB is 0.5 in each channel, so its linear red ratio is 1/3.
        gray = np.full((1, 1, 3), 0.5, dtype=np.float32)
        self.assertAlmostEqual(float(red_ratio(srgb_to_linear(gray))[0, 0]), 1.0 / 3.0, places=6)

    def test_ucs_distance(self) -> None:
        red = np.array([[[1.0, 0.0, 0.0]]], dtype=np.float32)
        gray = np.array([[[0.2126, 0.2126, 0.2126]]], dtype=np.float32)
        red_u, red_v = linear_rgb_to_ucs(red)
        gray_u, gray_v = linear_rgb_to_ucs(gray)
        distance = float(ucs_distance(red_u, red_v, gray_u, gray_v)[0, 0])
        self.assertGreater(distance, 0.2)

    def test_black_has_no_chromaticity(self) -> None:
        black = np.zeros((1, 1, 3), dtype=np.float32)
        u, v = linear_rgb_to_ucs(black)
        self.assertEqual(float(u[0, 0]), 0.0)
        self.assertEqual(float(v[0, 0]), 0.0)

    def test_fused_features_match_individual_helpers(self) -> None:
        rng = np.random.default_rng(4)
        linear = rng.random((7, 9, 3), dtype=np.float32)

        luminance, redness, red, u, v = linear_rgb_features(linear, 0.8)
        u_expected, v_expected = linear_rgb_to_ucs(linear)

        np.testing.assert_array_equal(luminance, linear_rgb_to_luminance(linear))
        np.testing.assert_array_equal(redness, red_ratio(linear))
        np.testing.assert_array_equal(red, is_saturated_red(linear, 0.8))
        np.testing.assert_array_equal(u, u_expected)
        np.testing.assert_array_equal(v, v_expected)

    def test_uint8_lut_matches_float_conversion(self) -> None:
        values = np.arange(256, dtype=np.uint8)
        np.testing.assert_array_equal(
            srgb_to_linear(values),
            srgb_to_linear(values.astype(np.float32) / np.float32(255.0)),
        )


if __name__ == "__main__":
    unittest.main()
