"""
Unit tests for models.py

Tests cover:
- ImageryRecord.make() centroid calculation
- ImageryRecord.has_extent() extent detection
- ImageryRecord.get_display_name() formatting
- ImageryRecord.to_dict() / from_dict() round-trip serialization
- DownloadResult.summary() result reporting
"""
import pytest
from datetime import datetime
from models import ImageryRecord, ImageryScanResult, DownloadResult


class TestImageryRecordMake:
    """Tests for ImageryRecord.make() factory method."""

    def test_make_computes_centroid_from_extent(self):
        """Centroid should be computed as midpoint of extent bounds."""
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="file.tif",
            fmt="GeoTIFF",
            extent_minx=0.0,
            extent_miny=0.0,
            extent_maxx=100.0,
            extent_maxy=100.0,
            spatial_ref_wkid=4326,
            acquisition_date=None,
            ingest_date=datetime(2025, 1, 15),
            file_size_bytes=1024 * 1024,
            band_count=3,
            width=512,
            height=512,
        )
        assert record.centroid_x == 50.0
        assert record.centroid_y == 50.0

    def test_make_centroid_none_when_extent_incomplete(self):
        """Centroid should be None if any extent field is None."""
        test_cases = [
            (None, 0.0, 100.0, 100.0),  # minx None
            (0.0, None, 100.0, 100.0),  # miny None
            (0.0, 0.0, None, 100.0),    # maxx None
            (0.0, 0.0, 100.0, None),    # maxy None
        ]
        for minx, miny, maxx, maxy in test_cases:
            record = ImageryRecord.make(
                filepath="/path/to/file.tif",
                filename="file.tif",
                fmt="GeoTIFF",
                extent_minx=minx,
                extent_miny=miny,
                extent_maxx=maxx,
                extent_maxy=maxy,
                spatial_ref_wkid=None,
                acquisition_date=None,
                ingest_date=datetime.now(),
                file_size_bytes=0,
                band_count=None,
                width=None,
                height=None,
            )
            assert record.centroid_x is None
            assert record.centroid_y is None

    def test_make_all_extent_none(self):
        """Centroid should be None when all extent fields are None."""
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="file.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        assert record.centroid_x is None
        assert record.centroid_y is None

    def test_make_generates_unique_ids(self):
        """Each call to make() should generate a unique id."""
        record1 = ImageryRecord.make(
            filepath="/path/to/file1.tif",
            filename="file1.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        record2 = ImageryRecord.make(
            filepath="/path/to/file2.tif",
            filename="file2.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        assert record1.id != record2.id


class TestImageryRecordHasExtent:
    """Tests for ImageryRecord.has_extent() method."""

    def test_has_extent_true_with_complete_extent(self):
        """has_extent() should return True when all extent fields are present."""
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="file.tif",
            fmt="GeoTIFF",
            extent_minx=-120.0,
            extent_miny=30.0,
            extent_maxx=-100.0,
            extent_maxy=50.0,
            spatial_ref_wkid=4326,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        assert record.has_extent() is True

    def test_has_extent_false_with_any_none(self):
        """has_extent() should return False if any extent field is None."""
        test_cases = [
            (None, 30.0, -100.0, 50.0),
            (-120.0, None, -100.0, 50.0),
            (-120.0, 30.0, None, 50.0),
            (-120.0, 30.0, -100.0, None),
        ]
        for minx, miny, maxx, maxy in test_cases:
            record = ImageryRecord.make(
                filepath="/path/to/file.tif",
                filename="file.tif",
                fmt="GeoTIFF",
                extent_minx=minx,
                extent_miny=miny,
                extent_maxx=maxx,
                extent_maxy=maxy,
                spatial_ref_wkid=None,
                acquisition_date=None,
                ingest_date=datetime.now(),
                file_size_bytes=0,
                band_count=None,
                width=None,
                height=None,
            )
            assert record.has_extent() is False

    def test_has_extent_false_all_none(self):
        """has_extent() should return False when all extent fields are None."""
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="file.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        assert record.has_extent() is False


class TestImageryRecordGetDisplayName:
    """Tests for ImageryRecord.get_display_name() formatting.

    Files matching SensorPlatform_Date_Type_Name convention produce
    "sensor | type | scene" (+ optional dims/bands).
    Plain filenames that don't match the convention fall back to
    just the filename (+ optional dims/bands). Format string is never shown.
    """

    def test_display_name_plain_filename_fallback(self):
        """Plain filenames that don't match the naming convention return just the filename."""
        record = ImageryRecord.make(
            filepath="/path/to/image.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        assert record.get_display_name() == "image.tif"

    def test_display_name_plain_filename_with_dimensions(self):
        """Plain filename with dims appended when width and height are both present."""
        record = ImageryRecord.make(
            filepath="/path/to/image.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=1024,
            height=2048,
        )
        assert record.get_display_name() == "image.tif | 1024x2048"

    def test_display_name_plain_filename_with_band_count(self):
        """Plain filename with band count appended when band_count is present."""
        record = ImageryRecord.make(
            filepath="/path/to/image.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=4,
            width=None,
            height=None,
        )
        assert record.get_display_name() == "image.tif | 4B"

    def test_display_name_convention_filename_full(self):
        """SensorPlatform_Date_Type_Name filename produces sensor | type | scene | dims | bands."""
        record = ImageryRecord.make(
            filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
            filename="W3_20240510_PAN_HARBOR.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=3,
            width=512,
            height=512,
        )
        assert record.get_display_name() == "W3 | PAN | HARBOR | 512x512 | 3B"

    def test_display_name_convention_filename_no_extras(self):
        """SensorPlatform_Date_Type_Name filename without dims/bands: sensor | type | scene."""
        record = ImageryRecord.make(
            filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
            filename="W3_20240510_PAN_HARBOR.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        assert record.get_display_name() == "W3 | PAN | HARBOR"

    def test_display_name_dims_omitted_when_only_width(self):
        """Dimensions are omitted if only width is present (height missing)."""
        record = ImageryRecord.make(
            filepath="/path/to/image.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=512,
            height=None,
        )
        assert record.get_display_name() == "image.tif"

    def test_display_name_dims_omitted_when_only_height(self):
        """Dimensions are omitted if only height is present (width missing)."""
        record = ImageryRecord.make(
            filepath="/path/to/image.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=datetime.now(),
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=512,
        )
        assert record.get_display_name() == "image.tif"


class TestImageryRecordSerialization:
    """Tests for to_dict() and from_dict() round-trip serialization."""

    def test_to_dict_with_complete_record(self):
        """to_dict() should return all fields as a dictionary."""
        acq_date = datetime(2024, 6, 15, 10, 30, 0)
        ingest_date = datetime(2024, 6, 20, 14, 45, 0)
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=-120.0,
            extent_miny=30.0,
            extent_maxx=-100.0,
            extent_maxy=50.0,
            spatial_ref_wkid=4326,
            acquisition_date=acq_date,
            ingest_date=ingest_date,
            file_size_bytes=1024 * 1024,
            band_count=3,
            width=512,
            height=512,
        )
        d = record.to_dict()
        assert d["filepath"] == "/path/to/file.tif"
        assert d["filename"] == "image.tif"
        assert d["format"] == "GeoTIFF"
        assert d["extent_minx"] == -120.0
        assert d["extent_miny"] == 30.0
        assert d["extent_maxx"] == -100.0
        assert d["extent_maxy"] == 50.0
        assert d["centroid_x"] == -110.0
        assert d["centroid_y"] == 40.0
        assert d["spatial_ref_wkid"] == 4326
        assert d["acquisition_date"] == "2024-06-15T10:30:00"
        assert d["ingest_date"] == "2024-06-20T14:45:00"
        assert d["file_size_bytes"] == 1024 * 1024
        assert d["band_count"] == 3
        assert d["width"] == 512
        assert d["height"] == 512

    def test_to_dict_with_none_acquisition_date(self):
        """to_dict() should serialize None acquisition_date as None."""
        ingest_date = datetime(2024, 6, 20)
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=ingest_date,
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        d = record.to_dict()
        assert d["acquisition_date"] is None
        assert d["ingest_date"] == "2024-06-20T00:00:00"

    def test_from_dict_complete_record(self):
        """from_dict() should reconstruct a record from dictionary."""
        d = {
            "id": "12345678-1234-5678-1234-567812345678",
            "filepath": "/path/to/file.tif",
            "filename": "image.tif",
            "format": "GeoTIFF",
            "extent_minx": -120.0,
            "extent_miny": 30.0,
            "extent_maxx": -100.0,
            "extent_maxy": 50.0,
            "centroid_x": -110.0,
            "centroid_y": 40.0,
            "spatial_ref_wkid": 4326,
            "acquisition_date": "2024-06-15T10:30:00",
            "ingest_date": "2024-06-20T14:45:00",
            "file_size_bytes": 1048576,
            "band_count": 3,
            "width": 512,
            "height": 512,
        }
        record = ImageryRecord.from_dict(d)
        assert record.id == "12345678-1234-5678-1234-567812345678"
        assert record.filepath == "/path/to/file.tif"
        assert record.filename == "image.tif"
        assert record.format == "GeoTIFF"
        assert record.extent_minx == -120.0
        assert record.acquisition_date == datetime(2024, 6, 15, 10, 30, 0)
        assert record.ingest_date == datetime(2024, 6, 20, 14, 45, 0)
        assert record.band_count == 3

    def test_from_dict_none_acquisition_date(self):
        """from_dict() should handle None acquisition_date."""
        d = {
            "id": "12345678-1234-5678-1234-567812345678",
            "filepath": "/path/to/file.tif",
            "filename": "image.tif",
            "format": "GeoTIFF",
            "acquisition_date": None,
            "ingest_date": "2024-06-20T00:00:00",
            "file_size_bytes": 0,
        }
        record = ImageryRecord.from_dict(d)
        assert record.acquisition_date is None
        assert record.ingest_date == datetime(2024, 6, 20)

    def test_round_trip_with_acquisition_date(self):
        """Serialization round-trip should be lossless with acquisition_date."""
        acq_date = datetime(2024, 6, 15, 10, 30, 0)
        ingest_date = datetime(2024, 6, 20, 14, 45, 0)
        record1 = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=-120.0,
            extent_miny=30.0,
            extent_maxx=-100.0,
            extent_maxy=50.0,
            spatial_ref_wkid=4326,
            acquisition_date=acq_date,
            ingest_date=ingest_date,
            file_size_bytes=1024,
            band_count=3,
            width=512,
            height=512,
        )
        d = record1.to_dict()
        record2 = ImageryRecord.from_dict(d)
        assert record2.id == record1.id
        assert record2.filepath == record1.filepath
        assert record2.filename == record1.filename
        assert record2.format == record1.format
        assert record2.centroid_x == record1.centroid_x
        assert record2.centroid_y == record1.centroid_y
        assert record2.acquisition_date == record1.acquisition_date
        assert record2.ingest_date == record1.ingest_date

    def test_round_trip_without_acquisition_date(self):
        """Serialization round-trip should be lossless without acquisition_date."""
        ingest_date = datetime(2024, 6, 20, 14, 45, 0)
        record1 = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=ingest_date,
            file_size_bytes=1024,
            band_count=None,
            width=None,
            height=None,
        )
        d = record1.to_dict()
        record2 = ImageryRecord.from_dict(d)
        assert record2.acquisition_date is None
        assert record2.ingest_date == record1.ingest_date


