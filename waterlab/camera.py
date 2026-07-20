"""USB camera capture integrated with the WaterLAB evidence logger."""

import argparse
from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

from .data_logger import DataLogger
from .schemas import MeasurementRecord


@dataclass(frozen=True)
class CameraConfig:
    """Configuration requested from a USB/UVC camera."""

    device_index: int = 0
    width: int = 1920
    height: int = 1080
    warmup_frames: int = 10
    codec: str = "MJPG"
    image_extension: str = ".jpg"

    def validate(self) -> None:
        if self.device_index < 0:
            raise ValueError("device_index must be zero or greater")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.warmup_frames < 0:
            raise ValueError("warmup_frames must be zero or greater")
        if self.codec and len(self.codec) != 4:
            raise ValueError("codec must contain exactly four characters")
        if self.image_extension.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("image_extension must be .jpg, .jpeg, or .png")


@dataclass(frozen=True)
class CameraCapture:
    """Metadata associated with one successfully written camera frame."""

    path: Path
    width: int
    height: int
    exposure: Optional[float]
    gain: Optional[float]
    white_balance_mode: str
    quality_flags: Tuple[str, ...]


def _load_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except ImportError as error:
        raise RuntimeError(
            "OpenCV is required for camera capture. Verify it with: "
            "python3 -c \"import cv2; print(cv2.__version__)\""
        ) from error
    return cv2


def _finite_camera_value(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _camera_property(capture: Any, cv2_module: Any, name: str) -> Optional[float]:
    property_id = getattr(cv2_module, name, None)
    if property_id is None:
        return None
    return _finite_camera_value(capture.get(property_id))


def _white_balance_mode(capture: Any, cv2_module: Any) -> str:
    value = _camera_property(capture, cv2_module, "CAP_PROP_AUTO_WB")
    if value is None or value < 0:
        return "unknown"
    return "auto" if value >= 0.5 else "manual"


def capture_usb_image(
    destination: Path,
    config: CameraConfig = CameraConfig(),
    cv2_module: Optional[Any] = None,
) -> CameraCapture:
    """Capture one UVC frame and atomically write it to ``destination``."""

    config.validate()
    cv2_module = cv2_module or _load_cv2()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    capture = cv2_module.VideoCapture(config.device_index)
    try:
        if not capture.isOpened():
            raise RuntimeError(
                "Could not open USB camera device {}".format(config.device_index)
            )

        if config.codec:
            capture.set(
                cv2_module.CAP_PROP_FOURCC,
                cv2_module.VideoWriter_fourcc(*config.codec),
            )
        capture.set(cv2_module.CAP_PROP_FRAME_WIDTH, config.width)
        capture.set(cv2_module.CAP_PROP_FRAME_HEIGHT, config.height)

        frame = None
        for _ in range(config.warmup_frames + 1):
            success, candidate = capture.read()
            if not success or candidate is None:
                raise RuntimeError("USB camera returned an invalid frame")
            frame = candidate

        if frame is None or getattr(frame, "size", 0) == 0:
            raise RuntimeError("USB camera returned an empty frame")

        actual_height, actual_width = int(frame.shape[0]), int(frame.shape[1])
        quality_flags = []
        if actual_width != config.width or actual_height != config.height:
            quality_flags.append("camera_resolution_mismatch")

        suffix = destination.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("destination must end in .jpg, .jpeg, or .png")
        temporary = destination.with_name(
            "{}.tmp{}".format(destination.stem, destination.suffix)
        )
        if not cv2_module.imwrite(str(temporary), frame):
            raise RuntimeError("OpenCV could not write captured image")
        os.replace(str(temporary), str(destination))

        return CameraCapture(
            path=destination,
            width=actual_width,
            height=actual_height,
            exposure=_camera_property(capture, cv2_module, "CAP_PROP_EXPOSURE"),
            gain=_camera_property(capture, cv2_module, "CAP_PROP_GAIN"),
            white_balance_mode=_white_balance_mode(capture, cv2_module),
            quality_flags=tuple(quality_flags),
        )
    finally:
        capture.release()


def capture_and_log(
    data_root: Path,
    sample_id: str,
    sample_type: str,
    run_type: str,
    config: CameraConfig = CameraConfig(),
    excitation_nm: Optional[int] = None,
    filter_id: str = "",
    camera_id: str = "usb-camera-01",
    notes: str = "",
    cv2_module: Optional[Any] = None,
) -> MeasurementRecord:
    """Capture a frame and persist image plus metadata under one ID."""

    record = MeasurementRecord.create(
        sample_id=sample_id,
        sample_type=sample_type,
        run_type=run_type,
        camera_id=camera_id,
        excitation_nm=excitation_nm,
        filter_id=filter_id,
        operator_notes=notes,
    )
    data_root = Path(data_root)
    staging_dir = data_root / ".staging"
    staged_path = staging_dir / "{}{}".format(
        record.measurement_id, config.image_extension
    )

    captured = capture_usb_image(staged_path, config, cv2_module=cv2_module)
    record = replace(
        record,
        exposure=captured.exposure,
        gain=captured.gain,
        white_balance_mode=captured.white_balance_mode,
        image_width_px=captured.width,
        image_height_px=captured.height,
        quality_flags=captured.quality_flags,
    )

    stored = DataLogger(data_root).log(record, source_image=captured.path)
    captured.path.unlink()
    try:
        staging_dir.rmdir()
    except OSError:
        pass
    return stored


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one USB camera frame and log its evidence bundle."
    )
    parser.add_argument("--root", default="data", help="Data directory")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--sample-type", required=True)
    parser.add_argument(
        "--run-type",
        required=True,
        choices=("blank", "reference", "sample", "calibration", "replay"),
    )
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--warmup-frames", type=int, default=10)
    parser.add_argument("--codec", default="MJPG")
    parser.add_argument("--format", choices=("jpg", "png"), default="jpg")
    parser.add_argument("--camera-id", default="usb-camera-01")
    parser.add_argument("--excitation-nm", type=int)
    parser.add_argument("--filter-id", default="")
    parser.add_argument("--notes", default="")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    config = CameraConfig(
        device_index=args.device,
        width=args.width,
        height=args.height,
        warmup_frames=args.warmup_frames,
        codec=args.codec,
        image_extension=".{}".format(args.format),
    )
    stored = capture_and_log(
        data_root=Path(args.root),
        sample_id=args.sample_id,
        sample_type=args.sample_type,
        run_type=args.run_type,
        config=config,
        excitation_nm=args.excitation_nm,
        filter_id=args.filter_id,
        camera_id=args.camera_id,
        notes=args.notes,
    )
    print(
        json.dumps(
            {
                "measurement_id": stored.measurement_id,
                "image_path": stored.image_path,
                "quality_flags": list(stored.quality_flags),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
