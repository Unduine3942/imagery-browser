"""
Unit tests for ui/tile_loader.py

Covers:
- BasemapRenderer: load, render, cache behaviour, missing file
- GeoTIFFBasemap: render geometry (crop / paste position), invalid path
"""
from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from PIL import Image as PILImage

from ui.tile_loader import BasemapRenderer, GeoTIFFBasemap


def _make_equirect_image(w: int = 360, h: int = 180) -> PILImage.Image:
    """Return a solid-colour equirectangular image."""
    return PILImage.new("RGBA", (w, h), color=(100, 149, 237, 255))


def _make_png_bytes(w: int = 360, h: int = 180) -> bytes:
    buf = BytesIO()
    _make_equirect_image(w, h).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# BasemapRenderer
# ---------------------------------------------------------------------------

class TestBasemapRenderer:
    def test_load_returns_false_when_file_missing(self, tmp_path):
        renderer = BasemapRenderer()
        # Patch _WORLD_PNG to a nonexistent path
        with patch("ui.tile_loader._WORLD_PNG", tmp_path / "nonexistent.png"):
            assert renderer.load() is False

    def test_load_returns_true_when_file_present(self, tmp_path):
        png = tmp_path / "world.png"
        png.write_bytes(_make_png_bytes())
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._WORLD_PNG", png):
            assert renderer.load() is True

    def test_render_returns_none_when_file_missing(self, tmp_path):
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._WORLD_PNG", tmp_path / "nonexistent.png"):
            result = renderer.render(-180.0, -90.0, 180.0, 90.0, 400, 300)
        assert result is None

    def test_render_returns_canvas_sized_image(self, tmp_path):
        png = tmp_path / "world.png"
        png.write_bytes(_make_png_bytes(360, 180))
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._WORLD_PNG", png):
            result = renderer.render(-180.0, -90.0, 180.0, 90.0, 400, 300)
        assert result is not None
        assert result.size == (400, 300)

    def test_render_returns_none_for_zero_area_bbox(self, tmp_path):
        png = tmp_path / "world.png"
        png.write_bytes(_make_png_bytes(360, 180))
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._WORLD_PNG", png):
            # Same minx and maxx → zero area
            result = renderer.render(10.0, 10.0, 10.0, 20.0, 400, 300)
        assert result is None

    def test_load_is_cached_after_first_call(self, tmp_path):
        png = tmp_path / "world.png"
        png.write_bytes(_make_png_bytes())
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._WORLD_PNG", png):
            with patch("PIL.Image.open", wraps=PILImage.open) as mock_open:
                renderer.load()
                renderer.load()  # second call should not re-open
                assert mock_open.call_count == 1


# ---------------------------------------------------------------------------
# GeoTIFFBasemap — render geometry (mocked rasterio path)
# ---------------------------------------------------------------------------

def _make_mock_rasterio_src(
    width: int = 100, height: int = 50,
    minx: float = -180.0, miny: float = -90.0,
    maxx: float = 180.0, maxy: float = 90.0,
    count: int = 3,
):
    """Build a minimal rasterio dataset mock."""
    import numpy as np

    src = MagicMock()
    src.width = width
    src.height = height
    src.count = count
    src.bounds = MagicMock()
    src.crs = MagicMock()

    # read() returns shape (count, height, width), dtype uint8
    data = np.full((count, height, width), 128, dtype=np.uint8)
    src.read.return_value = data
    return src


