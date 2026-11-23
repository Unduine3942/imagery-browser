"""
Unit tests for scanner.py

Tests cover:
- scan_imagery_folder() with various path conditions
- scan_imagery_folder() recursive behavior
- scan_imagery_folder() file filtering
- scan_imagery_folder() error handling with arcpy
- _build_record() with fallback when arcpy unavailable
"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Mock arcpy before importing scanner
sys.modules['arcpy'] = MagicMock()

from scanner import (
    scan_imagery_folder, _build_record, _ext_to_format, _parse_arcpy_date,
    _try_rasterio_metadata, _try_gdal_metadata, _geo_from_nitf,
)


class TestArcpyImport:
    """Tests for arcpy import fallback behavior."""

    def test_arcpy_mock_available(self):
        """Verify arcpy is mocked in test environment."""
        import scanner
        # arcpy should be mocked at module level
        assert hasattr(scanner, 'arcpy')


class TestScanImageryFolder:
    """Tests for scan_imagery_folder() main function."""

    def test_scan_nonexistent_path(self):
        """scan_imagery_folder() should return empty result for non-existent path."""
        result = scan_imagery_folder("/nonexistent/path")
        assert result.records == []
        assert result.processed_count == 0
        assert result.failed_count == 0
        assert len(result.warnings) == 1
        assert "not found" in result.warnings[0].lower()

    def test_scan_file_not_directory(self):
        """scan_imagery_folder() should return empty result if path is a file."""
        with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
            result = scan_imagery_folder(tmp.name)
            assert result.records == []
            assert result.processed_count == 0
            assert len(result.warnings) == 1
            assert "not a directory" in result.warnings[0].lower()

    def test_scan_finds_imagery_files(self):
        """scan_imagery_folder() should find only imagery files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create imagery files
            (Path(tmpdir) / "image1.tif").touch()
            (Path(tmpdir) / "image2.jp2").touch()
            (Path(tmpdir) / "image3.tiff").touch()

            # Create non-imagery files
            (Path(tmpdir) / "readme.txt").touch()
            (Path(tmpdir) / "script.py").touch()
            (Path(tmpdir) / "data.pdf").touch()

            result = scan_imagery_folder(tmpdir, recursive=False)
            assert result.processed_count == 3
            assert len(result.records) == 3
            filenames = {r.filename for r in result.records}
            assert filenames == {"image1.tif", "image2.jp2", "image3.tiff"}

    def test_scan_recursive_true(self):
        """scan_imagery_folder() with recursive=True should descend into subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Create files in root
            (root / "image1.tif").touch()
            # Create subdirectory with imagery files
            subdir = root / "subdir"
            subdir.mkdir()
            (subdir / "image2.tif").touch()
            (subdir / "image3.jp2").touch()
            # Create nested subdirectory
            nested = subdir / "nested"
            nested.mkdir()
            (nested / "image4.tiff").touch()

            result = scan_imagery_folder(tmpdir, recursive=True)
            assert result.processed_count == 4
            filenames = {r.filename for r in result.records}
            assert filenames == {"image1.tif", "image2.tif", "image3.jp2", "image4.tiff"}

    def test_scan_recursive_false(self):
        """scan_imagery_folder() with recursive=False should NOT descend into subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Create files in root
            (root / "image1.tif").touch()
            (root / "image2.jp2").touch()
            # Create subdirectory with imagery files (should be ignored)
            subdir = root / "subdir"
            subdir.mkdir()
            (subdir / "image3.tif").touch()

            result = scan_imagery_folder(tmpdir, recursive=False)
            assert result.processed_count == 2
            filenames = {r.filename for r in result.records}
            assert filenames == {"image1.tif", "image2.jp2"}

    def test_scan_handles_permission_error_gracefully(self):
        """scan_imagery_folder() should gracefully handle PermissionError on file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Create a valid file
            (root / "image1.tif").touch()
            # Create another file that we'll mock to fail
            (root / "problem.tif").touch()

            with patch("os.stat") as mock_stat:
                # First call succeeds, second call fails
                mock_stat.side_effect = [
                    MagicMock(st_size=1024, st_ctime=1234567890),
                    PermissionError("Access denied"),
                ]
                result = scan_imagery_folder(tmpdir, recursive=False)
                assert result.processed_count == 1
                assert result.failed_count == 1
                assert len(result.warnings) == 1
                assert "Cannot stat" in result.warnings[0]

    def test_scan_arcpy_describe_exception_uses_fallback(self):
        """scan_imagery_folder() should use fallback when arcpy.Describe raises Exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "image.tif").touch()

            # Mock arcpy.Describe to raise an exception
            import scanner
            original_arcpy = scanner.arcpy
            mock_arcpy = MagicMock()
            mock_arcpy.Describe.side_effect = RuntimeError("arcpy error")
            scanner.arcpy = mock_arcpy
            scanner._ARCPY_AVAILABLE = True

            try:
                result = scan_imagery_folder(tmpdir, recursive=False)
                assert result.processed_count == 1
                # Record should still be created with fallback format
                assert len(result.records) == 1
                assert result.records[0].format == "GeoTIFF"  # .tif -> GeoTIFF
                assert len(result.warnings) == 1
                assert "arcpy.Describe failed" in result.warnings[0]
            finally:
                scanner.arcpy = original_arcpy

    def test_scan_result_has_timestamp(self):
        """scan_imagery_folder() should set scan_timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "image.tif").touch()
            before = datetime.now()
            result = scan_imagery_folder(tmpdir, recursive=False)
            after = datetime.now()
            assert before <= result.scan_timestamp <= after


class TestBuildRecord:
    """Tests for _build_record() internal function."""

    def test_build_record_basic_attributes(self):
        """_build_record() should extract basic file attributes."""
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"test data" * 1000)  # ~9KB

        try:
            import scanner
            # Disable arcpy to use fallback format detection
            original_arcpy = scanner._ARCPY_AVAILABLE
            scanner._ARCPY_AVAILABLE = False

            try:
                warnings = []
                record = _build_record(tmp_path, warnings)
                assert record is not None
                assert record.filename == tmp_path.name
                assert record.format == "GeoTIFF"  # .tif
                assert record.file_size_bytes > 0
                assert record.ingest_date is not None
                assert len(warnings) == 0
            finally:
                scanner._ARCPY_AVAILABLE = original_arcpy
        finally:
            tmp_path.unlink()

    def test_build_record_returns_none_on_stat_error(self):
        """_build_record() should return None if os.stat fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "image.tif"
            tmp_path.touch()

            with patch("os.stat", side_effect=OSError("Permission denied")):
                warnings = []
                record = _build_record(tmp_path, warnings)
                assert record is None
                assert len(warnings) == 1
                assert "Cannot stat" in warnings[0]

    def test_build_record_arcpy_format_mapping(self):
        """_build_record() should use ARCPY_FORMAT_MAP when arcpy available."""
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            import scanner
            original_arcpy = scanner.arcpy
            mock_arcpy = MagicMock()

            # Mock Describe to return format info
            mock_desc = MagicMock()
            mock_desc.format = "TIFF"
            mock_desc.extent = None
            mock_desc.spatialReference = None
            mock_desc.acquisitionDate = None
            mock_desc.bandCount = None
            mock_desc.width = None
            mock_desc.height = None

            mock_arcpy.Describe.return_value = mock_desc
            scanner.arcpy = mock_arcpy
            scanner._ARCPY_AVAILABLE = True

            try:
                warnings = []
                record = _build_record(tmp_path, warnings)
                assert record is not None
                assert record.format == "GeoTIFF"  # ARCPY_FORMAT_MAP["TIFF"]
            finally:
                scanner.arcpy = original_arcpy
        finally:
            tmp_path.unlink()

    def test_build_record_arcpy_extent(self):
        """_build_record() should extract extent from arcpy.Describe."""
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            import scanner
            original_arcpy = scanner.arcpy
            mock_arcpy = MagicMock()

            # Mock Describe with extent
            mock_desc = MagicMock()
            mock_desc.format = "TIFF"
            mock_extent = MagicMock()
            mock_extent.XMin = -120.0
            mock_extent.YMin = 30.0
            mock_extent.XMax = -100.0
            mock_extent.YMax = 50.0
            mock_desc.extent = mock_extent
            mock_desc.spatialReference = None
            mock_desc.acquisitionDate = None
            mock_desc.bandCount = None
            mock_desc.width = None
            mock_desc.height = None

            mock_arcpy.Describe.return_value = mock_desc
            scanner.arcpy = mock_arcpy
            scanner._ARCPY_AVAILABLE = True

            try:
                warnings = []
                record = _build_record(tmp_path, warnings)
                assert record is not None
                assert record.extent_minx == -120.0
                assert record.extent_miny == 30.0
                assert record.extent_maxx == -100.0
                assert record.extent_maxy == 50.0
                assert record.centroid_x == -110.0
                assert record.centroid_y == 40.0
            finally:
                scanner.arcpy = original_arcpy
        finally:
            tmp_path.unlink()

    def test_build_record_arcpy_spatial_reference(self):
        """_build_record() should extract spatial reference WKID from arcpy."""
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            import scanner
            original_arcpy = scanner.arcpy
            mock_arcpy = MagicMock()

            # Mock Describe with spatial reference
            mock_desc = MagicMock()
            mock_desc.format = "TIFF"
            mock_desc.extent = None
            mock_sr = MagicMock()
            mock_sr.factoryCode = 4326
            mock_desc.spatialReference = mock_sr
            mock_desc.acquisitionDate = None
            mock_desc.bandCount = None
            mock_desc.width = None
            mock_desc.height = None

            mock_arcpy.Describe.return_value = mock_desc
            scanner.arcpy = mock_arcpy
            scanner._ARCPY_AVAILABLE = True

            try:
                warnings = []
                record = _build_record(tmp_path, warnings)
                assert record is not None
                assert record.spatial_ref_wkid == 4326
            finally:
                scanner.arcpy = original_arcpy
        finally:
            tmp_path.unlink()

    def test_build_record_arcpy_raster_properties(self):
        """_build_record() should extract band count, width, height from arcpy."""
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            import scanner
            original_arcpy = scanner.arcpy
            mock_arcpy = MagicMock()

            # Mock Describe with raster properties
            mock_desc = MagicMock()
            mock_desc.format = "TIFF"
            mock_desc.extent = None
            mock_desc.spatialReference = None
            mock_desc.acquisitionDate = None
            mock_desc.bandCount = 3
            mock_desc.width = 1024
            mock_desc.height = 2048

            mock_arcpy.Describe.return_value = mock_desc
            scanner.arcpy = mock_arcpy
            scanner._ARCPY_AVAILABLE = True

            try:
                warnings = []
                record = _build_record(tmp_path, warnings)
                assert record is not None
                assert record.band_count == 3
                assert record.width == 1024
                assert record.height == 2048
            finally:
                scanner.arcpy = original_arcpy
        finally:
            tmp_path.unlink()


