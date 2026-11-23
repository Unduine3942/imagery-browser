"""
Unit tests for airgapped_transfer.py

TDD — tests written before implementation.
Covers:
- AirgappedTransfer.package() happy path
- manifest.json written with correct record metadata
- manifest loadable via ImageryRecord.from_dict()
- empty records list
- copy failures (partial and total)
- duplicate filename collision handling
- dest_dir created when absent
- TransferPackage.summary() formatting
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from airgapped_transfer import (
    AirgappedImporter,
    AirgappedTransfer,
    ImportResult,
    TransferPackage,
    _companion_files,
)
from models import ImageryRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(
    tmpdir: str,
    filename: str,
    content: str = "imagery bytes",
    fmt: str = "GeoTIFF",
    acq_date: datetime | None = None,
    extent: tuple[float, float, float, float] | None = (-10.0, -10.0, 10.0, 10.0),
) -> ImageryRecord:
    src = Path(tmpdir) / filename
    src.write_text(content)
    minx, miny, maxx, maxy = extent if extent else (None, None, None, None)
    return ImageryRecord.make(
        filepath=str(src),
        filename=filename,
        fmt=fmt,
        extent_minx=minx,
        extent_miny=miny,
        extent_maxx=maxx,
        extent_maxy=maxy,
        spatial_ref_wkid=4326,
        acquisition_date=acq_date,
        ingest_date=datetime(2024, 1, 1),
        file_size_bytes=len(content),
        band_count=3,
        width=512,
        height=512,
    )


# ---------------------------------------------------------------------------
# AirgappedTransfer.package()
# ---------------------------------------------------------------------------

class TestPackageHappyPath:
    def test_creates_dest_dir_when_missing(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb" / "imagery_pkg"  # does not exist yet

            record = _make_record(str(src_dir), "image1.tif")
            result = transfer.package([record], str(dest))

            assert Path(result.dest_path).exists()

    def test_copies_all_imagery_files(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            r1 = _make_record(str(src_dir), "alpha.tif")
            r2 = _make_record(str(src_dir), "bravo.jp2", fmt="JPEG2000")
            result = transfer.package([r1, r2], str(dest))

            assert result.success_count == 2
            assert result.failed_count == 0
            assert (Path(result.dest_path) / "alpha.tif").exists()
            assert (Path(result.dest_path) / "bravo.jp2").exists()

    def test_writes_manifest_json(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            record = _make_record(str(src_dir), "scene.tif")
            result = transfer.package([record], str(dest))

            manifest_path = Path(result.manifest_path)
            assert manifest_path.exists()
            assert manifest_path.name == "manifest.json"

    def test_manifest_contains_all_records(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            r1 = _make_record(str(src_dir), "img1.tif")
            r2 = _make_record(str(src_dir), "img2.tif")
            result = transfer.package([r1, r2], str(dest))

            with open(result.manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)

            assert "records" in data
            assert len(data["records"]) == 2

    def test_manifest_records_are_loadable(self):
        """Records serialised into manifest can round-trip via ImageryRecord.from_dict()."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            acq = datetime(2023, 6, 15, 8, 30)
            original = _make_record(str(src_dir), "scene.tif", acq_date=acq)
            result = transfer.package([original], str(dest))

            with open(result.manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)

            loaded = ImageryRecord.from_dict(data["records"][0])
            assert loaded.filename == original.filename
            assert loaded.format == original.format
            assert loaded.acquisition_date == acq
            assert loaded.extent_minx == original.extent_minx

    def test_manifest_filepath_is_relative_to_package(self):
        """Manifest record filepaths should be relative so the package is portable."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            record = _make_record(str(src_dir), "scene.tif")
            result = transfer.package([record], str(dest))

            with open(result.manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)

            fp = data["records"][0]["filepath"]
            assert not Path(fp).is_absolute(), f"Expected relative path, got: {fp}"

    def test_manifest_includes_package_metadata(self):
        """Manifest should include a top-level created_at timestamp and record count."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            record = _make_record(str(src_dir), "scene.tif")
            result = transfer.package([record], str(dest))

            with open(result.manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)

            assert "created_at" in data
            assert "record_count" in data
            assert data["record_count"] == 1

    def test_dest_path_on_result_matches_created_folder(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            record = _make_record(str(src_dir), "scene.tif")
            result = transfer.package([record], str(dest))

            assert Path(result.dest_path).is_dir()


# ---------------------------------------------------------------------------
# Empty records
# ---------------------------------------------------------------------------

class TestPackageEmptyRecords:
    def test_empty_records_returns_zero_counts(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "usb"
            result = transfer.package([], str(dest))

            assert result.success_count == 0
            assert result.failed_count == 0

    def test_empty_records_no_dest_created(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "usb"
            transfer.package([], str(dest))

            assert not dest.exists()

    def test_empty_records_manifest_path_empty(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "usb"
            result = transfer.package([], str(dest))

            assert result.manifest_path == ""


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

class TestPackageFailures:
    def test_copy_failure_recorded_in_result(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            record = _make_record(str(src_dir), "scene.tif")

            with patch("shutil.copy2", side_effect=OSError("disk full")):
                result = transfer.package([record], str(dest))

            assert result.failed_count == 1
            assert result.success_count == 0
            assert any("disk full" in e for e in result.errors)

    def test_partial_failure_continues_copying(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            r1 = _make_record(str(src_dir), "good.tif")
            r2 = _make_record(str(src_dir), "bad.tif")

            call_count = [0]

            def side_effect(src, dst):
                call_count[0] += 1
                if call_count[0] == 1:
                    Path(dst).write_text("copied")
                else:
                    raise OSError("write error")

            with patch("shutil.copy2", side_effect=side_effect):
                result = transfer.package([r1, r2], str(dest))

            assert result.success_count == 1
            assert result.failed_count == 1

    def test_failed_records_excluded_from_manifest(self):
        """Only successfully copied records appear in manifest.json."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            r1 = _make_record(str(src_dir), "good.tif")
            r2 = _make_record(str(src_dir), "bad.tif")

            call_count = [0]

            def side_effect(src, dst):
                call_count[0] += 1
                if call_count[0] == 1:
                    Path(dst).write_text("copied")
                else:
                    raise OSError("write error")

            with patch("shutil.copy2", side_effect=side_effect):
                result = transfer.package([r1, r2], str(dest))

            with open(result.manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)

            assert data["record_count"] == 1
            assert len(data["records"]) == 1
            assert data["records"][0]["filename"] == "good.tif"


# ---------------------------------------------------------------------------
# Duplicate filenames
# ---------------------------------------------------------------------------

class TestPackageDuplicateFilenames:
    def test_duplicate_filenames_get_id_prefix(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            r1 = _make_record(str(src_dir), "image.tif", content="first")
            # Create a second source file with same logical filename
            src2 = src_dir / "subdir"
            src2.mkdir()
            (src2 / "image.tif").write_text("second")
            r2 = ImageryRecord.make(
                filepath=str(src2 / "image.tif"),
                filename="image.tif",
                fmt="GeoTIFF",
                extent_minx=-10.0, extent_miny=-10.0, extent_maxx=10.0, extent_maxy=10.0,
                spatial_ref_wkid=4326, acquisition_date=None,
                ingest_date=datetime(2024, 1, 1),
                file_size_bytes=6, band_count=None, width=None, height=None,
            )

            result = transfer.package([r1, r2], str(dest))

            assert result.success_count == 2
            dest_files = list(Path(result.dest_path).glob("*.tif"))
            assert len(dest_files) == 2


# ---------------------------------------------------------------------------
# TransferPackage.summary()
# ---------------------------------------------------------------------------

class TestTransferPackageSummary:
    def test_summary_includes_count_and_path(self):
        pkg = TransferPackage(
            dest_path="/media/usb/pkg",
            manifest_path="/media/usb/pkg/manifest.json",
            success_count=3,
            failed_count=0,
        )
        s = pkg.summary()
        assert "3" in s
        assert "/media/usb/pkg" in s

    def test_summary_includes_manifest_path(self):
        pkg = TransferPackage(
            dest_path="/media/usb/pkg",
            manifest_path="/media/usb/pkg/manifest.json",
            success_count=1,
            failed_count=0,
        )
        assert "manifest.json" in pkg.summary()

    def test_summary_includes_errors_when_present(self):
        pkg = TransferPackage(
            dest_path="/media/usb/pkg",
            manifest_path="/media/usb/pkg/manifest.json",
            success_count=2,
            failed_count=1,
            errors=["scene.tif: disk full"],
        )
        s = pkg.summary()
        assert "failed" in s.lower()
        assert "scene.tif" in s

    def test_summary_no_errors_section_when_clean(self):
        pkg = TransferPackage(
            dest_path="/media/usb/pkg",
            manifest_path="/media/usb/pkg/manifest.json",
            success_count=5,
            failed_count=0,
        )
        assert "failed" not in pkg.summary().lower()


# ---------------------------------------------------------------------------
# Companion / sidecar file handling
# ---------------------------------------------------------------------------

class TestCompanionFiles:
    def test_no_companions_when_none_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = Path(tmpdir) / "image.tif"
            primary.write_text("data")
            assert _companion_files(primary) == []

    def test_finds_prj_and_hdr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = Path(tmpdir) / "image.bil"
            primary.write_text("data")
            (Path(tmpdir) / "image.prj").write_text("projection")
            (Path(tmpdir) / "image.hdr").write_text("header")
            companions = {p.name for p in _companion_files(primary)}
            assert "image.prj" in companions
            assert "image.hdr" in companions

    def test_finds_aux_xml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = Path(tmpdir) / "scene.tif"
            primary.write_text("data")
            (Path(tmpdir) / "scene.tif.aux.xml").write_text("<xml/>")
            companions = {p.name for p in _companion_files(primary)}
            assert "scene.tif.aux.xml" in companions

    def test_primary_not_included_as_own_companion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = Path(tmpdir) / "image.ovr"
            primary.write_text("data")
            companions = _companion_files(primary)
            assert primary not in companions


class TestPackageWithCompanions:
    def test_companions_are_copied_alongside_primary(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            (src_dir / "image.bil").write_text("data")
            (src_dir / "image.hdr").write_text("header")
            (src_dir / "image.prj").write_text("projection")

            record = _make_record(str(src_dir), "image.bil", fmt="BIL")
            transfer.package([record], str(dest))

            assert (dest / "image.hdr").exists()
            assert (dest / "image.prj").exists()

    def test_aux_xml_copied_alongside_primary(self):
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            (src_dir / "scene.tif").write_text("tif data")
            (src_dir / "scene.tif.aux.xml").write_text("<PAMDataset/>")

            record = _make_record(str(src_dir), "scene.tif")
            transfer.package([record], str(dest))

            assert (dest / "scene.tif.aux.xml").exists()

    def test_companions_renamed_with_prefix_when_primary_renamed(self):
        """When primary file gets an id prefix due to collision, companions match."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            r1 = _make_record(str(src_dir), "image.tif", content="first")

            src2 = src_dir / "sub"
            src2.mkdir()
            (src2 / "image.tif").write_text("second")
            (src2 / "image.tif.aux.xml").write_text("<xml/>")
            r2 = ImageryRecord.make(
                filepath=str(src2 / "image.tif"),
                filename="image.tif",
                fmt="GeoTIFF",
                extent_minx=-10.0, extent_miny=-10.0, extent_maxx=10.0, extent_maxy=10.0,
                spatial_ref_wkid=4326, acquisition_date=None,
                ingest_date=datetime(2024, 1, 1),
                file_size_bytes=6, band_count=None, width=None, height=None,
            )

            transfer.package([r1, r2], str(dest))

            # The aux.xml for r2 should have the same prefix as r2's renamed primary
            aux_xmls = list(dest.glob("*.aux.xml"))
            assert len(aux_xmls) == 1
            assert aux_xmls[0].name.startswith(r2.id[:8])

    def test_companion_failure_does_not_increment_failed_count(self):
        """A sidecar copy failure should not count as a record failure."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            (src_dir / "image.tif").write_text("data")
            (src_dir / "image.ovr").write_text("overview")

            record = _make_record(str(src_dir), "image.tif")

            original_copy2 = shutil.copy2

            def selective_fail(src, dst):
                if str(src).endswith(".ovr"):
                    raise OSError("disk full")
                return original_copy2(src, dst)

            with patch("shutil.copy2", side_effect=selective_fail):
                result = transfer.package([record], str(dest))

            assert result.success_count == 1
            assert result.failed_count == 0
            assert any("ovr" in e for e in result.errors)

    def test_companions_not_in_manifest(self):
        """Companion files should not appear as records in the manifest."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "usb"

            (src_dir / "image.bil").write_text("data")
            (src_dir / "image.hdr").write_text("header")

            record = _make_record(str(src_dir), "image.bil", fmt="BIL")
            result = transfer.package([record], str(dest))

            with open(result.manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)

            assert data["record_count"] == 1
            filenames = [r["filename"] for r in data["records"]]
            assert "image.hdr" not in filenames


# ---------------------------------------------------------------------------
# Security fixes: symlinks, directory checks, path traversal protection
# ---------------------------------------------------------------------------

class TestPackageSecurityFixes:
    """Test security-critical paths: symlink detection, directory rejection, path traversal prevention.

    These tests validate the security fixes in package():
    - Symlinks are detected and rejected before being followed
    - Directories (non-regular files) are rejected
    - Path traversal attempts in filenames are blocked
    - Sidecar path traversal is blocked
    """

    def test_source_symlink_is_rejected(self):
        """Security fix: Symlinks in source files are rejected.

        The check must occur BEFORE Path.resolve() collapses the symlink,
        otherwise is_symlink() will return False on the resolved path.
        """
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "dest"

            # Create a real file and a symlink to it
            real_file = src_dir / "real.tif"
            real_file.write_text("data")
            symlink_file = src_dir / "link.tif"

            try:
                symlink_file.symlink_to(real_file)
            except (OSError, PermissionError):
                pytest.skip("Cannot create symlinks on this system")

            # Create record pointing to the symlink
            record = ImageryRecord.make(
                filepath=str(symlink_file),
                filename="link.tif",
                fmt="GeoTIFF",
                extent_minx=-10.0, extent_miny=-10.0, extent_maxx=10.0, extent_maxy=10.0,
                spatial_ref_wkid=4326, acquisition_date=None,
                ingest_date=datetime(2024, 1, 1),
                file_size_bytes=4, band_count=None, width=None, height=None,
            )

            result = transfer.package([record], str(dest))

            # Security fix: Symlink should be rejected
            assert result.failed_count == 1
            assert result.success_count == 0
            assert any("symbolic links are not supported" in e for e in result.errors)

    def test_source_directory_is_skipped(self):
        """Source is a directory (not a regular file) → skipped with failed_count += 1."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "dest"

            # Create a directory as a "source"
            data_dir = src_dir / "data_folder"
            data_dir.mkdir()

            record = ImageryRecord.make(
                filepath=str(data_dir),
                filename="data_folder",
                fmt="GeoTIFF",
                extent_minx=-10.0, extent_miny=-10.0, extent_maxx=10.0, extent_maxy=10.0,
                spatial_ref_wkid=4326, acquisition_date=None,
                ingest_date=datetime(2024, 1, 1),
                file_size_bytes=0, band_count=None, width=None, height=None,
            )

            result = transfer.package([record], str(dest))

            assert result.failed_count == 1
            assert result.success_count == 0
            assert any("not a regular file" in e for e in result.errors)

    def test_destination_path_traversal_in_filename_is_rejected(self):
        """record.filename contains ../ path traversal → destination escapes dest_dir."""
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "dest"

            # Create a source file
            real_file = src_dir / "real.tif"
            real_file.write_text("data")

            # Create record with malicious filename containing ../
            record = ImageryRecord.make(
                filepath=str(real_file),
                filename="../../../etc/passwd",  # path traversal attempt
                fmt="GeoTIFF",
                extent_minx=-10.0, extent_miny=-10.0, extent_maxx=10.0, extent_maxy=10.0,
                spatial_ref_wkid=4326, acquisition_date=None,
                ingest_date=datetime(2024, 1, 1),
                file_size_bytes=4, band_count=None, width=None, height=None,
            )

            result = transfer.package([record], str(dest))

            # Should detect that resolved path escapes dest_dir
            assert result.failed_count == 1
            assert result.success_count == 0
            assert any("escapes transfer directory" in e for e in result.errors)

    def test_primary_file_path_traversal_is_caught(self):
        """Path traversal in record.filename is blocked.

        Even if record.filename contains ../, the resolved destination path
        is checked to ensure it doesn't escape dest_dir.
        """
        transfer = AirgappedTransfer()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "dest"

            # Create main file
            (src_dir / "image.tif").write_text("tif data")

            record = _make_record(str(src_dir), "image.tif")

            # Change the filename to include path traversal
            # Create a new record with malicious filename
            from datetime import datetime
            from models import ImageryRecord

            malicious_record = ImageryRecord.make(
                filepath=str(src_dir / "image.tif"),
                filename="../../../etc/passwd",  # path traversal
                fmt="GeoTIFF",
                extent_minx=-10.0, extent_miny=-10.0, extent_maxx=10.0, extent_maxy=10.0,
                spatial_ref_wkid=4326, acquisition_date=None,
                ingest_date=datetime(2024, 1, 1),
                file_size_bytes=8, band_count=None, width=None, height=None,
            )

            result = transfer.package([malicious_record], str(dest))

            # Should be rejected as destination escapes
            assert result.failed_count == 1
            assert any("escapes transfer directory" in e for e in result.errors)


# ---------------------------------------------------------------------------
# AirgappedImporter.import_from_manifest()
# ---------------------------------------------------------------------------

def _write_package(dest: Path, records: list[ImageryRecord]) -> Path:
    """Helper: run AirgappedTransfer.package() and return the manifest path."""
    src_dir = dest.parent / "source"
    src_dir.mkdir(exist_ok=True)
    # Ensure source files exist
    for r in records:
        p = Path(r.filepath)
        if not p.exists():
            p.write_text("imagery bytes")
    result = AirgappedTransfer().package(records, str(dest))
    return Path(result.manifest_path)


class TestImporterHappyPath:
    def test_single_record_imported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            record = _make_record(str(src_dir), "scene.tif")
            manifest = _write_package(dest, [record])

            result = AirgappedImporter().import_from_manifest(str(manifest))

            assert len(result.records) == 1
            assert result.missing_count == 0
            assert result.errors == []

    def test_multiple_records_imported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            r1 = _make_record(str(src_dir), "alpha.tif")
            r2 = _make_record(str(src_dir), "bravo.jp2", fmt="JPEG2000")
            manifest = _write_package(dest, [r1, r2])

            result = AirgappedImporter().import_from_manifest(str(manifest))

            assert len(result.records) == 2
            filenames = {r.filename for r in result.records}
            assert "alpha.tif" in filenames
            assert "bravo.jp2" in filenames

    def test_metadata_preserved_after_import(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            acq = datetime(2023, 6, 15, 8, 30)
            original = _make_record(str(src_dir), "scene.tif", acq_date=acq)
            manifest = _write_package(dest, [original])

            result = AirgappedImporter().import_from_manifest(str(manifest))

            imported = result.records[0]
            assert imported.filename == original.filename
            assert imported.format == original.format
            assert imported.acquisition_date == acq
            assert imported.extent_minx == original.extent_minx

    def test_imported_filepath_is_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            record = _make_record(str(src_dir), "scene.tif")
            manifest = _write_package(dest, [record])

            result = AirgappedImporter().import_from_manifest(str(manifest))

            imported = result.records[0]
            assert Path(imported.filepath).is_absolute()

    def test_imported_filepath_points_to_package_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            record = _make_record(str(src_dir), "scene.tif")
            manifest = _write_package(dest, [record])

            result = AirgappedImporter().import_from_manifest(str(manifest))

            imported = result.records[0]
            fp = Path(imported.filepath)
            assert fp.is_file()
            assert str(fp).startswith(str(dest))

    def test_summary_shows_record_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            r1 = _make_record(str(src_dir), "a.tif")
            r2 = _make_record(str(src_dir), "b.tif")
            manifest = _write_package(dest, [r1, r2])

            result = AirgappedImporter().import_from_manifest(str(manifest))

            assert "2" in result.summary()


class TestImporterErrors:
    def test_missing_manifest_returns_error(self):
        result = AirgappedImporter().import_from_manifest("/nonexistent/path/manifest.json")

        assert len(result.records) == 0
        assert len(result.errors) == 1
        assert "Manifest not found" in result.errors[0]

    def test_invalid_json_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_manifest = Path(tmpdir) / "manifest.json"
            bad_manifest.write_text("NOT JSON {{{}}", encoding="utf-8")

            result = AirgappedImporter().import_from_manifest(str(bad_manifest))

            assert len(result.records) == 0
            assert any("Cannot read manifest" in e for e in result.errors)

    def test_empty_records_list_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.json"
            manifest.write_text(
                json.dumps({"created_at": "2024-01-01", "record_count": 0, "records": []}),
                encoding="utf-8",
            )

            result = AirgappedImporter().import_from_manifest(str(manifest))

            assert len(result.records) == 0
            assert result.missing_count == 0
            assert result.errors == []

    def test_missing_file_in_package_increments_missing_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            record = _make_record(str(src_dir), "scene.tif")
            manifest = _write_package(dest, [record])

            # Delete the copied file from the package so importer can't find it
            (dest / "scene.tif").unlink()

            result = AirgappedImporter().import_from_manifest(str(manifest))

            assert len(result.records) == 0
            assert result.missing_count == 1
            assert any("scene.tif" in e for e in result.errors)

    def test_malformed_record_in_manifest_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "created_at": "2024-01-01",
                    "record_count": 1,
                    "records": [{"not": "a valid record"}],
                }),
                encoding="utf-8",
            )

            result = AirgappedImporter().import_from_manifest(str(manifest))

            assert len(result.records) == 0
            assert result.missing_count == 1
            assert any("Bad record" in e for e in result.errors)


class TestImporterPartialSuccess:
    def test_one_missing_one_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            r1 = _make_record(str(src_dir), "good.tif")
            r2 = _make_record(str(src_dir), "bad.tif")
            manifest = _write_package(dest, [r1, r2])

            # Delete one of the copied files
            (dest / "bad.tif").unlink()

            result = AirgappedImporter().import_from_manifest(str(manifest))

            assert len(result.records) == 1
            assert result.missing_count == 1
            assert result.records[0].filename == "good.tif"

    def test_summary_shows_missing_count_when_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            dest = Path(tmpdir) / "pkg"
            r1 = _make_record(str(src_dir), "good.tif")
            r2 = _make_record(str(src_dir), "gone.tif")
            manifest = _write_package(dest, [r1, r2])
            (dest / "gone.tif").unlink()

            result = AirgappedImporter().import_from_manifest(str(manifest))

            summary = result.summary()
            assert "1" in summary  # 1 record imported
            assert "not found" in summary.lower()


class TestImportResult:
    def test_summary_no_errors(self):
        r = ImportResult(records=["a", "b", "c"])  # type: ignore[list-item]
        assert "3" in r.summary()
        assert "not found" not in r.summary().lower()

    def test_summary_with_missing(self):
        r = ImportResult(missing_count=2, errors=["x: not found", "y: not found"])
        assert "2" in r.summary()
        assert "not found" in r.summary().lower()

    def test_summary_truncates_errors_after_five(self):
        errors = [f"file{i}.tif: not found" for i in range(10)]
        r = ImportResult(missing_count=10, errors=errors)
        summary = r.summary()
        # Only first 5 errors should appear
        assert "file0.tif" in summary
        assert "file4.tif" in summary
        assert "file5.tif" not in summary