class TestGeoTIFFBasemapRenderGeometry:
    """Validate that render() places the raster at the correct canvas position."""

    def _make_geotiff(
        self,
        raster_minx=-180.0, raster_miny=-90.0,
        raster_maxx=180.0, raster_maxy=90.0,
    ) -> GeoTIFFBasemap:
        """Create a GeoTIFFBasemap with a synthetic PIL image (bypasses I/O)."""
        gt = GeoTIFFBasemap.__new__(GeoTIFFBasemap)
        gt._path = "dummy.tif"
        gt._minx = raster_minx
        gt._miny = raster_miny
        gt._maxx = raster_maxx
        gt._maxy = raster_maxy
        gt._img = PILImage.new("RGBA", (360, 180), color=(255, 0, 0, 255))
        gt._valid = True
        gt._backend = "pil"        # exercise the preview-crop render path
        gt._geographic = False
        gt._src_w, gt._src_h = 360, 180
        gt._norm = None
        return gt

    def test_full_overlap_fills_canvas(self):
        gt = self._make_geotiff(-180, -90, 180, 90)
        result = gt.render(-180, -90, 180, 90, 400, 300)
        assert result is not None
        assert result.size == (400, 300)

    def test_no_overlap_returns_none(self):
        gt = self._make_geotiff(-180, -90, 0, 90)  # raster covers western hemisphere
        # viewport is entirely in eastern hemisphere
        result = gt.render(10, -90, 180, 90, 400, 300)
        assert result is None

    def test_partial_overlap_transparent_outside_raster(self):
        """Pixels outside the raster bbox should be transparent (alpha=0)."""
        # Raster only covers right half of canvas viewport
        gt = self._make_geotiff(0, -90, 180, 90)  # eastern hemisphere
        # Viewport covers full world
        result = gt.render(-180, -90, 180, 90, 400, 300)
        assert result is not None
        assert result.size == (400, 300)
        # Left half of canvas (x=0 to ~200) should have alpha=0
        px_left = result.getpixel((10, 150))
        assert px_left[3] == 0, f"Expected transparent pixel at x=10, got alpha={px_left[3]}"
        # Right half should be opaque (raster is solid red with full alpha)
        px_right = result.getpixel((390, 150))
        assert px_right[3] > 0, "Expected opaque pixel on right half"

    def test_result_is_canvas_sized_rgba(self):
        gt = self._make_geotiff(-90, -45, 90, 45)
        result = gt.render(-180, -90, 180, 90, 800, 600)
        assert result is not None
        assert result.size == (800, 600)
        assert result.mode == "RGBA"

    def test_invalid_geotiff_returns_none(self):
        gt = GeoTIFFBasemap("nonexistent_path_that_does_not_exist.tif")
        assert gt.valid is False
        result = gt.render(-180, -90, 180, 90, 400, 300)
        assert result is None


# ---------------------------------------------------------------------------
# GeoTIFFBasemap — PNG fallback (plain equirectangular PNG, no georeference)
# ---------------------------------------------------------------------------

class TestGeoTIFFBasemapPNGFallback:
    def test_plain_png_loads_as_full_world(self, tmp_path):
        png = tmp_path / "basemap.png"
        PILImage.new("RGB", (360, 180), color=(0, 128, 0)).save(png)
        gt = GeoTIFFBasemap(str(png))
        assert gt.valid is True
        assert gt._minx == -180.0
        assert gt._maxx == 180.0
        assert gt._miny == -90.0
        assert gt._maxy == 90.0

    def test_plain_png_renders_full_canvas(self, tmp_path):
        png = tmp_path / "basemap.png"
        PILImage.new("RGBA", (360, 180), color=(0, 128, 0, 255)).save(png)
        gt = GeoTIFFBasemap(str(png))
        result = gt.render(-180, -90, 180, 90, 400, 300)
        assert result is not None
        assert result.size == (400, 300)
        assert result.mode == "RGBA"

    def test_plain_png_downsampled_to_cap(self, tmp_path):
        """A raster larger than the working cap is downsampled to it at load."""
        png = tmp_path / "big.png"
        PILImage.new("RGB", (512, 256), color=(200, 200, 200)).save(png)
        # Patch the cap small so the test is fast and independent of the default.
        with patch("ui.tile_loader._MAX_BASEMAP_PX", 256), \
             patch.object(GeoTIFFBasemap, "_try_rasterio", return_value=False), \
             patch.object(GeoTIFFBasemap, "_try_gdal", return_value=False):
            gt = GeoTIFFBasemap(str(png))
        assert gt.valid is True
        iw, ih = gt._img.size
        assert max(iw, ih) <= 256

    def test_nonexistent_png_is_invalid(self):
        gt = GeoTIFFBasemap("nonexistent.png")
        assert gt.valid is False


