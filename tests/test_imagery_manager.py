"""
Unit tests for imagery_manager.py

Tests cover:
- ImageryManager.search() with various filter combinations
- ImageryManager.search() date range filtering
- ImageryManager.search() sensor/platform filtering
- ImageryManager.search() image type filtering
- ImageryManager.search() scene name search
- ImageryManager.search() size filtering
- ImageryManager.sort_records() by various keys
"""
import pytest
from datetime import datetime, timedelta
from models import ImageryRecord
from imagery_manager import ImageryManager


class TestImageryManagerInit:
    """Tests for ImageryManager initialization."""

    def test_init_empty(self):
        """ImageryManager() should initialize with empty records."""
        manager = ImageryManager()
        assert manager.all_records() == []

    def test_init_with_records(self):
        """ImageryManager() should accept initial records."""
        ingest = datetime.now()
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
            ingest_date=ingest,
            file_size_bytes=1024,
            band_count=None,
            width=None,
            height=None,
        )
        manager = ImageryManager([record])
        assert len(manager.all_records()) == 1
        assert manager.all_records()[0] == record

    def test_load_replaces_records(self):
        """load() should replace existing records."""
        ingest1 = datetime.now()
        ingest2 = datetime.now()
        record1 = ImageryRecord.make(
            filepath="/path/to/file1.tif",
            filename="image1.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=ingest1,
            file_size_bytes=1024,
            band_count=None,
            width=None,
            height=None,
        )
        record2 = ImageryRecord.make(
            filepath="/path/to/file2.tif",
            filename="image2.tif",
            fmt="GeoTIFF",
            extent_minx=None,
            extent_miny=None,
            extent_maxx=None,
            extent_maxy=None,
            spatial_ref_wkid=None,
            acquisition_date=None,
            ingest_date=ingest2,
            file_size_bytes=2048,
            band_count=None,
            width=None,
            height=None,
        )
        manager = ImageryManager([record1])
        manager.load([record2])
        assert len(manager.all_records()) == 1
        assert manager.all_records()[0] == record2

    def test_all_sensor_platforms(self):
        """all_sensor_platforms() should return sorted list of unique sensor/platform values."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/GE01_20231201_MS_INLAND.tif",
                filename="GE01_20231201_MS_INLAND.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=2048, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/W3_20240601_IR_COASTAL.tif",
                filename="W3_20240601_IR_COASTAL.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=3072, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        sensors = manager.all_sensor_platforms()
        assert sensors == ["GE01", "W3"]  # Sorted, unique

    def test_all_image_types(self):
        """all_image_types() should return sorted list of unique image types."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/GE01_20231201_MS_INLAND.tif",
                filename="GE01_20231201_MS_INLAND.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=2048, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/W3_20240601_PAN_COASTAL.tif",
                filename="W3_20240601_PAN_COASTAL.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=3072, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        types = manager.all_image_types()
        assert types == ["MS", "PAN"]  # Sorted, unique

    def test_max_file_size_mb_empty(self):
        """max_file_size_mb() should return 0.0 for empty manager."""
        manager = ImageryManager()
        assert manager.max_file_size_mb() == 0.0

    def test_max_file_size_mb_single_file(self):
        """max_file_size_mb() should return size of single file in MB."""
        ingest = datetime.now()
        record = ImageryRecord.make(
            filepath="/path/to/file.tif",
            filename="image.tif",
            fmt="GeoTIFF",
            extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
            spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
            file_size_bytes=2097152,  # 2 MB
            band_count=None, width=None, height=None,
        )
        manager = ImageryManager([record])
        assert manager.max_file_size_mb() == 2.0

    def test_max_file_size_mb_multiple_files(self):
        """max_file_size_mb() should return size of largest file."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/file1.tif",
                filename="image1.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1048576,  # 1 MB
                band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/file2.tif",
                filename="image2.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=5242880,  # 5 MB
                band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        assert manager.max_file_size_mb() == 5.0


class TestImageryManagerSearch:
    """Tests for ImageryManager.search() filtering."""

    @pytest.fixture
    def sample_records(self):
        """Create a set of sample records for filtering tests."""
        base_ingest = datetime(2024, 6, 20, 12, 0, 0)
        return [
            ImageryRecord.make(
                filepath="/path/to/north1.tif",
                filename="north1.tif",
                fmt="GeoTIFF",
                extent_minx=-120.0, extent_miny=50.0, extent_maxx=-100.0, extent_maxy=70.0,
                spatial_ref_wkid=4326,
                acquisition_date=datetime(2024, 6, 1),
                ingest_date=base_ingest,
                file_size_bytes=1048576,  # 1 MB
                band_count=3, width=512, height=512,
            ),
            ImageryRecord.make(
                filepath="/path/to/south1.tif",
                filename="south1.tif",
                fmt="JPEG2000",
                extent_minx=-120.0, extent_miny=-70.0, extent_maxx=-100.0, extent_maxy=-50.0,
                spatial_ref_wkid=4326,
                acquisition_date=datetime(2024, 5, 1),
                ingest_date=base_ingest - timedelta(days=60),
                file_size_bytes=2097152,  # 2 MB
                band_count=1, width=256, height=256,
            ),
            ImageryRecord.make(
                filepath="/path/to/east1.tif",
                filename="east1.tif",
                fmt="NITF",
                extent_minx=120.0, extent_miny=0.0, extent_maxx=140.0, extent_maxy=20.0,
                spatial_ref_wkid=4326,
                acquisition_date=None,  # No acquisition date
                ingest_date=base_ingest - timedelta(days=15),
                file_size_bytes=512000,  # ~500 KB
                band_count=4, width=1024, height=1024,
            ),
            ImageryRecord.make(
                filepath="/path/to/no_extent.tif",
                filename="no_extent.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None,
                acquisition_date=datetime(2024, 6, 10),
                ingest_date=base_ingest,
                file_size_bytes=524288,  # ~500 KB
                band_count=2, width=512, height=512,
            ),
        ]

    def test_search_no_filters(self, sample_records):
        """search() with no filters should return all records."""
        manager = ImageryManager(sample_records)
        results = manager.search({})
        assert len(results) == 4
        assert results == sample_records

    def test_search_date_range_last_30_days_acquisition(self, sample_records):
        """search() with date_range='Last 30 Days' on acquisition field."""
        now = datetime.now()
        recent_ingest = now
        # Mock recent acquisition date
        manager = ImageryManager(sample_records)
        # Manually set one record to have recent acquisition
        old_records = manager.all_records()
        # north1 has acquisition_date=2024-06-01, which may or may not be in last 30 days
        # depending on current date. Let's test the filtering logic.
        results = manager.search({
            "date_range": "Last 30 Days",
            "date_field": "acquisition",
        })
        # Results should have only records with acquisition_date in last 30 days
        # and exclude records with None acquisition_date
        assert all(r.acquisition_date is not None for r in results)
        assert len(results) <= 3  # east1 has None acquisition_date

    def test_search_date_range_last_30_days_ingest(self, sample_records):
        """search() with date_range='Last 30 Days' on ingest field."""
        # Create records with recent ingest dates to test the filter
        recent_ingest = datetime.now()
        old_ingest = datetime.now() - timedelta(days=60)
        recent_records = [
            ImageryRecord.make(
                filepath="/path/to/recent1.tif",
                filename="recent1.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=recent_ingest,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/old1.tif",
                filename="old1.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=old_ingest,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(recent_records)
        results = manager.search({
            "date_range": "Last 30 Days",
            "date_field": "ingest",
        })
        # Should include only the recent record
        assert len(results) == 1
        assert results[0].filename == "recent1.tif"

    def test_search_date_range_last_90_days(self):
        """search() with date_range='Last 90 Days' should filter by 90-day window."""
        now = datetime.now()
        ingest_recent = now - timedelta(days=60)
        ingest_old = now - timedelta(days=100)
        records = [
            ImageryRecord.make(
                filepath="/path/to/recent.tif",
                filename="recent.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=ingest_recent, ingest_date=ingest_recent,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/old.tif",
                filename="old.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=ingest_old, ingest_date=ingest_old,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.search({
            "date_range": "Last 90 Days",
            "date_field": "acquisition",
        })
        assert len(results) == 1
        assert results[0].filename == "recent.tif"

    def test_search_date_range_last_year(self):
        """search() with date_range='Last Year' should filter by 365-day window."""
        now = datetime.now()
        ingest_recent = now - timedelta(days=200)
        ingest_old = now - timedelta(days=400)
        records = [
            ImageryRecord.make(
                filepath="/path/to/recent.tif",
                filename="recent.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=ingest_recent, ingest_date=ingest_recent,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/old.tif",
                filename="old.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=ingest_old, ingest_date=ingest_old,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.search({
            "date_range": "Last Year",
            "date_field": "acquisition",
        })
        assert len(results) == 1
        assert results[0].filename == "recent.tif"

    def test_search_date_range_custom(self, sample_records):
        """search() with date_range='Custom Range' should use start and end dates."""
        manager = ImageryManager(sample_records)
        start = datetime(2024, 5, 15)
        end = datetime(2024, 6, 15)
        results = manager.search({
            "date_range": "Custom Range",
            "date_field": "acquisition",
            "date_start": start,
            "date_end": end,
        })
        # north1 (2024-06-01) and no_extent (2024-06-10) are in range
        # south1 (2024-05-01) is before start date, excluded
        # east1 has None acquisition_date so excluded
        assert len(results) == 2
        filenames = {r.filename for r in results}
        assert filenames == {"north1.tif", "no_extent.tif"}

    def test_search_date_range_custom_with_end_boundary(self):
        """search() with end date should exclude records after end."""
        now = datetime.now()
        in_range_date = now - timedelta(days=50)
        after_end_date = now - timedelta(days=5)

        records = [
            ImageryRecord.make(
                filepath="/path/to/in_range.tif",
                filename="in_range.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=in_range_date, ingest_date=now,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/after_end.tif",
                filename="after_end.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=after_end_date, ingest_date=now,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        end = now - timedelta(days=10)
        results = manager.search({
            "date_range": "Custom Range",
            "date_field": "acquisition",
            "date_start": now - timedelta(days=100),
            "date_end": end,
        })
        # Only in_range should be included
        assert len(results) == 1
        assert results[0].filename == "in_range.tif"

    def test_search_sensor_filter(self):
        """search() with sensors filter should only return matching sensor/platform records."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1048576, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/GE01_20231201_MS_INLAND.tif",
                filename="GE01_20231201_MS_INLAND.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=2097152, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.search({"sensors": ["W3"]})
        assert len(results) == 1
        assert results[0].sensor_platform == "W3"

    def test_search_sensor_filter_empty_list(self):
        """search() with empty sensors list should return all records."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.search({"sensors": []})
        assert len(results) == 1

    def test_search_image_type_filter(self):
        """search() with image_types filter should return only matching type records."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1048576, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/W3_20240601_MS_COASTAL.tif",
                filename="W3_20240601_MS_COASTAL.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=2097152, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/GE01_20231201_IR_INLAND.tif",
                filename="GE01_20231201_IR_INLAND.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=3145728, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.search({"image_types": ["PAN", "MS"]})
        assert len(results) == 2
        types = {r.image_type for r in results}
        assert types == {"PAN", "MS"}

    def test_search_scene_name_filter(self):
        """search() with scene_search should match scene name substring."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1048576, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/W3_20240601_MS_COASTAL.tif",
                filename="W3_20240601_MS_COASTAL.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=2097152, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.search({"scene_search": "coa"})
        assert len(results) == 1
        assert results[0].scene_name == "COASTAL"

    def test_search_scene_name_filter_case_insensitive(self):
        """scene_search should be case-insensitive."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1024, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        assert len(manager.search({"scene_search": "HARBOR"})) == 1
        assert len(manager.search({"scene_search": "harbor"})) == 1
        assert len(manager.search({"scene_search": "Harbor"})) == 1

    def test_search_size_filter(self, sample_records):
        """search() with min_size_mb should filter by file size."""
        manager = ImageryManager(sample_records)
        results = manager.search({"min_size_mb": 1.0})
        # north1 (1 MB) and south1 (2 MB) meet threshold
        # east1 (~500 KB) and no_extent (~500 KB) excluded
        assert len(results) == 2
        filenames = {r.filename for r in results}
        assert filenames == {"north1.tif", "south1.tif"}

    def test_search_combined_filters(self):
        """search() should apply sensor and size filters in combination."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/W3_20240510_PAN_HARBOR.tif",
                filename="W3_20240510_PAN_HARBOR.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=1048576,  # 1 MB
                band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/W3_20240601_MS_COASTAL.tif",
                filename="W3_20240601_MS_COASTAL.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=524288,  # 0.5 MB — excluded by size
                band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/GE01_20231201_PAN_INLAND.tif",
                filename="GE01_20231201_PAN_INLAND.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=2097152,  # 2 MB — excluded by sensor
                band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.search({"sensors": ["W3"], "min_size_mb": 0.6})
        assert len(results) == 1
        assert results[0].filename == "W3_20240510_PAN_HARBOR.tif"


class TestImageryManagerSort:
    """Tests for ImageryManager.sort_records() sorting."""

    @pytest.fixture
    def sample_records(self):
        """Create sample records for sorting tests."""
        base_ingest = datetime(2024, 6, 20)
        return [
            ImageryRecord.make(
                filepath="/path/to/charlie.tif",
                filename="charlie.tif",
                fmt="GeoTIFF",
                extent_minx=-100.0, extent_miny=0.0, extent_maxx=-80.0, extent_maxy=20.0,
                spatial_ref_wkid=4326,
                acquisition_date=datetime(2024, 6, 15),
                ingest_date=base_ingest + timedelta(days=2),
                file_size_bytes=3145728,  # 3 MB
                band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/alice.tif",
                filename="alice.tif",
                fmt="GeoTIFF",
                extent_minx=-120.0, extent_miny=40.0, extent_maxx=-100.0, extent_maxy=60.0,
                spatial_ref_wkid=4326,
                acquisition_date=datetime(2024, 6, 10),
                ingest_date=base_ingest,
                file_size_bytes=1048576,  # 1 MB
                band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/bob.tif",
                filename="bob.tif",
                fmt="JPEG2000",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None,
                acquisition_date=None,  # None acquisition date
                ingest_date=base_ingest + timedelta(days=5),
                file_size_bytes=2097152,  # 2 MB
                band_count=None, width=None, height=None,
            ),
        ]

    def test_sort_by_filename_ascending(self, sample_records):
        """sort_records() by filename should sort alphabetically ascending."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "filename", reverse=False)
        filenames = [r.filename for r in results]
        assert filenames == ["alice.tif", "bob.tif", "charlie.tif"]

    def test_sort_by_filename_descending(self, sample_records):
        """sort_records() by filename should sort alphabetically descending."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "filename", reverse=True)
        filenames = [r.filename for r in results]
        assert filenames == ["charlie.tif", "bob.tif", "alice.tif"]

    def test_sort_by_filename_case_insensitive(self):
        """sort_records() by filename should be case-insensitive."""
        ingest = datetime.now()
        records = [
            ImageryRecord.make(
                filepath="/path/to/ZEBRA.tif",
                filename="ZEBRA.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=0, band_count=None, width=None, height=None,
            ),
            ImageryRecord.make(
                filepath="/path/to/apple.tif",
                filename="apple.tif",
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None, acquisition_date=None, ingest_date=ingest,
                file_size_bytes=0, band_count=None, width=None, height=None,
            ),
        ]
        manager = ImageryManager(records)
        results = manager.sort_records(records, "filename", reverse=False)
        filenames = [r.filename for r in results]
        assert filenames == ["apple.tif", "ZEBRA.tif"]

    def test_sort_by_file_size(self, sample_records):
        """sort_records() by file_size should sort numerically."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "file_size", reverse=False)
        sizes = [r.file_size_bytes for r in results]
        assert sizes == [1048576, 2097152, 3145728]

    def test_sort_by_file_size_descending(self, sample_records):
        """sort_records() by file_size descending should sort largest first."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "file_size", reverse=True)
        sizes = [r.file_size_bytes for r in results]
        assert sizes == [3145728, 2097152, 1048576]

    def test_sort_by_acquisition_date(self, sample_records):
        """sort_records() by acquisition_date should sort chronologically."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "acquisition_date", reverse=False)
        filenames = [r.filename for r in results]
        # alice (2024-06-10), charlie (2024-06-15), bob (None)
        # None values sort to beginning when using datetime.min
        assert filenames[0] == "bob.tif"  # None acquisition_date
        assert filenames[1] == "alice.tif"  # 2024-06-10
        assert filenames[2] == "charlie.tif"  # 2024-06-15

    def test_sort_by_acquisition_date_none_at_beginning(self, sample_records):
        """sort_records() by acquisition_date should put None dates at beginning (datetime.min)."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "acquisition_date", reverse=False)
        # None dates map to datetime.min and sort to the beginning
        assert results[0].acquisition_date is None

    def test_sort_by_ingest_date(self, sample_records):
        """sort_records() by ingest_date should sort chronologically."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "ingest_date", reverse=False)
        # alice (base), charlie (base+2), bob (base+5)
        assert results[0].filename == "alice.tif"
        assert results[1].filename == "charlie.tif"
        assert results[2].filename == "bob.tif"

    def test_sort_by_location_x(self, sample_records):
        """sort_records() by location_x should sort by centroid_x."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "location_x", reverse=False)
        # alice (centroid_x=-110), charlie (centroid_x=-90), bob (None->inf)
        assert results[0].filename == "alice.tif"
        assert results[1].filename == "charlie.tif"
        assert results[2].filename == "bob.tif"  # None sorts to end

    def test_sort_by_location_y(self, sample_records):
        """sort_records() by location_y should sort by centroid_y."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "location_y", reverse=False)
        # charlie (centroid_y=10), alice (centroid_y=50), bob (None->inf)
        assert results[0].filename == "charlie.tif"
        assert results[1].filename == "alice.tif"
        assert results[2].filename == "bob.tif"  # None sorts to end

    def test_sort_unknown_key_defaults_to_filename(self, sample_records):
        """sort_records() with unknown key should default to filename sort."""
        manager = ImageryManager(sample_records)
        results = manager.sort_records(sample_records, "unknown_key", reverse=False)
        filenames = [r.filename for r in results]
        assert filenames == ["alice.tif", "bob.tif", "charlie.tif"]


