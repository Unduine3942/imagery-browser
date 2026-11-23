from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from models import DownloadResult, ImageryRecord


class ImageryDownloader:
    def copy_to(self, records: list[ImageryRecord], dest_dir: str) -> DownloadResult:
        """Copy records into a timestamped subfolder inside dest_dir."""
        result = DownloadResult()
        if not records:
            return result

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path(dest_dir) / f"ImageryBrowser_{timestamp}"
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result.errors.append(f"Cannot create destination folder: {exc}")
            result.failed_count = len(records)
            return result
        result.dest_path = str(dest)

        for record in records:
            src_raw = Path(record.filepath)
            if src_raw.is_symlink():
                result.failed_count += 1
                result.errors.append(f"{record.filename}: symbolic links are not supported")
                continue
            src = src_raw.resolve()
            if not src.is_file():
                result.failed_count += 1
                result.errors.append(f"{record.filename}: source not found or not a regular file")
                continue
            dst = dest / record.filename
            # Avoid clobbering duplicates by appending the record id prefix
            if dst.exists():
                dst = dest / f"{record.id[:8]}_{record.filename}"
            try:
                shutil.copy2(str(src), str(dst))
                result.success_count += 1
            except Exception as exc:
                result.failed_count += 1
                result.errors.append(f"{record.filename}: {exc}")

        return result