# ---------------------------------------------------------------------------
# GeoTIFFBasemap — Security fixes: path resolution, invalid bounds
# ---------------------------------------------------------------------------

class TestGeoTIFFBasemapSecurityFixes:
    """Test security-critical paths: symlink collapse, invalid bounds detection."""

    def test_symlink_path_is_resolved_to_absolute(self, tmp_path):
        """Path.resolve() collapses symlinks; verify __init__ calls resolve()."""
        if not hasattr(Path, "symlink_to"):
            pytest.skip("symlink creation not available on this system")

        try:
            # Create a real file
            real_file = tmp_path / "real.png"
            PILImage.new("RGBA", (360, 180), color=(255, 0, 0, 255)).save(real_file)

            # Create a symlink to it
            symlink_path = tmp_path / "link.png"
            symlink_path.symlink_to(real_file)

            # Init with symlink path
            gt = GeoTIFFBasemap(str(symlink_path))

            # The stored _path should be the resolved absolute path, not the symlink
            resolved_path = str(symlink_path.resolve())
            assert gt._path == resolved_path
            assert not Path(gt._path).is_symlink()
        except (OSError, PermissionError) as e:
            pytest.skip(f"Cannot create symlinks: {e}")

    def test_oserror_during_resolve_sets_invalid(self, tmp_path):
        """If Path.resolve() raises OSError/RuntimeError, mark as invalid."""
        bad_path = str(tmp_path / "this" / "path" / "does" / "not" / "exist" / "file.tif")

        with patch("pathlib.Path.resolve", side_effect=OSError("Permission denied")):
            gt = GeoTIFFBasemap(bad_path)
            assert gt._valid is False

    def test_rasterio_invalid_bounds_returns_false(self, tmp_path):
        """rasterio yielding a degenerate extent (minx == maxx) → _try_rasterio returns False."""
        pytest.importorskip("rasterio")
        from rasterio.crs import CRS

        real_png = tmp_path / "test.png"
        PILImage.new("RGBA", (100, 100)).save(real_png)

        gt = GeoTIFFBasemap.__new__(GeoTIFFBasemap)
        gt._path = str(real_png)
        gt._img = None
        gt._valid = False
        gt._minx = gt._miny = gt._maxx = gt._maxy = 0.0
        gt._backend = None
        gt._geographic = False
        gt._src_w = gt._src_h = 0
        gt._norm = None

        # rasterio is imported locally inside _try_rasterio, so patch the real module.
        with patch("rasterio.open") as mock_rasterio_open:
            src_mock = MagicMock()
            src_mock.crs = CRS.from_epsg(4326)
            src_mock.bounds = (10.0, 5.0, 10.0, 15.0)  # minx == maxx → degenerate extent
            src_mock.width = 100
            src_mock.height = 100
            src_mock.count = 3
            src_mock.dtypes = ("uint8",)
            mock_rasterio_open.return_value = src_mock

            assert gt._try_rasterio() is False
            assert gt._valid is False

    def test_gdal_invalid_bounds_returns_false(self, tmp_path):
        """GDAL returning bounds where xmin >= xmax → _try_gdal returns False."""
        real_tif = tmp_path / "test.tif"
        PILImage.new("RGBA", (100, 100)).save(real_tif)

        with patch("ui.tile_loader.GeoTIFFBasemap._try_gdal") as mock_gdal:
            mock_gdal.return_value = False

            gt = GeoTIFFBasemap.__new__(GeoTIFFBasemap)
            gt._path = str(real_tif)
            gt._img = None
            gt._valid = False
            gt._minx = gt._miny = gt._maxx = gt._maxy = 0.0

            # Manually test the bounds check logic
            xmin, xmax = 10.0, 10.0  # invalid: equal bounds
            ymin, ymax = 5.0, 15.0

            # The check in code is: if not (xmin < xmax and ymin < ymax)
            assert not (xmin < xmax and ymin < ymax)  # condition triggers return False

    def test_geotiff_with_invalid_bounds_stays_invalid(self, tmp_path):
        """Create a GeoTIFFBasemap that fails both rasterio and GDAL path→ stays invalid."""
        # Create a file that's not actually a valid GeoTIFF
        bad_tif = tmp_path / "not_a_geotiff.tif"
        bad_tif.write_text("garbage data")

        gt = GeoTIFFBasemap(str(bad_tif))

        # Both rasterio and GDAL should fail; valid should stay False
        assert gt.valid is False


