from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
import zipfile

from scripts.full_local_validation import prepare_sorted_member


SOURCE = Path("data") / "Чичерина-40 Лет Победы 19.04.24.zip"
OUTPUT = Path("data") / "demo_chicherina_sorted.zip"


def main() -> None:
    print(f"Source: {SOURCE}")
    print(f"Output: {OUTPUT}")

    with zipfile.ZipFile(SOURCE, "r") as src_zip, \
            zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip, \
            tempfile.TemporaryDirectory() as tmp:

        json_members = [
            info
            for info in src_zip.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".json")
        ]

        print(f"JSON members: {len(json_members)}")

        for index, member in enumerate(json_members, start=1):
            print(f"[{index}/{len(json_members)}] {member.filename}")

            work_dir = Path(tmp) / f"member_{index:04d}"

            with src_zip.open(member) as source_stream:
                sorted_stream, audit = prepare_sorted_member(
                    source_stream,
                    name=member.filename,
                    work_dir=work_dir,
                    chunk_trajectories=500,
                )

                try:
                    data = sorted_stream.read()
                    dst_zip.writestr(member.filename, data)
                finally:
                    sorted_stream.close()

            print(
                f"    records={audit.record_count}, "
                f"cars={audit.usable_car_count}, "
                f"order_violations_before={audit.order_violation_count}"
            )

    print("DONE")
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()