class TestDownloadResultSummary:
    """Tests for DownloadResult.summary() string formatting."""

    def test_summary_success_only(self):
        """summary() should report success count when no failures."""
        result = DownloadResult(
            success_count=5,
            failed_count=0,
            dest_path="/Users/test/Desktop/ImageryBrowser_20240620_143000",
            errors=[],
        )
        summary = result.summary()
        assert "Downloaded 5 file(s)" in summary
        assert "/Users/test/Desktop/ImageryBrowser_20240620_143000" in summary
        assert "failed" not in summary.lower()

    def test_summary_with_failures(self):
        """summary() should report failures and error details."""
        result = DownloadResult(
            success_count=3,
            failed_count=2,
            dest_path="/Users/test/Desktop/ImageryBrowser_20240620_143000",
            errors=["file1.tif: Permission denied", "file2.tif: File not found"],
        )
        summary = result.summary()
        assert "Downloaded 3 file(s)" in summary
        assert "2 file(s) failed" in summary
        assert "file1.tif: Permission denied" in summary
        assert "file2.tif: File not found" in summary

    def test_summary_all_failed(self):
        """summary() should report all failures."""
        result = DownloadResult(
            success_count=0,
            failed_count=2,
            dest_path="/Users/test/Desktop/ImageryBrowser_20240620_143000",
            errors=["file1.tif: Error", "file2.tif: Error"],
        )
        summary = result.summary()
        assert "Downloaded 0 file(s)" in summary
        assert "2 file(s) failed" in summary

    def test_summary_truncates_errors_to_five(self):
        """summary() should show at most 5 error lines."""
        errors = [f"file{i}.tif: Error {i}" for i in range(10)]
        result = DownloadResult(
            success_count=0,
            failed_count=10,
            dest_path="/Users/test/Desktop/ImageryBrowser_20240620_143000",
            errors=errors,
        )
        summary = result.summary()
        assert "file0.tif: Error 0" in summary
        assert "file4.tif: Error 4" in summary
        # Files 5-9 should not be shown
        for i in range(5, 10):
            assert f"file{i}.tif" not in summary