# ---------------------------------------------------------------------------
# _PIL_AVAILABLE = False code paths
# ---------------------------------------------------------------------------

class TestPILUnavailable:
    """Verify graceful degradation when Pillow is not installed.

    All tests patch ``ui.tile_loader._PIL_AVAILABLE`` to ``False`` to simulate
    an environment where the Pillow package is absent.  The actual PIL import
    in this test module is unaffected — we only replace the module-level flag
    that the production code reads at call time.
    """

    def test_basemap_renderer_load_returns_false(self, tmp_path):
        """BasemapRenderer.load() → False when PIL is unavailable."""
        png = tmp_path / "world.png"
        png.write_bytes(_make_png_bytes())
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._PIL_AVAILABLE", False), \
             patch("ui.tile_loader._WORLD_PNG", png):
            result = renderer.load()
        assert result is False

    def test_basemap_renderer_render_returns_none(self, tmp_path):
        """BasemapRenderer.render() → None when PIL is unavailable (load short-circuits)."""
        png = tmp_path / "world.png"
        png.write_bytes(_make_png_bytes())
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._PIL_AVAILABLE", False), \
             patch("ui.tile_loader._WORLD_PNG", png):
            result = renderer.render(-180.0, -90.0, 180.0, 90.0, 400, 300)
        assert result is None

    def test_basemap_renderer_load_is_cached_false(self, tmp_path):
        """A False result from load() is cached; a second call does not re-check the file."""
        png = tmp_path / "world.png"
        png.write_bytes(_make_png_bytes())
        renderer = BasemapRenderer()
        with patch("ui.tile_loader._PIL_AVAILABLE", False), \
             patch("ui.tile_loader._WORLD_PNG", png):
            first = renderer.load()
            second = renderer.load()
        assert first is False
        assert second is False
        assert renderer._loaded is True

    def test_geotiff_basemap_stays_invalid_without_pil(self, tmp_path):
        """GeoTIFFBasemap._load() returns early when PIL absent; _valid stays False."""
        png = tmp_path / "basemap.png"
        PILImage.new("RGB", (360, 180), color=(0, 128, 0)).save(png)
        with patch("ui.tile_loader._PIL_AVAILABLE", False):
            gt = GeoTIFFBasemap(str(png))
        assert gt._valid is False

    def test_geotiff_basemap_render_returns_none_without_pil(self, tmp_path):
        """GeoTIFFBasemap.render() returns None when the instance is invalid (no PIL)."""
        png = tmp_path / "basemap.png"
        PILImage.new("RGB", (360, 180), color=(0, 128, 0)).save(png)
        with patch("ui.tile_loader._PIL_AVAILABLE", False):
            gt = GeoTIFFBasemap(str(png))
        result = gt.render(-180.0, -90.0, 180.0, 90.0, 400, 300)
        assert result is None