class TestImageryManagerSearchCombinations:
    """Filter combination matrix tests for ImageryManager.search().

    All records use the sensor_date_type_scene filename convention so that
    sensor_platform, image_type, and scene_name fields are populated.

    Dataset:
        W3_20240510_PAN_HARBOR   sensor=W3,   type=PAN, scene=HARBOR, acq=2024-05-10, 3 MB
        W3_20240601_MS_COASTAL     sensor=W3,   type=MS,  scene=COASTAL,  acq=2024-06-01, 1 MB
        GE01_20231201_PAN_INLAND    sensor=GE01, type=PAN, scene=INLAND,    acq=2023-12-01, 5 MB
        GE01_20240315_IR_INLAND     sensor=GE01, type=IR,  scene=INLAND,    acq=2024-03-15, 2 MB
        PHR_20240701_MS_OSAKA      sensor=PHR,  type=MS,  scene=OSAKA,    acq=2024-07-01, 0.5 MB
    """

    @pytest.fixture
    def combo_records(self):
        ingest = datetime(2024, 8, 1, 0, 0, 0)
        specs = [
            ("W3_20240510_PAN_HARBOR.tif",  datetime(2024, 5, 10), 3145728),
            ("W3_20240601_MS_COASTAL.tif",    datetime(2024, 6,  1), 1048576),
            ("GE01_20231201_PAN_INLAND.tif",   datetime(2023, 12, 1), 5242880),
            ("GE01_20240315_IR_INLAND.tif",    datetime(2024, 3, 15), 2097152),
            ("PHR_20240701_MS_OSAKA.tif",     datetime(2024, 7,  1),  524288),
        ]
        return [
            ImageryRecord.make(
                filepath=f"/path/to/{fn}",
                filename=fn,
                fmt="GeoTIFF",
                extent_minx=None, extent_miny=None, extent_maxx=None, extent_maxy=None,
                spatial_ref_wkid=None,
                acquisition_date=acq,
                ingest_date=ingest,
                file_size_bytes=size,
                band_count=None, width=None, height=None,
            )
            for fn, acq, size in specs
        ]

    # -- two-filter combinations --

    def test_sensor_and_image_type(self, combo_records):
        """sensor=W3 AND type=PAN → only W3_PAN_HARBOR."""
        manager = ImageryManager(combo_records)
        results = manager.search({"sensors": ["W3"], "image_types": ["PAN"]})
        assert len(results) == 1
        assert results[0].sensor_platform == "W3"
        assert results[0].image_type == "PAN"

    def test_sensor_and_custom_date_range(self, combo_records):
        """sensor=GE01 AND acquisition in 2024 → only GE01_IR_INLAND (2024-03-15).

        GE01_PAN_INLAND is dated 2023-12-01, which is before the start date.
        """
        manager = ImageryManager(combo_records)
        results = manager.search({
            "sensors": ["GE01"],
            "date_range": "Custom Range",
            "date_field": "acquisition",
            "date_start": datetime(2024, 1, 1),
            "date_end": datetime(2024, 12, 31),
        })
        assert len(results) == 1
        assert results[0].filename == "GE01_20240315_IR_INLAND.tif"

    def test_image_type_and_min_size(self, combo_records):
        """type=PAN AND size>=4 MB → only GE01_PAN_INLAND (5 MB); W3_PAN_HARBOR is 3 MB."""
        manager = ImageryManager(combo_records)
        results = manager.search({"image_types": ["PAN"], "min_size_mb": 4.0})
        assert len(results) == 1
        assert results[0].filename == "GE01_20231201_PAN_INLAND.tif"

    def test_image_type_and_scene_search(self, combo_records):
        """type=MS AND scene contains 'osa' → only PHR_MS_OSAKA ('OSA' is in 'OSAKA')."""
        manager = ImageryManager(combo_records)
        results = manager.search({"image_types": ["MS"], "scene_search": "osa"})
        assert len(results) == 1
        assert results[0].filename == "PHR_20240701_MS_OSAKA.tif"

    # -- three-filter combinations --

    def test_sensor_type_and_date_range_triple(self, combo_records):
        """sensor=W3, type=MS, acquisition in 2024 → only W3_MS_COASTAL."""
        manager = ImageryManager(combo_records)
        results = manager.search({
            "sensors": ["W3"],
            "image_types": ["MS"],
            "date_range": "Custom Range",
            "date_field": "acquisition",
            "date_start": datetime(2024, 1, 1),
            "date_end": datetime(2024, 12, 31),
        })
        assert len(results) == 1
        assert results[0].filename == "W3_20240601_MS_COASTAL.tif"

    def test_type_scene_and_size_triple(self, combo_records):
        """type in [PAN, IR], scene='INLAND', size>=3 MB → only GE01_PAN_INLAND (5 MB).

        GE01_IR_INLAND (2 MB) is excluded by the size threshold.
        """
        manager = ImageryManager(combo_records)
        results = manager.search({
            "image_types": ["PAN", "IR"],
            "scene_search": "INLAND",
            "min_size_mb": 3.0,
        })
        assert len(results) == 1
        assert results[0].filename == "GE01_20231201_PAN_INLAND.tif"

    # -- no-match / empty-result scenario --

    def test_no_records_match_all_filters_out(self, combo_records):
        """sensor=W3 AND type=IR: W3 only has PAN and MS, so result is empty."""
        manager = ImageryManager(combo_records)
        results = manager.search({"sensors": ["W3"], "image_types": ["IR"]})
        assert results == []

    def test_unrecognised_sensor_returns_empty(self, combo_records):
        """Filtering on a sensor not present in the dataset returns no records."""
        manager = ImageryManager(combo_records)
        results = manager.search({"sensors": ["SENTINEL"]})
        assert results == []


