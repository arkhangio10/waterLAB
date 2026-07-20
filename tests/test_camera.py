import csv
from pathlib import Path
import tempfile
import unittest

from waterlab.camera import CameraConfig, capture_and_log, capture_usb_image


class FakeFrame:
    shape = (1080, 1920, 3)
    size = 1080 * 1920 * 3


class FakeCapture:
    def __init__(self, opened=True, read_success=True):
        self.opened = opened
        self.read_success = read_success
        self.released = False
        self.set_calls = []
        self.read_count = 0

    def isOpened(self):
        return self.opened

    def set(self, property_id, value):
        self.set_calls.append((property_id, value))
        return True

    def read(self):
        self.read_count += 1
        return self.read_success, FakeFrame() if self.read_success else None

    def get(self, property_id):
        return {5: -6.0, 6: 2.0, 7: 1.0}.get(property_id, -1.0)

    def release(self):
        self.released = True


class FakeCv2:
    CAP_PROP_FOURCC = 1
    CAP_PROP_FRAME_WIDTH = 2
    CAP_PROP_FRAME_HEIGHT = 3
    CAP_PROP_EXPOSURE = 5
    CAP_PROP_GAIN = 6
    CAP_PROP_AUTO_WB = 7

    def __init__(self, capture=None):
        self.capture = capture or FakeCapture()

    def VideoCapture(self, device_index):
        self.device_index = device_index
        return self.capture

    @staticmethod
    def VideoWriter_fourcc(*codec):
        return 1234

    @staticmethod
    def imwrite(path, frame):
        Path(path).write_bytes(b"fake-jpeg")
        return True


class CameraCaptureTests(unittest.TestCase):
    def test_capture_sets_resolution_warms_up_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "capture.jpg"
            fake_cv2 = FakeCv2()
            result = capture_usb_image(
                destination,
                CameraConfig(warmup_frames=2),
                cv2_module=fake_cv2,
            )

            self.assertEqual(destination.read_bytes(), b"fake-jpeg")
            self.assertEqual(fake_cv2.capture.read_count, 3)
            self.assertTrue(fake_cv2.capture.released)
            self.assertEqual(result.width, 1920)
            self.assertEqual(result.height, 1080)
            self.assertEqual(result.exposure, -6.0)
            self.assertEqual(result.gain, 2.0)
            self.assertEqual(result.white_balance_mode, "auto")
            self.assertEqual(result.quality_flags, ())

    def test_unavailable_camera_raises_and_releases_device(self):
        capture = FakeCapture(opened=False)
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(RuntimeError, "Could not open"):
                capture_usb_image(
                    Path(temporary_directory) / "capture.jpg",
                    cv2_module=FakeCv2(capture),
                )
        self.assertTrue(capture.released)

    def test_capture_and_log_uses_one_measurement_id(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            stored = capture_and_log(
                data_root=root,
                sample_id="uv-blank-01",
                sample_type="water",
                run_type="blank",
                excitation_nm=365,
                filter_id="yellow-cellophane-v1",
                config=CameraConfig(warmup_frames=0),
                cv2_module=FakeCv2(),
            )

            image_path = root / stored.image_path
            json_path = root / "records" / (stored.measurement_id + ".json")
            self.assertTrue(image_path.is_file())
            self.assertTrue(json_path.is_file())
            self.assertFalse((root / ".staging").exists())

            with (root / "measurements.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["measurement_id"], stored.measurement_id)
            self.assertEqual(row["image_path"], stored.image_path)
            self.assertEqual(row["excitation_nm"], "365")
            self.assertEqual(row["exposure"], "-6.0")
            self.assertEqual(row["image_width_px"], "1920")
            self.assertEqual(row["image_height_px"], "1080")


if __name__ == "__main__":
    unittest.main()