class TestExtToFormat:
    """Tests for _ext_to_format() suffix-to-format mapping."""

    def test_ext_to_format_tif(self):
        """_ext_to_format() should map .tif to GeoTIFF."""
        assert _ext_to_format(".tif") == "GeoTIFF"
        assert _ext_to_format(".TIF") == "GeoTIFF"

    def test_ext_to_format_tiff(self):
        """_ext_to_format() should map .tiff to GeoTIFF."""
        assert _ext_to_format(".tiff") == "GeoTIFF"
        assert _ext_to_format(".TIFF") == "GeoTIFF"

    def test_ext_to_format_nitf(self):
        """_ext_to_format() should map .nitf and .ntf to NITF."""
        assert _ext_to_format(".nitf") == "NITF"
        assert _ext_to_format(".ntf") == "NITF"

    def test_ext_to_format_jpeg2000(self):
        """_ext_to_format() should map JP2 variants to JPEG2000."""
        assert _ext_to_format(".jp2") == "JPEG2000"
        assert _ext_to_format(".j2k") == "JPEG2000"
        assert _ext_to_format(".j2c") == "JPEG2000"

    def test_ext_to_format_sid(self):
        """_ext_to_format() should map .sid to SID."""
        assert _ext_to_format(".sid") == "SID"

    def test_ext_to_format_ecw(self):
        """_ext_to_format() should map .ecw to ECW."""
        assert _ext_to_format(".ecw") == "ECW"

    def test_ext_to_format_img(self):
        """_ext_to_format() should map IMG variants to IMG."""
        assert _ext_to_format(".img") == "IMG"
        assert _ext_to_format(".ers") == "IMG"

    def test_ext_to_format_unknown(self):
        """_ext_to_format() should return Unknown for unmapped extensions."""
        assert _ext_to_format(".xyz") == "Unknown"
        assert _ext_to_format(".txt") == "Unknown"
        assert _ext_to_format("") == "Unknown"