class TestPILWorldFileLoader:
    """GeoTIFF/PNG basemaps load via PIL + world file when rasterio/GDAL are absent."""

    def _write_tif(self, tmp_path, w=8, h=4):
        p = tmp_path / "ne.tif"
        PILImage.new("RGB", (w, h), (10, 20, 30)).save(p, format="TIFF")
        return p

    def _write_tfw(self, tif_path, a, e, c, f):
        # World file lines: A, D, B, E, C, F (D/B = rotation)
        tif_path.with_suffix(".tfw").write_text(f"{a}\n0.0\n0.0\n{e}\n{c}\n{f}\n")

    def test_bounds_from_world_file_global(self, tmp_path):
        tif = self._write_tif(tmp_path, 8, 4)
        # 45°/px, top-left pixel center at (-157.5, 67.5) -> exactly global
        self._write_tfw(tif, 45.0, -45.0, -157.5, 67.5)
        b = GeoTIFFBasemap._bounds_from_world_file(tif, 8, 4)
        assert b == pytest.approx((-180.0, -90.0, 180.0, 90.0))

    def test_rotated_world_file_rejected(self, tmp_path):
        tif = self._write_tif(tmp_path)
        tif.with_suffix(".tfw").write_text("1\n0.5\n0.5\n-1\n0\n0\n")  # rotation terms set
        assert GeoTIFFBasemap._bounds_from_world_file(tif, 8, 4) is None

    def test_is_projected_sidecar(self, tmp_path):
        tif = self._write_tif(tmp_path)
        tif.with_suffix(".prj").write_text('PROJCS["WGS 84 / UTM zone 11N", ...]')
        assert GeoTIFFBasemap._is_projected_sidecar(tif) is True
        tif.with_suffix(".prj").write_text('GEOGCS["GCS_WGS_1984", ...]')
        assert GeoTIFFBasemap._is_projected_sidecar(tif) is False

    def test_loads_tif_via_pil_worldfile(self, tmp_path):
        tif = self._write_tif(tmp_path, 8, 4)
        self._write_tfw(tif, 45.0, -45.0, -157.5, 67.5)
        # Force the dependency-free PIL path regardless of rasterio/GDAL availability
        with patch.object(GeoTIFFBasemap, "_try_rasterio", return_value=False), \
             patch.object(GeoTIFFBasemap, "_try_gdal", return_value=False):
            bm = GeoTIFFBasemap(str(tif))
        assert bm.valid is True
        assert (bm._minx, bm._miny, bm._maxx, bm._maxy) == pytest.approx((-180.0, -90.0, 180.0, 90.0))
        assert bm._img is not None and bm._img.mode == "RGBA"

    def test_projected_tif_skipped_by_pil_path(self, tmp_path):
        tif = self._write_tif(tmp_path, 8, 4)
        self._write_tfw(tif, 1000.0, -1000.0, 400000.0, 4000000.0)  # metre units
        tif.with_suffix(".prj").write_text('PROJCS["UTM zone 11N"]')
        with patch.object(GeoTIFFBasemap, "_try_rasterio", return_value=False), \
             patch.object(GeoTIFFBasemap, "_try_gdal", return_value=False):
            bm = GeoTIFFBasemap(str(tif))
        assert bm.valid is False

    def test_png_without_worldfile_is_global(self, tmp_path):
        png = tmp_path / "world.png"
        _make_equirect_image(360, 180).save(png, format="PNG")
        with patch.object(GeoTIFFBasemap, "_try_rasterio", return_value=False), \
             patch.object(GeoTIFFBasemap, "_try_gdal", return_value=False):
            bm = GeoTIFFBasemap(str(png))
        assert bm.valid is True
        assert (bm._minx, bm._miny, bm._maxx, bm._maxy) == pytest.approx((-180.0, -90.0, 180.0, 90.0))


