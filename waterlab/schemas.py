"""Shared data contracts for WaterLAB measurements.

This module intentionally uses only the Python 3.8 standard library so the
same record format can run on the Alienware development machine and Jetson
Nano without separate schema dependencies.
"""

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_VALID_RUN_TYPES = {"blank", "reference", "sample", "calibration", "replay"}
DATA_SCHEMA_VERSION = "1.0.0"


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp in a stable ISO 8601 format."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def new_measurement_id(
    sample_id: str, timestamp: Optional[datetime] = None
) -> str:
    """Create a filesystem-safe, human-readable measurement identifier."""

    normalized = _SAFE_ID_RE.sub("-", sample_id.strip()).strip("-._")
    if not normalized:
        normalized = "sample"

    instant = timestamp or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    stamp = instant.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return "{}-{}-{}".format(normalized, stamp, uuid4().hex[:8])


@dataclass(frozen=True)
class MeasurementRecord:
    """One synchronized WaterLAB acquisition.

    Empty optional fields mean that the corresponding processing stage has
    not run yet. Raw evidence should be logged before derived features are
    added by later pipeline stages.
    """

    measurement_id: str
    timestamp_utc: str
    sample_id: str
    sample_type: str
    run_type: str
    schema_version: str = DATA_SCHEMA_VERSION
    device_id: str = "jetson-nano-01"
    camera_id: str = "usb-camera-01"
    excitation_nm: Optional[int] = None
    filter_id: str = ""
    exposure: Optional[float] = None
    gain: Optional[float] = None
    white_balance_mode: str = ""
    image_path: str = ""
    image_width_px: Optional[int] = None
    image_height_px: Optional[int] = None
    image_mean_brightness: Optional[float] = None
    image_saturation_fraction: Optional[float] = None
    image_sharpness_score: Optional[float] = None
    roi_x: Optional[int] = None
    roi_y: Optional[int] = None
    roi_width: Optional[int] = None
    roi_height: Optional[int] = None
    rgb_median_r: Optional[float] = None
    rgb_median_g: Optional[float] = None
    rgb_median_b: Optional[float] = None
    hsv_h: Optional[float] = None
    hsv_s: Optional[float] = None
    hsv_v: Optional[float] = None
    lab_l: Optional[float] = None
    lab_a: Optional[float] = None
    lab_b: Optional[float] = None
    fluorescence_index: Optional[float] = None
    turbidity_dark_raw: Optional[float] = None
    turbidity_reference_raw: Optional[float] = None
    turbidity_sample_raw: Optional[float] = None
    attenuation_ratio: Optional[float] = None
    quality_flags: Tuple[str, ...] = field(default_factory=tuple)
    local_model_name: str = ""
    local_model_version: str = ""
    local_class: str = ""
    local_confidence: Optional[float] = None
    gpt_report_status: str = "not_requested"
    operator_notes: str = ""

    @classmethod
    def create(
        cls,
        sample_id: str,
        sample_type: str,
        run_type: str,
        **kwargs: Any
    ) -> "MeasurementRecord":
        """Create a record with a new ID and current UTC timestamp."""

        timestamp_utc = kwargs.pop("timestamp_utc", utc_now_iso())
        measurement_id = kwargs.pop(
            "measurement_id", new_measurement_id(sample_id)
        )
        return cls(
            measurement_id=measurement_id,
            timestamp_utc=timestamp_utc,
            sample_id=sample_id,
            sample_type=sample_type,
            run_type=run_type,
            **kwargs
        )

    @classmethod
    def csv_fieldnames(cls) -> Tuple[str, ...]:
        """Return the canonical, version-stable CSV column order."""

        return tuple(item.name for item in fields(cls))

    def validate(self) -> None:
        """Reject incomplete or unsafe records before writing them."""

        required = {
            "measurement_id": self.measurement_id,
            "timestamp_utc": self.timestamp_utc,
            "sample_id": self.sample_id,
            "sample_type": self.sample_type,
            "run_type": self.run_type,
            "schema_version": self.schema_version,
            "device_id": self.device_id,
            "camera_id": self.camera_id,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError("Missing required fields: {}".format(", ".join(missing)))

        if _SAFE_ID_RE.search(self.measurement_id):
            raise ValueError("measurement_id contains unsafe characters")

        if self.run_type not in _VALID_RUN_TYPES:
            raise ValueError(
                "run_type must be one of: {}".format(
                    ", ".join(sorted(_VALID_RUN_TYPES))
                )
            )

        parsed_timestamp = datetime.fromisoformat(
            self.timestamp_utc.replace("Z", "+00:00")
        )
        if parsed_timestamp.tzinfo is None:
            raise ValueError("timestamp_utc must include a timezone")

        if self.excitation_nm is not None and self.excitation_nm <= 0:
            raise ValueError("excitation_nm must be positive")

        for name, value in (
            ("image_width_px", self.image_width_px),
            ("image_height_px", self.image_height_px),
        ):
            if value is not None and value <= 0:
                raise ValueError("{} must be positive".format(name))

        if (
            self.image_saturation_fraction is not None
            and not 0.0 <= self.image_saturation_fraction <= 1.0
        ):
            raise ValueError("image_saturation_fraction must be between 0 and 1")

        for name, value in (
            ("image_mean_brightness", self.image_mean_brightness),
            ("image_sharpness_score", self.image_sharpness_score),
        ):
            if value is not None and value < 0:
                raise ValueError("{} must be zero or greater".format(name))

        if self.local_confidence is not None and not 0.0 <= self.local_confidence <= 1.0:
            raise ValueError("local_confidence must be between 0 and 1")

    def to_json_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe representation."""

        payload = asdict(self)
        payload["quality_flags"] = list(self.quality_flags)
        return payload

    def to_csv_row(self) -> Dict[str, Any]:
        """Return a flat CSV representation."""

        payload = asdict(self)
        payload["quality_flags"] = json.dumps(
            list(self.quality_flags), ensure_ascii=False, separators=(",", ":")
        )
        return payload