class TestParseArcpyDate:
    """Tests for _parse_arcpy_date() date parsing."""

    def test_parse_datetime_object(self):
        """_parse_arcpy_date() should accept datetime objects."""
        dt = datetime(2024, 6, 15, 10, 30, 0)
        result = _parse_arcpy_date(dt)
        assert result == dt

    def test_parse_date_format_colon_separated(self):
        """_parse_arcpy_date() should parse YYYY:MM:DD HH:MM:SS format."""
        result = _parse_arcpy_date("2024:06:15 10:30:00")
        assert result == datetime(2024, 6, 15, 10, 30, 0)

    def test_parse_date_format_iso_with_t(self):
        """_parse_arcpy_date() should parse ISO format with T separator."""
        result = _parse_arcpy_date("2024-06-15T10:30:00")
        assert result == datetime(2024, 6, 15, 10, 30, 0)

    def test_parse_date_format_dash_separated(self):
        """_parse_arcpy_date() should parse YYYY-MM-DD HH:MM:SS format."""
        result = _parse_arcpy_date("2024-06-15 10:30:00")
        assert result == datetime(2024, 6, 15, 10, 30, 0)

    def test_parse_date_format_yyyymmdd(self):
        """_parse_arcpy_date() should parse YYYYMMDD format."""
        result = _parse_arcpy_date("20240615")
        assert result == datetime(2024, 6, 15)

    def test_parse_date_format_yyyy_mm_dd(self):
        """_parse_arcpy_date() should parse YYYY-MM-DD format."""
        result = _parse_arcpy_date("2024-06-15")
        assert result == datetime(2024, 6, 15)

    def test_parse_invalid_date_string(self):
        """_parse_arcpy_date() should return None for invalid date strings."""
        result = _parse_arcpy_date("invalid")
        assert result is None

    def test_parse_empty_string(self):
        """_parse_arcpy_date() should return None for empty strings."""
        result = _parse_arcpy_date("")
        assert result is None

    def test_parse_whitespace_only(self):
        """_parse_arcpy_date() should return None for whitespace-only strings."""
        result = _parse_arcpy_date("   ")
        assert result is None

    def test_parse_non_string_non_datetime(self):
        """_parse_arcpy_date() should return None for non-string, non-datetime values."""
        result = _parse_arcpy_date(12345)
        assert result is None

    def test_parse_date_with_whitespace(self):
        """_parse_arcpy_date() should handle dates with leading/trailing whitespace."""
        result = _parse_arcpy_date("  2024-06-15T10:30:00  ")
        assert result == datetime(2024, 6, 15, 10, 30, 0)