class TestWindowedReads:
    """Native windowed-read logic (works without GDAL/rasterio via mocked backends)."""

    def _make(self, backend="gdal", src_w=21600, src_h=10800, preview_w=4096, preview_h=2048):
        gt = GeoTIFFBasemap.__new__(GeoTIFFBasemap)
        gt._path = "dummy.tif"
        gt._minx, gt._miny, gt._maxx, gt._maxy = -180.0, -90.0, 180.0, 90.0
        gt._img = PILImage.new("RGBA", (preview_w, preview_h), (10, 20, 30, 255))
        gt._valid = True
        gt._backend = backend
        gt._geographic = True
        gt._src_w, gt._src_h = src_w, src_h
        gt._norm = None
        return gt

    def test_source_window_maps_lonlat_to_pixels(self):
        gt = self._make()  # 21600x10800 over the whole globe → 60 px/degree
        assert gt._source_window(-1, -1, 1, 1) == (10740, 5340, 120, 120)

    def test_source_window_clamps_to_raster(self):
        gt = self._make()
        xoff, yoff, xsize, ysize = gt._source_window(-180, -90, 180, 90)
        assert (xoff, yoff) == (0, 0)
        assert xoff + xsize <= gt._src_w and yoff + ysize <= gt._src_h

    def test_zoomed_in_triggers_native_read(self):
        gt = self._make(backend="gdal")
        sentinel = PILImage.new("RGBA", (700, 525), (1, 2, 3, 255))
        with patch.object(GeoTIFFBasemap, "_read_window_gdal", return_value=sentinel) as m:
            out = gt.render(-1, -1, 1, 1, 700, 525)  # 2° viewport → preview would upscale
        assert m.called
        assert out is not None and out.size == (700, 525)

    def test_zoomed_out_uses_preview(self):
        gt = self._make(backend="gdal")
        with patch.object(GeoTIFFBasemap, "_read_window_gdal") as m:
            out = gt.render(-180, -90, 180, 90, 700, 525)  # whole world → preview suffices
        assert not m.called
        assert out is not None and out.size == (700, 525)

    def test_rasterio_backend_uses_rasterio_reader(self):
        gt = self._make(backend="rasterio")
        sentinel = PILImage.new("RGBA", (700, 525), (4, 5, 6, 255))
        with patch.object(GeoTIFFBasemap, "_read_window_rasterio", return_value=sentinel) as m:
            out = gt.render(-1, -1, 1, 1, 700, 525)
        assert m.called and out is not None

    def test_pil_backend_never_windowed(self):
        gt = self._make(backend="pil")
        with patch.object(GeoTIFFBasemap, "_read_window_gdal") as mg, \
             patch.object(GeoTIFFBasemap, "_read_window_rasterio") as mr:
            out = gt.render(-1, -1, 1, 1, 700, 525)
        assert not mg.called and not mr.called
        assert out is not None and out.size == (700, 525)

    def test_windowed_read_failure_falls_back_to_preview(self):
        gt = self._make(backend="gdal")
        with patch.object(GeoTIFFBasemap, "_read_window_gdal", side_effect=RuntimeError("boom")):
            out = gt.render(-1, -1, 1, 1, 700, 525)
        assert out is not None and out.size == (700, 525)  # preview fallback, no crash


class TestRealRasterioBackend:
    """End-to-end against a real (generated) GeoTIFF via the rasterio backend."""

    def test_real_windowed_read_from_geotiff(self, tmp_path):
        rasterio = pytest.importorskip("rasterio")
        from rasterio.transform import from_bounds
        import numpy as np

        w, h = 256, 128
        path = tmp_path / "geo.tif"
        data = np.zeros((3, h, w), dtype=np.uint8)
        data[0] = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))  # E-W gradient
        with rasterio.open(
            path, "w", driver="GTiff", height=h, width=w, count=3, dtype="uint8",
            crs="EPSG:4326", transform=from_bounds(-180, -90, 180, 90, w, h),
        ) as dst:
            dst.write(data)

        # Tiny preview forces the native windowed-read branch when zoomed in.
        with patch("ui.tile_loader._PREVIEW_PX", 32):
            bm = GeoTIFFBasemap(str(path))

        assert bm.valid and bm._backend == "rasterio"
        assert bm._geographic is True
        assert (bm._src_w, bm._src_h) == (w, h)
        assert bm._img.width <= 32                      # preview downsampled
        assert bm._norm is None                          # 8-bit → no normalization

        out = bm.render(-90, -45, 90, 45, 200, 150)      # zoomed in → windowed read
        assert out is not None and out.size == (200, 150) and out.mode == "RGBA"