class TestCategoryFilterAndSort:
    """Tests for the NITF image-category (ICAT) filter and new sort keys."""

    def _rec(self, *, category=None, image_id=None, name="scene"):
        return ImageryRecord.make(
            filepath=f"/d/{name}.ntf", filename=f"{name}.ntf", fmt="NITF",
            extent_minx=0.0, extent_miny=0.0, extent_maxx=1.0, extent_maxy=1.0,
            spatial_ref_wkid=4326, acquisition_date=datetime(2025, 1, 1),
            ingest_date=datetime(2025, 1, 1), file_size_bytes=10,
            band_count=1, width=10, height=10,
            image_category=category, image_id=image_id,
        )

    def test_all_image_categories_sorted_unique(self):
        mgr = ImageryManager([
            self._rec(category="SAR"), self._rec(category="VIS"),
            self._rec(category="VIS"), self._rec(category=None),
        ])
        assert mgr.all_image_categories() == ["SAR", "VIS"]

    def test_filter_by_category(self):
        mgr = ImageryManager([
            self._rec(category="SAR", name="a"),
            self._rec(category="VIS", name="b"),
            self._rec(category="IR", name="c"),
        ])
        out = mgr.search({"categories": ["SAR", "IR"]})
        assert {r.image_category for r in out} == {"SAR", "IR"}

    def test_empty_categories_returns_all(self):
        mgr = ImageryManager([self._rec(category="SAR"), self._rec(category="VIS")])
        assert len(mgr.search({"categories": []})) == 2
        assert len(mgr.search({})) == 2

    def test_sort_by_category_and_image_id(self):
        recs = [
            self._rec(category="VIS", image_id="B2", name="a"),
            self._rec(category="IR", image_id="A1", name="b"),
            self._rec(category="SAR", image_id="C3", name="c"),
        ]
        mgr = ImageryManager(recs)
        by_cat = mgr.sort_records(recs, "image_category")
        assert [r.image_category for r in by_cat] == ["IR", "SAR", "VIS"]
        by_id = mgr.sort_records(recs, "image_id")
        assert [r.image_id for r in by_id] == ["A1", "B2", "C3"]