class TestTryRasterioMetadata:
    """Tests for _try_rasterio_metadata() fallback extractor."""

    def test_returns_metadata_when_crs_present(self):
        """Should return _GeoMetadata when rasterio opens file with valid CRS."""
        import scanner
        mock_crs = MagicMock()
        mock_crs.to_epsg.return_value = 4326
        mock_src = MagicMock()
        mock_src.crs = mock_crs
        mock_src.bounds = MagicMock(left=-120.0, bottom=30.0, right=-100.0, top=50.0)
        mock_src.count = 3
        mock_src.width = 512
        mock_src.height = 256
        mock_src.__enter__ = MagicMock(return_value=mock_src)
        mock_src.__exit__ = MagicMock(return_value=False)

        with patch.object(scanner, '_RASTERIO_AVAILABLE', True), \
             patch.object(scanner, '_rasterio') as mock_rio, \
             patch.object(scanner, '_RasterioCRS', MagicMock(), create=True), \
             patch.object(scanner, '_rasterio_transform_bounds', return_value=(-120.0, 30.0, -100.0, 50.0), create=True):
            mock_rio.open.return_value = mock_src
            result = _try_rasterio_metadata(Path("test.ntf"))

        assert result is not None
        assert result.extent_minx == -120.0
        assert result.extent_miny == 30.0
        assert result.extent_maxx == -100.0
        assert result.extent_maxy == 50.0
        assert result.spatial_ref_wkid == 4326
        assert result.band_count == 3
        assert result.width == 512
        assert result.height == 256

    def test_returns_none_when_crs_is_none(self):
        """Should return None when rasterio source has no CRS."""
        import scanner
        mock_src = MagicMock()
        mock_src.crs = None
        mock_src.__enter__ = MagicMock(return_value=mock_src)
        mock_src.__exit__ = MagicMock(return_value=False)

        with patch.object(scanner, '_RASTERIO_AVAILABLE', True), \
             patch.object(scanner, '_rasterio') as mock_rio:
            mock_rio.open.return_value = mock_src
            result = _try_rasterio_metadata(Path("test.ntf"))

        assert result is None

    def test_returns_none_when_bounds_invalid(self):
        """Should return None when transformed bounds produce zero-area bbox."""
        import scanner
        mock_crs = MagicMock()
        mock_src = MagicMock()
        mock_src.crs = mock_crs
        mock_src.__enter__ = MagicMock(return_value=mock_src)
        mock_src.__exit__ = MagicMock(return_value=False)

        with patch.object(scanner, '_RASTERIO_AVAILABLE', True), \
             patch.object(scanner, '_rasterio') as mock_rio, \
             patch.object(scanner, '_RasterioCRS', MagicMock(), create=True), \
             patch.object(scanner, '_rasterio_transform_bounds', return_value=(-100.0, 50.0, -100.0, 50.0), create=True):
            mock_rio.open.return_value = mock_src
            result = _try_rasterio_metadata(Path("test.ntf"))

        assert result is None

    def test_returns_none_when_rasterio_raises(self):
        """Should return None and log debug when rasterio raises any exception."""
        import scanner

        with patch.object(scanner, '_RASTERIO_AVAILABLE', True), \
             patch.object(scanner, '_rasterio') as mock_rio:
            mock_rio.open.side_effect = Exception("cannot open file")
            result = _try_rasterio_metadata(Path("test.ntf"))

        assert result is None

    def test_returns_none_when_rasterio_unavailable(self):
        """Should return None immediately when rasterio is not installed."""
        import scanner
        with patch.object(scanner, '_RASTERIO_AVAILABLE', False):
            result = _try_rasterio_metadata(Path("test.ntf"))
        assert result is None


