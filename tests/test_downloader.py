"""
Unit tests for downloader.py

Tests cover:
- ImageryDownloader.copy_to_desktop() basic functionality
- ImageryDownloader.copy_to_desktop() with empty records
- ImageryDownloader.copy_to_desktop() with file copy failures
- ImageryDownloader.copy_to_desktop() duplicate filename handling
- DownloadResult structure and reporting
"""
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import shutil

from models import ImageryRecord, DownloadResult
from downloader import ImageryDownloader


class TestImageryDownloaderCopyToDesktop:
    """Tests for ImageryDownloader.copy_to_desktop() method."""

    @pytest.fixture
    def sample_records(self):
        """Create sample ImageryRecords for testing."""
        ingest = datetime(2024, 6, 20, 12, 0, 0)
        return [
            ImageryRecord.make(
                filepath="/source/path/to/image1.tif",
                filename="image1.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1048576, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/source/path/to/image2.jp2",
                filename="image2.jp2",
                fmt="JPEG2000",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=2097152, band_count=None, width=None, height=None,
            ),
        ]

    def test_copy_to_desktop_creates_timestamped_folder(self):
        """copy_to_desktop() should create a timestamped folder under Desktop."""
        downloader = ImageryDownloader()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source files
            src1 = Path(tmpdir) / "image1.tif"
            src1.write_text("fake imagery data 1")
            src2 = Path(tmpdir) / "image2.jp2"
            src2.write_text("fake imagery data 2")

            records = [
                ImageryRecord.make(
                    filepath=str(src1),
                    filename="image1.tif",
                    fmt="GeoTIFF",
                    extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                    spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                    file_size_bytes=20, band_count=None, width=None, height=None,
                ),
                ImageryRecord.make(
                    filepath=str(src2),
                    filename="image2.jp2",
                    fmt="JPEG2000",
                    extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                    spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                    file_size_bytes=20, band_count=None, width=None, height=None,
                ),
            ]

            with patch("pathlib.Path.home") as mock_home:
                desktop = Path(tmpdir) / "Desktop"
                desktop.mkdir()
                mock_home.return_value = Path(tmpdir)

                result = downloader.copy_to_desktop(records)

                # Check that destination was created
                assert result.dest_path != ""
                assert "ImageryBrowser_" in result.dest_path
                assert Path(result.dest_path).exists()

    def test_copy_to_desktop_copies_all_files(self):
        """copy_to_desktop() should copy all selected files."""
        downloader = ImageryDownloader()
        with tempfile.TemporaryDirectory() as tmpdir:
            src1 = Path(tmpdir) / "image1.tif"
            src1.write_text("fake imagery data 1")
            src2 = Path(tmpdir) / "image2.jp2"
            src2.write_text("fake imagery data 2")

            records = [
                ImageryRecord.make(
                    filepath=str(src1),
                    filename="image1.tif",
                    fmt="GeoTIFF",
                    extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                    spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                    file_size_bytes=20, band_count=None, width=None, height=None,
                ),
                ImageryRecord.make(
                    filepath=str(src2),
                    filename="image2.jp2",
                    fmt="JPEG2000",
                    extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                    spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                    file_size_bytes=20, band_count=None, width=None, height=None,
                ),
            ]

            with patch("pathlib.Path.home") as mock_home:
                desktop = Path(tmpdir) / "Desktop"
                desktop.mkdir()
                mock_home.return_value = Path(tmpdir)

                result = downloader.copy_to_desktop(records)

                assert result.success_count == 2
                assert result.failed_count == 0
                dest_path = Path(result.dest_path)
                assert (dest_path / "image1.tif").exists()
                assert (dest_path / "image2.jp2").exists()

    def test_copy_to_desktop_empty_records(self):
        """copy_to_desktop() with empty records list should return empty result."""
        downloader = ImageryDownloader()
        result = downloader.copy_to_desktop([])
        assert result.success_count == 0
        assert result.failed_count == 0
        assert result.dest_path == ""
        assert result.errors == []

    def test_copy_to_desktop_handles_copy_failure_gracefully(self):
        """copy_to_desktop() should handle shutil.copy2 failure gracefully."""
        downloader = ImageryDownloader()
        with tempfile.TemporaryDirectory() as tmpdir:
            src1 = Path(tmpdir) / "image1.tif"
            src1.write_text("fake imagery data 1")

            record = ImageryRecord.make(
                filepath=str(src1),
                filename="image1.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                file_size_bytes=20, band_count=None, width=None, height=None,
            )

            with patch("pathlib.Path.home") as mock_home:
                desktop = Path(tmpdir) / "Desktop"
                desktop.mkdir()
                mock_home.return_value = Path(tmpdir)

                # Mock shutil.copy2 to raise an exception
                with patch("shutil.copy2", side_effect=IOError("Permission denied")):
                    result = downloader.copy_to_desktop([record])

                    assert result.success_count == 0
                    assert result.failed_count == 1
                    assert len(result.errors) == 1
                    assert "Permission denied" in result.errors[0]

    def test_copy_to_desktop_continues_on_failure(self):
        """copy_to_desktop() should continue copying even if one file fails."""
        downloader = ImageryDownloader()
        with tempfile.TemporaryDirectory() as tmpdir:
            src1 = Path(tmpdir) / "image1.tif"
            src1.write_text("fake imagery data 1")
            src2 = Path(tmpdir) / "image2.jp2"
            src2.write_text("fake imagery data 2")

            records = [
                ImageryRecord.make(
                    filepath=str(src1),
                    filename="image1.tif",
                    fmt="GeoTIFF",
                    extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                    spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                    file_size_bytes=20, band_count=None, width=None, height=None,
                ),
                ImageryRecord.make(
                    filepath=str(src2),
                    filename="image2.jp2",
                    fmt="JPEG2000",
                    extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                    spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                    file_size_bytes=20, band_count=None, width=None, height=None,
                ),
            ]

            with patch("pathlib.Path.home") as mock_home:
                desktop = Path(tmpdir) / "Desktop"
                desktop.mkdir()
                mock_home.return_value = Path(tmpdir)

                # Mock shutil.copy2 to succeed first, then fail
                copy_count = [0]
                def side_effect(src, dst):
                    copy_count[0] += 1
                    if copy_count[0] == 1:
                        Path(dst).write_text("copied")
                    else:
                        raise IOError("Second copy failed")

                with patch("shutil.copy2", side_effect=side_effect):
                    result = downloader.copy_to_desktop(records)

                    assert result.success_count == 1
                    assert result.failed_count == 1
                    assert len(result.errors) == 1

    def test_copy_to_desktop_duplicate_filenames(self):
        """copy_to_desktop() should prefix duplicate filenames with record id."""
        downloader = ImageryDownloader()
        with tempfile.TemporaryDirectory() as tmpdir:
            src1 = Path(tmpdir) / "image.tif"
            src1.write_text("fake imagery data 1")
            src2 = Path(tmpdir) / "image.tif"  # Same name
            src2_actual = Path(tmpdir) / "image2.tif"
            src2_actual.write_text("fake imagery data 2")

            record1 = ImageryRecord.make(
                filepath=str(src1),
                filename="image.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                file_size_bytes=20, band_count=None, width=None, height=None,
            )
            record2 = ImageryRecord.make(
                filepath=str(src2_actual),
                filename="image.tif",  # Same as record1
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                file_size_bytes=20, band_count=None, width=None, height=None,
            )

            with patch("pathlib.Path.home") as mock_home:
                desktop = Path(tmpdir) / "Desktop"
                desktop.mkdir()
                mock_home.return_value = Path(tmpdir)

                result = downloader.copy_to_desktop([record1, record2])

                assert result.success_count == 2
                dest_path = Path(result.dest_path)
                # First copy should be direct name
                assert (dest_path / "image.tif").exists()
                # Second copy should have id prefix
                files_in_dest = list(dest_path.glob("*_image.tif"))
                assert len(files_in_dest) == 1

    def test_copy_to_desktop_result_dest_path_set(self):
        """copy_to_desktop() should set result.dest_path."""
        downloader = ImageryDownloader()
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "image.tif"
            src.write_text("fake")

            record = ImageryRecord.make(
                filepath=str(src),
                filename="image.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=datetime.now(),
                file_size_bytes=4, band_count=None, width=None, height=None,
            )

            with patch("pathlib.Path.home") as mock_home:
                desktop = Path(tmpdir) / "Desktop"
                desktop.mkdir()
                mock_home.return_value = Path(tmpdir)

                result = downloader.copy_to_desktop([record])

                assert result.dest_path != ""
                assert Path(result.dest_path).exists()
                assert "ImageryBrowser_" in Path(result.dest_path).name


