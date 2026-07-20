"""Durable CSV and JSON logging for WaterLAB measurements."""

import argparse
import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
from typing import Optional, Sequence

from .schemas import MeasurementRecord


class DataLogger:
    """Persist synchronized raw evidence and metadata under one ID."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.images_dir = self.root / "raw" / "images"
        self.records_dir = self.root / "records"
        self.csv_path = self.root / "measurements.csv"

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        record: MeasurementRecord,
        source_image: Optional[Path] = None,
    ) -> MeasurementRecord:
        """Write one measurement and optionally copy its original image.

        Returns the stored record, including the repository-relative image
        path when ``source_image`` is supplied.
        """

        record.validate()
        self._validate_csv_schema()
        json_path = self.records_dir / "{}.json".format(record.measurement_id)
        if json_path.exists():
            raise FileExistsError(
                "Measurement already exists: {}".format(record.measurement_id)
            )

        stored_record = record
        if source_image is not None:
            stored_record = self._copy_image(record, Path(source_image))

        self._write_json(stored_record, json_path)
        self._append_csv(stored_record)
        return stored_record

    def _validate_csv_schema(self) -> None:
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            return
        with self.csv_path.open("r", encoding="utf-8", newline="") as handle:
            existing_header = next(csv.reader(handle), None)
        expected_header = list(MeasurementRecord.csv_fieldnames())
        if existing_header != expected_header:
            raise ValueError(
                "measurements.csv uses a different schema. Start a new --root "
                "directory or migrate the existing dataset before appending."
            )

    def _copy_image(
        self, record: MeasurementRecord, source_image: Path
    ) -> MeasurementRecord:
        if not source_image.is_file():
            raise FileNotFoundError("Image does not exist: {}".format(source_image))

        suffix = source_image.suffix.lower() or ".img"
        destination = self.images_dir / "{}{}".format(
            record.measurement_id, suffix
        )
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(str(source_image), str(temporary))
        os.replace(str(temporary), str(destination))

        relative_path = destination.relative_to(self.root).as_posix()
        return replace(record, image_path=relative_path)

    @staticmethod
    def _write_json(record: MeasurementRecord, destination: Path) -> None:
        temporary = destination.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                record.to_json_dict(),
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(destination))

    def _append_csv(self, record: MeasurementRecord) -> None:
        write_header = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        with self.csv_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=MeasurementRecord.csv_fieldnames(),
                extrasaction="raise",
            )
            if write_header:
                writer.writeheader()
            writer.writerow(record.to_csv_row())
            handle.flush()
            os.fsync(handle.fileno())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a WaterLAB measurement record."
    )
    parser.add_argument("--root", default="data", help="Data directory")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--sample-type", required=True)
    parser.add_argument(
        "--run-type",
        required=True,
        choices=("blank", "reference", "sample", "calibration", "replay"),
    )
    parser.add_argument("--source-image")
    parser.add_argument("--excitation-nm", type=int)
    parser.add_argument("--notes", default="")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    record = MeasurementRecord.create(
        sample_id=args.sample_id,
        sample_type=args.sample_type,
        run_type=args.run_type,
        excitation_nm=args.excitation_nm,
        operator_notes=args.notes,
    )
    stored = DataLogger(Path(args.root)).log(
        record,
        source_image=Path(args.source_image) if args.source_image else None,
    )
    print(stored.measurement_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
