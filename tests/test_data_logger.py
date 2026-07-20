import csv
import json
from pathlib import Path
import tempfile
import unittest

from waterlab.data_logger import DataLogger
from waterlab.schemas import MeasurementRecord, new_measurement_id


class MeasurementSchemaTests(unittest.TestCase):
    def test_measurement_id_is_safe_and_prefixed(self) -> None:
        measurement_id = new_measurement_id("Blank water / 01")
        self.assertTrue(measurement_id.startswith("Blank-water-01-"))
        self.assertNotIn(" ", measurement_id)
        self.assertNotIn("/", measurement_id)

    def test_invalid_confidence_is_rejected(self) -> None:
        record = MeasurementRecord.create(
            sample_id="sample-01",
            sample_type="safe-proxy",
            run_type="sample",
            local_confidence=1.5,
        )
        with self.assertRaises(ValueError):
            record.validate()


class DataLoggerTests(unittest.TestCase):
    def test_log_writes_csv_json_and_original_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_image = root / "capture.png"
            source_image.write_bytes(b"test-image-bytes")

            record = MeasurementRecord.create(
                sample_id="tonic-25",
                sample_type="fluorescent-proxy",
                run_type="sample",
                excitation_nm=365,
                quality_flags=("demo_only",),
            )
            stored = DataLogger(root / "dataset").log(record, source_image)

            csv_path = root / "dataset" / "measurements.csv"
            json_path = root / "dataset" / "records" / (
                record.measurement_id + ".json"
            )
            stored_image = root / "dataset" / stored.image_path

            self.assertTrue(csv_path.is_file())
            self.assertTrue(json_path.is_file())
            self.assertEqual(stored_image.read_bytes(), b"test-image-bytes")

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["measurement_id"], record.measurement_id)
            self.assertEqual(rows[0]["excitation_nm"], "365")
            self.assertEqual(rows[0]["quality_flags"], '["demo_only"]')

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["measurement_id"], record.measurement_id)
            self.assertEqual(payload["image_path"], stored.image_path)
            self.assertEqual(payload["quality_flags"], ["demo_only"])

    def test_header_is_written_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logger = DataLogger(Path(temporary_directory))
            logger.log(
                MeasurementRecord.create(
                    sample_id="blank-01",
                    sample_type="water",
                    run_type="blank",
                )
            )
            logger.log(
                MeasurementRecord.create(
                    sample_id="blank-02",
                    sample_type="water",
                    run_type="blank",
                )
            )

            with logger.csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 3)

    def test_duplicate_measurement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logger = DataLogger(Path(temporary_directory))
            record = MeasurementRecord.create(
                sample_id="blank-01",
                sample_type="water",
                run_type="blank",
                measurement_id="fixed-measurement-id",
            )
            logger.log(record)
            with self.assertRaises(FileExistsError):
                logger.log(record)


if __name__ == "__main__":
    unittest.main()