class TestTryGDALMetadata:
    """Tests for _try_gdal_metadata() fallback extractor."""

    def _make_mock_ds(self, gt, w, h, projection):
        """Build a mock GDAL dataset."""
        ds = MagicMock()
        ds.GetGeoTransform.return_value = gt
        ds.RasterXSize = w
        ds.RasterYSize = h
        ds.GetProjection.return_value = projection
        ds.RasterCount = 1
        return ds

    def test_returns_metadata_for_valid_geotransform(self):
        """Should return _GeoMetadata for valid GT + WKT projection."""
        import scanner
        gt = (-120.0, 0.02, 0.0, 50.0, 0.0, -0.02)
        ds = self._make_mock_ds(gt, 1000, 1000, "GEOGCS[...]")

        mock_src_srs = MagicMock()
        mock_src_srs.GetAuthorityCode.return_value = "4326"
        mock_wgs84 = MagicMock()
        mock_ct = MagicMock()
        mock_ct.TransformPoint.side_effect = [
            (-120.0, 30.0, 0.0),
            (-100.0, 50.0, 0.0),
        ]

        with patch.object(scanner, '_GDAL_AVAILABLE', True), \
             patch.object(scanner, '_gdal') as mock_gdal, \
             patch.object(scanner, '_osr') as mock_osr:
            mock_gdal.Open.return_value = ds
            mock_gdal.GA_ReadOnly = 0
            mock_osr.SpatialReference.side_effect = [mock_src_srs, mock_wgs84]
            mock_osr.CoordinateTransformation.return_value = mock_ct
            mock_osr.OAMS_TRADITIONAL_GIS_ORDER = 1
            result = _try_gdal_metadata(Path("test.r0"))

        assert result is not None
        assert result.extent_minx == -120.0
        assert result.extent_miny == 30.0
        assert result.extent_maxx == -100.0
        assert result.extent_maxy == 50.0
        assert result.spatial_ref_wkid == 4326

    def test_returns_none_when_gdal_open_returns_none(self):
        """Should return None when gdal.Open cannot open the file."""
        import scanner
        with patch.object(scanner, '_GDAL_AVAILABLE', True), \
             patch.object(scanner, '_gdal') as mock_gdal:
            mock_gdal.Open.return_value = None
            mock_gdal.GA_ReadOnly = 0
            result = _try_gdal_metadata(Path("test.r0"))
        assert result is None

    def test_returns_none_when_no_projection(self):
        """Should return None when dataset has no projection WKT."""
        import scanner
        gt = (-120.0, 0.02, 0.0, 50.0, 0.0, -0.02)
        ds = self._make_mock_ds(gt, 1000, 1000, "")

        with patch.object(scanner, '_GDAL_AVAILABLE', True), \
             patch.object(scanner, '_gdal') as mock_gdal:
            mock_gdal.Open.return_value = ds
            mock_gdal.GA_ReadOnly = 0
            result = _try_gdal_metadata(Path("test.r0"))
        assert result is None

    def test_returns_none_when_geotransform_zero_area(self):
        """Should return None when geotransform produces zero-area native bbox."""
        import scanner
        gt = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ds = self._make_mock_ds(gt, 0, 0, "GEOGCS[...]")

        with patch.object(scanner, '_GDAL_AVAILABLE', True), \
             patch.object(scanner, '_gdal') as mock_gdal:
            mock_gdal.Open.return_value = ds
            mock_gdal.GA_ReadOnly = 0
            result = _try_gdal_metadata(Path("test.r0"))
        assert result is None

    def test_returns_none_when_gdal_unavailable(self):
        """Should return None immediately when GDAL is not installed."""
        import scanner
        with patch.object(scanner, '_GDAL_AVAILABLE', False):
            result = _try_gdal_metadata(Path("test.r0"))
        assert result is None


