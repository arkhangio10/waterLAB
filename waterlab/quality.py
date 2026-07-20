"""Deterministic image-quality checks for WaterLAB acquisitions."""

from dataclasses import dataclass
from typing import Any, Tuple

import numpy as np


@dataclass(frozen=True)
class QualityThresholds:
    """Conservative defaults that can later be calibrated for the chamber."""

    minimum_mean_brightness: float = 15.0
    maximum_mean_brightness: float = 240.0
    saturation_pixel_value: int = 250
    maximum_saturation_fraction: float = 0.02
    minimum_sharpness_score: float = 20.0

    def validate(self) -> None:
        if not 0 <= self.minimum_mean_brightness < self.maximum_mean_brightness <= 255:
            raise ValueError("brightness thresholds must satisfy 0 <= min < max <= 255")
        if not 0 <= self.saturation_pixel_value <= 255:
            raise ValueError("saturation_pixel_value must be between 0 and 255")
        if not 0 <= self.maximum_saturation_fraction <= 1:
            raise ValueError("maximum_saturation_fraction must be between 0 and 1")
        if self.minimum_sharpness_score < 0:
            raise ValueError("minimum_sharpness_score must be zero or greater")


@dataclass(frozen=True)
class ImageQualityMetrics:
    """Transparent metrics and flags computed from one BGR image."""

    mean_brightness: float
    saturation_fraction: float
    sharpness_score: float
    flags: Tuple[str, ...]


def analyze_bgr_frame(
    frame: Any,
    thresholds: QualityThresholds = QualityThresholds(),
) -> ImageQualityMetrics:
    """Analyze an OpenCV-style BGR frame without changing the image.

    Sharpness is the variance of a four-neighbour Laplacian. Saturation is the
    fraction of pixels where any BGR channel reaches the clipping threshold.
    These values are screening quality controls, not water-quality features.
    """

    thresholds.validate()
    image = np.asarray(frame)
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("frame must be a height x width x BGR image")
    if image.shape[0] < 3 or image.shape[1] < 3 or image.size == 0:
        raise ValueError("frame must be at least 3 x 3 pixels")

    bgr = image[:, :, :3].astype(np.float32, copy=False)
    gray = 0.114 * bgr[:, :, 0] + 0.587 * bgr[:, :, 1] + 0.299 * bgr[:, :, 2]
    mean_brightness = float(np.mean(gray))
    saturation_fraction = float(
        np.mean(np.max(bgr, axis=2) >= thresholds.saturation_pixel_value)
    )

    laplacian = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    sharpness_score = float(np.var(laplacian))

    flags = []
    if mean_brightness < thresholds.minimum_mean_brightness:
        flags.append("image_too_dark")
    if mean_brightness > thresholds.maximum_mean_brightness:
        flags.append("image_too_bright")
    if saturation_fraction > thresholds.maximum_saturation_fraction:
        flags.append("image_saturated")
    if sharpness_score < thresholds.minimum_sharpness_score:
        flags.append("image_blurry")

    return ImageQualityMetrics(
        mean_brightness=mean_brightness,
        saturation_fraction=saturation_fraction,
        sharpness_score=sharpness_score,
        flags=tuple(flags),
    )