class TestDownloadResultClass:
    """Tests for DownloadResult data structure."""

    def test_default_download_result(self):
        """DownloadResult should have sensible defaults."""
        result = DownloadResult()
        assert result.success_count == 0
        assert result.failed_count == 0
        assert result.dest_path == ""
        assert result.errors == []

    def test_download_result_with_values(self):
        """DownloadResult should accept initialization values."""
        result = DownloadResult(
            success_count=5,
            failed_count=2,
            dest_path="/path/to/dest",
            errors=["Error 1", "Error 2"],
        )
        assert result.success_count == 5
        assert result.failed_count == 2
        assert result.dest_path == "/path/to/dest"
        assert result.errors == ["Error 1", "Error 2"]

    def test_download_result_summary_success_only(self):
        """DownloadResult.summary() should format success-only results."""
        result = DownloadResult(
            success_count=5,
            failed_count=0,
            dest_path="/Users/test/Desktop/ImageryBrowser_20240620_143000",
            errors=[],
        )
        summary = result.summary()
        assert "Downloaded 5 file(s)" in summary
        assert "/Users/test/Desktop/ImageryBrowser_20240620_143000" in summary

    def test_download_result_summary_with_errors(self):
        """DownloadResult.summary() should include error details."""
        result = DownloadResult(
            success_count=3,
            failed_count=2,
            dest_path="/Users/test/Desktop/ImageryBrowser_20240620_143000",
            errors=["file1.tif: Permission denied", "file2.tif: File not found"],
        )
        summary = result.summary()
        assert "3 file(s)" in summary
        assert "2 file(s) failed" in summary
        assert "file1.tif: Permission denied" in summary
        assert "file2.tif: File not found" in summary