class TestBuildRecordGeoFallback:
    """Tests for geo-fallback wiring in _build_record()."""

    def _make_geo_meta(self, minx=-120.0, miny=30.0, maxx=-100.0, maxy=50.0):
        from scanner import _GeoMetadata
        return _GeoMetadata(
            extent_minx=minx, extent_miny=miny,
            extent_maxx=maxx, extent_maxy=maxy,
            spatial_ref_wkid=4326, band_count=1, width=512, height=512,
        )

    def test_ntf_extent_populated_via_rasterio(self):
        """NITF file with no arcpy should get extent from rasterio fallback."""
        with tempfile.NamedTemporaryFile(suffix=".ntf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            import scanner
            meta = self._make_geo_meta()
            with patch.object(scanner, '_ARCPY_AVAILABLE', False), \
                 patch.object(scanner, '_try_rasterio_metadata', return_value=meta), \
                 patch.object(scanner, '_try_gdal_metadata', return_value=None):
                record = _build_record(tmp_path, [])
            assert record is not None
            assert record.extent_minx == -120.0
            assert record.extent_maxy == 50.0
            assert record.format == "NITF"
        finally:
            tmp_path.unlink()

    def test_cadrg_extent_populated_via_gdal(self):
        """CADRG file with no arcpy, rasterio failing, should get extent from GDAL."""
        with tempfile.NamedTemporaryFile(suffix=".r0", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            import scanner
            meta = self._make_geo_meta()
            with patch.object(scanner, '_ARCPY_AVAILABLE', False), \
                 patch.object(scanner, '_try_rasterio_metadata', return_value=None), \
                 patch.object(scanner, '_try_gdal_metadata', return_value=meta):
                record = _build_record(tmp_path, [])
            assert record is not None
            assert record.extent_minx == -120.0
            assert record.format == "CADRG"
        finally:
            tmp_path.unlink()

    def test_arcpy_extent_not_overwritten_by_fallback(self):
        """When arcpy provides extent, rasterio/GDAL fallbacks must not be called."""
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            import scanner
            mock_arcpy = MagicMock()
            mock_desc = MagicMock()
            mock_desc.format = "TIFF"
            mock_extent = MagicMock()
            mock_extent.XMin = -80.0
            mock_extent.YMin = 25.0
            mock_extent.XMax = -70.0
            mock_extent.YMax = 35.0
            mock_desc.extent = mock_extent
            mock_desc.spatialReference = None
            mock_desc.acquisitionDate = None
            mock_desc.bandCount = None
            mock_desc.width = None
            mock_desc.height = None
            mock_arcpy.Describe.return_value = mock_desc

            with patch.object(scanner, '_ARCPY_AVAILABLE', True), \
                 patch.object(scanner, 'arcpy', mock_arcpy), \
                 patch.object(scanner, '_try_rasterio_metadata') as mock_rio, \
                 patch.object(scanner, '_try_gdal_metadata') as mock_gdal_fn:
                record = _build_record(tmp_path, [])

            assert record is not None
            assert record.extent_minx == -80.0
            mock_rio.assert_not_called()
            mock_gdal_fn.assert_not_called()
        finally:
            tmp_path.unlink()

    def test_arcpy_gap_filled_by_fallback(self):
        """When arcpy succeeds but returns no extent, fallback should fill it."""
        with tempfile.NamedTemporaryFile(suffix=".ntf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            import scanner
            mock_arcpy = MagicMock()
            mock_desc = MagicMock()
            mock_desc.format = "NITF"
            mock_desc.extent = None
            mock_desc.spatialReference = None
            mock_desc.acquisitionDate = None
            mock_desc.bandCount = None
            mock_desc.width = None
            mock_desc.height = None
            mock_arcpy.Describe.return_value = mock_desc

            meta = self._make_geo_meta()
            with patch.object(scanner, '_ARCPY_AVAILABLE', True), \
                 patch.object(scanner, 'arcpy', mock_arcpy), \
                 patch.object(scanner, '_try_rasterio_metadata', return_value=meta), \
                 patch.object(scanner, '_try_gdal_metadata', return_value=None):
                record = _build_record(tmp_path, [])

            assert record is not None
            assert record.extent_minx == -120.0
            assert record.extent_maxy == 50.0
        finally:
            tmp_path.unlink()


class TestNitfIntegration:
    """End-to-end: a real (synthetic) NITF 2.1 file flows through _build_record."""

    def test_build_record_populates_nitf_ntm_fields(self, tmp_path):
        from tests.test_nitf import build_nitf21, igeolo_g, _DEFAULT_CORNERS_DMS
        import scanner

        blob = build_nitf21(icords="G", igeolo=igeolo_g(_DEFAULT_CORNERS_DMS))
        p = tmp_path / "NTM001.ntf"
        p.write_bytes(blob)

        # Force the dependency-free path (no arcpy / rasterio / gdal).
        with patch.object(scanner, "_ARCPY_AVAILABLE", False):
            rec = _build_record(p, [])

        assert rec is not None
        assert rec.format == "NITF"
        # NTM metadata captured from the header/subheader
        assert rec.image_id == "TESTIMG001"
        assert rec.image_category == "VIS"
        assert rec.image_source == "TESTSENSOR-1"
        assert rec.file_title == "NTM TEST COLLECTION ALPHA"
        assert rec.classification == "U"
        assert rec.num_image_segments == 1
        # IDATIM populated acquisition_date (filename had none)
        assert rec.acquisition_date == datetime(2025, 1, 15, 12, 0, 0)
        # True corner geometry + dimensions
        assert rec.corners is not None and len(rec.corners) == 4
        assert rec.width == 2048 and rec.height == 1024
        assert rec.extent_minx == pytest.approx(-117.5)
        assert rec.extent_maxy == pytest.approx(34.0)

    def test_geo_from_nitf_none_passthrough(self):
        assert _geo_from_nitf(None) is None
