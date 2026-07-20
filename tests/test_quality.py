import unittest

import numpy as np

from waterlab.quality import QualityThresholds, analyze_bgr_frame


class ImageQualityTests(unittest.TestCase):
    def test_midrange_checkerboard_passes_default_gate(self):
        checkerboard = (np.indices((20, 20)).sum(axis=0) % 2) * 120 + 60
        image = np.repeat(checkerboard[:, :, np.newaxis], 3, axis=2).astype(np.uint8)

        result = analyze_bgr_frame(image)

        self.assertAlmostEqual(result.mean_brightness, 120.0)
        self.assertEqual(result.saturation_fraction, 0.0)
        self.assertGreater(result.sharpness_score, 20.0)
        self.assertEqual(result.flags, ())

    def test_black_image_is_dark_and_blurry(self):
        result = analyze_bgr_frame(np.zeros((20, 20, 3), dtype=np.uint8))

        self.assertIn("image_too_dark", result.flags)
        self.assertIn("image_blurry", result.flags)
        self.assertNotIn("image_saturated", result.flags)

    def test_white_image_is_bright_saturated_and_blurry(self):
        result = analyze_bgr_frame(np.full((20, 20, 3), 255, dtype=np.uint8))

        self.assertIn("image_too_bright", result.flags)
        self.assertIn("image_saturated", result.flags)
        self.assertIn("image_blurry", result.flags)

    def test_invalid_thresholds_are_rejected(self):
        with self.assertRaises(ValueError):
            QualityThresholds(
                minimum_mean_brightness=250,
                maximum_mean_brightness=200,
            ).validate()


if __name__ == "__main__":
    unittest.main()