class TestImageryScanResult:
    """Tests for ImageryScanResult data structure."""

    def test_default_values(self):
        """ImageryScanResult should have sensible defaults."""
        result = ImageryScanResult()
        assert result.records == []
        assert result.warnings == []
        assert result.processed_count == 0
        assert result.failed_count == 0
        assert isinstance(result.scan_timestamp, datetime)

    def test_with_records_and_warnings(self):
        """ImageryScanResult should accept records and warnings."""
        ingest_date = datetime.now()
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=ingest_date,
            file_size_bytes=0,
            band_count=None,
            width=None,
            height=None,
        )
        result = ImageryScanResult(
            records=[record],
            warnings=["Warning 1"],
            processed_count=1,
            failed_count=0,
        )
        assert len(result.records) == 1
        assert result.records[0] == record
        assert result.warnings == ["Warning 1"]
        assert result.processed_count == 1


class TestImageryRecordNitfFields:
    """Tests for the NITF 2.1 / NTM metadata added to ImageryRecord."""

    def _make(self, **overrides):
        base = dict(
            filepath="/data/NITF001.ntf",
            filename="NITF001.ntf",
            fmt="NITF",
            extent_minx=-117.5, extent_miny=33.0, extent_maxx=-116.0, extent_maxy=34.0,
            spatial_ref_wkid=4326,
            acquisition_date=None,
            ingest_date=datetime(2025, 1, 15),
            file_size_bytes=2048,
            band_count=1, width=2048, height=1024,
        )
        base.update(overrides)
        return ImageryRecord.make(**base)

    def test_nitf_fields_stored(self):
        corners = [(-117.0, 34.0), (-116.0, 34.0), (-116.5, 33.0), (-117.5, 33.0)]
        rec = self._make(
            corners=corners, image_id="TESTIMG001", image_title="scene alpha",
            image_category="VIS", image_source="SENSOR-1",
            file_title="NTM COLLECTION", classification="U", num_image_segments=1,
        )
        assert rec.image_id == "TESTIMG001"
        assert rec.image_category == "VIS"
        assert rec.file_title == "NTM COLLECTION"
        assert rec.classification == "U"
        assert rec.num_image_segments == 1
        # corners normalised to an immutable tuple-of-tuples (hashable record)
        assert rec.corners == tuple(corners)
        assert isinstance(rec.corners, tuple) and isinstance(rec.corners[0], tuple)
        hash(rec)  # frozen dataclass must remain hashable with corners present

    def test_idatim_feeds_acquisition_date_over_filename(self):
        # Filename has no date; NITF IDATIM should populate acquisition_date.
        rec = self._make(image_datetime=datetime(2025, 1, 15, 12, 30, 0))
        assert rec.acquisition_date == datetime(2025, 1, 15, 12, 30, 0)

    def test_explicit_acquisition_date_beats_idatim(self):
        rec = self._make(
            acquisition_date=datetime(2020, 6, 1),
            image_datetime=datetime(2025, 1, 15, 12, 0, 0),
        )
        assert rec.acquisition_date == datetime(2020, 6, 1)

    def test_isorce_fills_sensor_when_filename_has_none(self):
        rec = self._make(image_source="WV03")
        assert rec.sensor_platform == "WV03"

    def test_filename_sensor_beats_isorce(self):
        rec = ImageryRecord.make(
            filepath="/data/WV02_20250115_PAN_scene.ntf",
            filename="WV02_20250115_PAN_scene.ntf",
            fmt="NITF",
            extent_minx=-1.0, extent_miny=-1.0, extent_maxx=1.0, extent_maxy=1.0,
            spatial_ref_wkid=4326, acquisition_date=None,
            ingest_date=datetime(2025, 1, 15), file_size_bytes=10,
            band_count=1, width=10, height=10, image_source="OTHER",
        )
        assert rec.sensor_platform == "WV02"

    def test_roundtrip_serialization_with_corners(self):
        corners = [(-117.0, 34.0), (-116.0, 34.0), (-116.5, 33.0), (-117.5, 33.0)]
        rec = self._make(
            corners=corners, image_id="ID1", image_category="SAR",
            file_title="T", classification="U", num_image_segments=2,
        )
        restored = ImageryRecord.from_dict(rec.to_dict())
        assert restored == rec
        assert restored.corners == tuple(corners)

    def test_from_dict_backwards_compatible_without_new_keys(self):
        """Old manifests (no NITF keys) must still import cleanly."""
        legacy = {
            "id": "abc", "filepath": "/x.tif", "filename": "x.tif", "format": "GeoTIFF",
            "ingest_date": datetime(2025, 1, 1).isoformat(), "file_size_bytes": 1,
        }
        rec = ImageryRecord.from_dict(legacy)
        assert rec.corners is None
        assert rec.image_id is None
        assert rec.num_image_segments is None
