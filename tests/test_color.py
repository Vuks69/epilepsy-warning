"""Unit tests for the color helpers."""

from __future__ import annotations

import unittest

import numpy as np

from epilepsy_warning.color import (
    convert_to_srgb_linear,
    decode_to_srgb_linear,
    hlg_to_linear,
    is_saturated_red,
    linear_rgb_features,
    linear_rgb_to_luminance,
    linear_rgb_to_ucs,
    linear_to_srgb,
    pq_to_linear,
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

    def test_pq_eotf_anchors(self) -> None:
        # ST 2084: normalized code 0.508 -> ~100 cd/m^2 (relative 100/10000),
        # the peak code 1.0 -> reference white (relative 1.0).
        self.assertAlmostEqual(float(pq_to_linear(np.float32(0.508))), 100.0 / 10000.0, places=4)
        self.assertAlmostEqual(float(pq_to_linear(np.float32(1.0))), 1.0, places=5)
        self.assertAlmostEqual(float(pq_to_linear(np.float32(0.0))), 0.0, places=9)
        # Monotonic in the code value.
        codes = np.array([0.1, 0.3, 0.5, 0.7, 0.9], dtype=np.float32)
        decoded = pq_to_linear(codes)
        self.assertTrue(np.all(np.diff(decoded) > 0))

    def test_pq_clamps_negative_codes(self) -> None:
        codes = np.array([-1.0, 0.0, 0.5], dtype=np.float32)
        decoded = pq_to_linear(codes)
        self.assertGreaterEqual(float(decoded[0]), 0.0)

    def test_hlg_inverse_oetf_anchors(self) -> None:
        # HLG: code 0.5 is reference white (relative 1.0), the ceiling code 1.0
        # is ~12x reference, and the perceptual midpoint 0.21213 is 0.18 cd/m^2.
        self.assertAlmostEqual(float(hlg_to_linear(np.float32(0.5))), 1.0, places=5)
        self.assertAlmostEqual(float(hlg_to_linear(np.float32(0.0))), 0.0, places=9)
        self.assertAlmostEqual(float(hlg_to_linear(np.float32(0.21213))), 0.18, places=2)
        ceiling = float(hlg_to_linear(np.float32(1.0)))
        self.assertGreater(ceiling, 10.0)
        self.assertLess(ceiling, 13.0)

    def test_hlg_matches_pq_at_reference_white(self) -> None:
        # Both HDR transfers read relative 1.0 at reference white, so a
        # neutralized HDR frame matches sRGB reference white on the cd/m^2 path.
        self.assertAlmostEqual(
            float(hlg_to_linear(np.float32(0.5))),
            float(pq_to_linear(np.float32(1.0))),
            places=6,
        )

    def test_srgb_and_rec709_decode_identically(self) -> None:
        # Rec.709 shares sRGB's primaries, so decoding is identical for both.
        tiles = np.random.default_rng(2).random((5, 7, 3), dtype=np.float32)
        srgb = decode_to_srgb_linear(tiles, "srgb", "srgb")
        rec709 = decode_to_srgb_linear(tiles, "bt709", "srgb")
        np.testing.assert_array_equal(srgb, rec709)

    def test_decode_hdr_transfer_uses_pq(self) -> None:
        tiles = np.random.default_rng(3).random((5, 7, 3), dtype=np.float32)
        pq = decode_to_srgb_linear(tiles, "bt2020", "pq")
        self.assertGreater(float(pq.max()), 0.0)
        # PQ decodes darker than sRGB at the same code, so the PQ luminance is
        # lower than an sRGB decode of the same codes (for the same gamut).
        srgb = decode_to_srgb_linear(tiles, "bt2020", "srgb")
        self.assertLess(float(pq.mean()), float(srgb.mean()))

    def test_gamut_matrices_preserve_white(self) -> None:
        # Both matrices map the reference white to white: every row sums to one,
        # so a decoded neutral keeps relative luminance 1.0 (the cd/m^2 ceiling).
        for color_space in ("p3_d65", "bt2020"):
            white = np.array([[[1.0, 1.0, 1.0]]], dtype=np.float32)
            converted = convert_to_srgb_linear(white, color_space)
            np.testing.assert_allclose(converted, white, atol=1e-5)

    def test_gamut_neutral_preserves_luminance(self) -> None:
        # A neutral of relative luminance L (equal channels in the source gamut)
        # must decode to sRGB luminance ~L. That is the value the cd/m^2 and WCAG
        # luminance paths read, and it is preserved by both matrices.
        rng = np.random.default_rng(7)
        levels = rng.random((500,), dtype=np.float32)
        neutral = np.repeat(levels[:, None], 3, axis=1).reshape(500, 1, 3).astype(np.float32)
        weights = np.array([0.2126729, 0.7151522, 0.0721750], dtype=np.float32)
        for color_space in ("p3_d65", "bt2020"):
            converted = convert_to_srgb_linear(neutral, color_space)
            decoded_luminance = np.sum(converted * weights, axis=2).ravel()
            np.testing.assert_allclose(decoded_luminance, levels, atol=1e-3, rtol=0)

    def test_convert_identity_gamut_is_noop(self) -> None:
        linear = np.random.default_rng(9).random((4, 4, 3), dtype=np.float32)
        np.testing.assert_array_equal(convert_to_srgb_linear(linear, "srgb"), linear)

    def test_convert_clamps_out_of_gamut_low_end(self) -> None:
        # Wide-gamut colors with an sRGB-negative channel clamp to zero; nothing
        # goes below black.
        negative = np.array([[[1.4, -0.2, 0.3]]], dtype=np.float32)
        converted = convert_to_srgb_linear(negative, "bt2020")
        self.assertGreaterEqual(float(np.min(converted)), 0.0)

    def test_decode_preserves_luminance_of_srgb(self) -> None:
        # With no gamut conversion (bt709) the decoded path must equal the engine's
        # sRGB path: decode -> relative luminance equals sRGB -> relative luminance.
        rng = np.random.default_rng(11)
        tiles = rng.random((6, 6, 3), dtype=np.float32)
        from epilepsy_warning.color import linear_rgb_to_luminance

        decoded = decode_to_srgb_linear(tiles, "bt709", "srgb")
        direct = srgb_to_linear(tiles)
        np.testing.assert_array_equal(decoded, direct)
        np.testing.assert_array_equal(
            linear_rgb_to_luminance(decoded), linear_rgb_to_luminance(direct)
        )


if __name__ == "__main__":
    unittest.main()
