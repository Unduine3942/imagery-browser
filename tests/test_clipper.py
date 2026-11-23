"""Tests for clipper.py — geospatial clip + PNG snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

import clipper

rasterio = pytest.importorskip("rasterio")
np = pytest.importorskip("numpy")
from rasterio.transform import from_origin  # noqa: E402
from PIL import Image  # noqa: E402


def _make_geotiff(path: Path, width: int = 100, height: int = 80, crs: str | None = "EPSG:4326") -> None:
    """Write a small georeferenced RGB GeoTIFF.

    Origin at lon=10, lat=50; pixel size 0.01 deg. So pixel (col,row) maps to
    lon = 10 + col*0.01, lat = 50 - row*0.01.
    """
    transform = from_origin(10.0, 50.0, 0.01, 0.01)
    data = np.zeros((3, height, width), dtype="uint8")
    # Make pixel values encode their column so we can verify the window offset.
    for c in range(width):
        data[0, :, c] = c % 256
    profile = {
        "driver": "GTiff", "width": width, "height": height, "count": 3,
        "dtype": "uint8", "transform": transform,
    }
    if crs:
        profile["crs"] = crs
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)


class TestClipByPixels:
    def test_clip_creates_output_with_correct_size(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src)
        out = tmp_path / "clip.tif"

        result = clipper.clip_geotiff_by_pixels(str(src), 10, 5, 30, 20, str(out))

        assert result.ok, result.error
        assert out.exists()
        assert (result.width, result.height) == (30, 20)
        with rasterio.open(out) as ds:
            assert ds.width == 30 and ds.height == 20

    def test_clip_preserves_crs(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src, crs="EPSG:4326")
        out = tmp_path / "clip.tif"

        result = clipper.clip_geotiff_by_pixels(str(src), 0, 0, 20, 20, str(out))

        assert result.ok and result.georeferenced
        with rasterio.open(out) as ds:
            assert ds.crs is not None
            assert ds.crs.to_epsg() == 4326

    def test_clip_offsets_transform_to_window_origin(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src)
        out = tmp_path / "clip.tif"

        clipper.clip_geotiff_by_pixels(str(src), 20, 10, 25, 25, str(out))

        # Window origin (col=20,row=10) → lon = 10 + 20*0.01 = 10.2, lat = 50 - 10*0.01 = 49.9
        with rasterio.open(out) as ds:
            assert ds.transform.c == pytest.approx(10.2)
            assert ds.transform.f == pytest.approx(49.9)

    def test_clip_pixel_values_match_source_window(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src)
        out = tmp_path / "clip.tif"

        clipper.clip_geotiff_by_pixels(str(src), 30, 0, 10, 10, str(out))

        with rasterio.open(out) as ds:
            band0 = ds.read(1)
        # Column c of the clip came from source column 30+c, encoded as the value.
        assert band0[0, 0] == 30
        assert band0[0, 9] == 39

    def test_window_clamped_to_image_extent(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src, width=100, height=80)
        out = tmp_path / "clip.tif"

        # Request a window that runs off the right/bottom edge.
        result = clipper.clip_geotiff_by_pixels(str(src), 90, 70, 50, 50, str(out))

        assert result.ok
        assert (result.width, result.height) == (10, 10)  # clamped to 100x80

    def test_window_entirely_outside_returns_error(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src)
        out = tmp_path / "clip.tif"

        result = clipper.clip_geotiff_by_pixels(str(src), 500, 500, 10, 10, str(out))

        assert not result.ok
        assert "outside" in result.error.lower()
        assert not out.exists()

    def test_zero_size_returns_error(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src)
        out = tmp_path / "clip.tif"

        result = clipper.clip_geotiff_by_pixels(str(src), 0, 0, 0, 10, str(out))

        assert not result.ok
        assert "zero size" in result.error.lower()

    def test_missing_source_returns_error(self, tmp_path):
        out = tmp_path / "clip.tif"
        result = clipper.clip_geotiff_by_pixels(str(tmp_path / "nope.tif"), 0, 0, 10, 10, str(out))
        assert not result.ok
        assert "not found" in result.error.lower()


class TestClipByBounds:
    def test_clip_by_bounds_maps_to_correct_pixels(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src)
        out = tmp_path / "clip.tif"

        # Bounds lon 10.2..10.4, lat 49.7..49.9 → cols 20..40, rows 10..30 → 20x20
        result = clipper.clip_geotiff_by_bounds(str(src), 10.2, 49.7, 10.4, 49.9, str(out))

        assert result.ok, result.error
        assert (result.width, result.height) == (20, 20)

    def test_clip_by_bounds_rejects_inverted_box(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src)
        out = tmp_path / "clip.tif"

        result = clipper.clip_geotiff_by_bounds(str(src), 10.4, 49.9, 10.2, 49.7, str(out))

        assert not result.ok


class TestRasterInfo:
    def test_reports_dimensions_and_crs(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src, width=120, height=90, crs="EPSG:4326")

        info = clipper.raster_info(str(src))

        assert info is not None
        assert (info.width, info.height, info.count) == (120, 90, 3)
        assert info.has_crs is True

    def test_missing_file_returns_none(self, tmp_path):
        assert clipper.raster_info(str(tmp_path / "nope.tif")) is None


class TestReadRegionAsImage:
    def test_full_extent_when_size_zero(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src, width=100, height=80)

        img = clipper.read_region_as_image(str(src), 0, 0, 0, 0)

        assert img is not None
        assert img.size == (100, 80)
        assert img.mode == "RGB"

    def test_region_is_decimated_to_max_px(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src, width=4000, height=2000)

        img = clipper.read_region_as_image(str(src), 0, 0, 4000, 2000, max_px=1000)

        assert img is not None
        assert max(img.size) == 1000

    def test_window_subset_size(self, tmp_path):
        src = tmp_path / "src.tif"
        _make_geotiff(src, width=100, height=80)

        img = clipper.read_region_as_image(str(src), 10, 10, 40, 30, max_px=4096)

        assert img is not None
        assert img.size == (40, 30)


class TestSnapshot:
    def test_snapshot_saves_png(self, tmp_path):
        img = Image.new("RGB", (40, 30), (120, 60, 200))
        out = tmp_path / "snap.png"

        result = clipper.save_snapshot_png(img, str(out))

        assert result.ok and out.exists()
        assert result.backend == "pil" and not result.georeferenced
        with Image.open(out) as reopened:
            assert reopened.size == (40, 30)

    def test_snapshot_converts_non_rgb_mode(self, tmp_path):
        img = Image.new("P", (10, 10))
        out = tmp_path / "snap.png"

        result = clipper.save_snapshot_png(img, str(out))

        assert result.ok and out.exists()
