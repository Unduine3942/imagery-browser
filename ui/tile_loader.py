from __future__ import annotations

import logging
import math
import sys
from pathlib import Path as _Path
from typing import Optional

# Fill for canvas area outside the world (past the poles or the antimeridian).
# Matches COLOR_CANVAS_BG in ui/styles.py.
OFF_WORLD_FILL = "#a8c8e8"

_log = logging.getLogger(__name__)

try:
    from PIL import Image
    _PIL_AVAILABLE = True
    # Basemaps are large, trusted, user-selected files — lift PIL's
    # decompression-bomb guard so multi-hundred-megapixel rasters (e.g. the
    # 21600×10800 Natural Earth HYP_HR_SR_OB_DR) can be opened and downsampled.
    Image.MAX_IMAGE_PIXELS = None
except ImportError:
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

from config import MAX_BASEMAP_PX as _MAX_BASEMAP_PX  # PIL-fallback working cap (see config)

# Resident preview size for the GDAL/rasterio backends. These read the visible
# window at native resolution on demand, so the preview only needs to be good
# enough for zoomed-out views — kept small for fast load and low memory
# (2048 ≈ 16 MB RGBA; native windowed reads supply all zoomed-in detail).
_PREVIEW_PX = 2048

def _assets_dir() -> _Path:
    """Locate the bundled assets directory.

    Works both from source (../assets relative to this file) and from a
    PyInstaller frozen build, where bundled data lives under sys._MEIPASS.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or _Path(sys.executable).parent
        return _Path(base) / "assets"
    return _Path(__file__).parent.parent / "assets"


_ASSETS_DIR = _assets_dir()
_WORLD_PNG = _ASSETS_DIR / "world_basemap.png"

_GEOTIFF_EXTENSIONS = {".tif", ".tiff", ".jp2", ".img", ".ecw", ".sid", ".vrt", ".png"}
_KML_EXTENSIONS = {".kml", ".kmz"}


def _kml_iter(root, local_name: str):
    """Yield all descendants whose local tag name (namespace stripped) matches local_name."""
    for el in root.iter():
        tag = el.tag
        if tag.startswith("{"):
            tag = tag.split("}", 1)[1]
        if tag == local_name:
            yield el


def _kml_find(parent, local_name: str):
    """Return first direct child whose local tag name matches local_name, or None."""
    for child in parent:
        tag = child.tag
        if tag.startswith("{"):
            tag = tag.split("}", 1)[1]
        if tag == local_name:
            return child
    return None


class BasemapRenderer:
    """Renders a bundled equirectangular world PNG as a Tier-1 offline basemap."""

    def __init__(self) -> None:
        self._img: Optional["Image.Image"] = None
        self._loaded = False

    def load(self) -> bool:
        if self._loaded:
            return self._img is not None
        self._loaded = True
        if not (_PIL_AVAILABLE and _WORLD_PNG.exists()):
            return False
        try:
            self._img = Image.open(_WORLD_PNG).convert("RGBA")
        except Exception:
            self._img = None
        return self._img is not None

    def render(
        self,
        world_minx: float,
        world_miny: float,
        world_maxx: float,
        world_maxy: float,
        canvas_w: int,
        canvas_h: int,
    ) -> Optional["Image.Image"]:
        """Return a canvas-sized PIL image cropped to the visible lon/lat bbox."""
        if not self.load() or self._img is None:
            return None
        if world_maxx <= world_minx or world_maxy <= world_miny:
            return None
        iw, ih = self._img.size

        def lon_to_px(lon: float) -> float:
            return (lon + 180.0) / 360.0 * iw

        def lat_to_px(lat: float) -> float:
            return (90.0 - lat) / 180.0 * ih

        # The requested window in source pixels. It can extend past the image
        # when the view is zoomed out or panned beyond the poles/antimeridian.
        fx0, fx1 = lon_to_px(world_minx), lon_to_px(world_maxx)
        fy0, fy1 = lat_to_px(world_maxy), lat_to_px(world_miny)
        span_x, span_y = fx1 - fx0, fy1 - fy0
        if span_x <= 0 or span_y <= 0:
            return None

        # Clamp to the area the image actually covers.
        cx0, cx1 = max(0.0, fx0), min(float(iw), fx1)
        cy0, cy1 = max(0.0, fy0), min(float(ih), fy1)
        if cx1 <= cx0 or cy1 <= cy0:
            return None

        # Scale the clamped part and paste it where it belongs instead of
        # stretching it across the whole canvas. Stretching gives the basemap a
        # different scale from the vector overlays, which makes footprints
        # drift away from the map while panning or zooming.
        scale_x = canvas_w / span_x
        scale_y = canvas_h / span_y
        dest_w = max(1, int(round((cx1 - cx0) * scale_x)))
        dest_h = max(1, int(round((cy1 - cy0) * scale_y)))
        dest_x = int(round((cx0 - fx0) * scale_x))
        dest_y = int(round((cy0 - fy0) * scale_y))

        cropped = self._img.crop((
            int(math.floor(cx0)), int(math.floor(cy0)),
            int(math.ceil(cx1)), int(math.ceil(cy1)),
        )).resize((dest_w, dest_h), resample=Image.BICUBIC)

        out = Image.new("RGB", (canvas_w, canvas_h), OFF_WORLD_FILL)
        out.paste(cropped, (dest_x, dest_y))
        return out


class GeoTIFFBasemap:
    """Load a georeferenced raster (GeoTIFF, JP2, IMG, …) as an optional basemap layer.

    Rendering strategy, in order of preference:
      • GDAL (osgeo) or rasterio — keep a small resident *preview* for zoomed-out
        views, and read the *visible window at native resolution* on demand when
        zoomed in. This shows the source's full detail at every zoom with low
        memory, and works in the air-gapped ArcGIS Pro environment (Pro bundles
        GDAL). rasterio is used only if importable; it is never required.
      • PIL + world file — with neither GDAL nor rasterio: load one downsampled
        working image (capped at config.MAX_BASEMAP_PX) and crop/scale it. Quality
        is bounded by that cap; true windowed native reads aren't possible in PIL.

    ``self._img`` holds the resident preview (GDAL/rasterio) or working image (PIL);
    render() composites the visible region onto a canvas-sized RGBA image.
    """

    def __init__(self, path: str) -> None:
        self._img: Optional["Image.Image"] = None   # resident preview / working image
        self._minx = self._miny = self._maxx = self._maxy = 0.0
        self._valid = False
        self._backend: Optional[str] = None          # "gdal" | "rasterio" | "pil"
        self._geographic = False                      # native windowed reads only if True
        self._src_w = 0                               # native source pixel dims
        self._src_h = 0
        self._norm: Optional[list] = None             # per-band (lo, hi) for non-8-bit sources
        try:
            self._path = str(_Path(path).resolve())
        except (OSError, RuntimeError):
            self._path = path
            return
        self._load()

    # -- loading --

    def _load(self) -> None:
        if not _PIL_AVAILABLE:
            return
        # GDAL first: it ships with ArcGIS Pro (air-gapped) and supports windowed
        # native reads. rasterio is used only if importable, never required.
        if self._try_gdal():
            return
        if self._try_rasterio():
            return
        self._try_pil_worldfile()

    def _try_gdal(self) -> bool:
        """Discover georeferencing + build a small preview; enable windowed reads."""
        try:
            from osgeo import gdal, osr  # type: ignore[import]
            import numpy as np  # type: ignore[import]
        except ImportError:
            return False
        try:
            ds = gdal.Open(self._path)
            if ds is None:
                return False

            ncols, nrows = ds.RasterXSize, ds.RasterYSize
            gt = ds.GetGeoTransform()
            xmin, xpx, ymax, ypx = gt[0], gt[1], gt[3], gt[5]  # ypx < 0 (north-up)
            xmax = xmin + xpx * ncols
            ymin = ymax + ypx * nrows

            geographic = True
            proj = ds.GetProjection()
            if proj:
                srs = osr.SpatialReference()
                srs.ImportFromWkt(proj)
                geographic = bool(srs.IsGeographic())
                if not geographic:
                    # Reproject corners to WGS84 for preview placement; windowed
                    # native reads stay disabled (lon/lat↔pixel isn't linear).
                    wgs84 = osr.SpatialReference()
                    wgs84.ImportFromEPSG(4326)
                    ct = osr.CoordinateTransformation(srs, wgs84)
                    corners = [ct.TransformPoint(xmin, ymin), ct.TransformPoint(xmin, ymax),
                               ct.TransformPoint(xmax, ymin), ct.TransformPoint(xmax, ymax)]
                    lons = [c[0] for c in corners]
                    lats = [c[1] for c in corners]
                    xmin, xmax = min(lons), max(lons)
                    ymin, ymax = min(lats), max(lats)

            if not (xmin < xmax and ymin < ymax):
                _log.debug("GDAL invalid bounds for %s", self._path)
                return False

            self._minx, self._miny, self._maxx, self._maxy = xmin, ymin, xmax, ymax
            self._src_w, self._src_h = ncols, nrows
            self._geographic = geographic
            is_byte = ds.GetRasterBand(1).DataType == gdal.GDT_Byte

            scale = min(1.0, _PREVIEW_PX / max(ncols, nrows, 1))
            out_w, out_h = max(1, int(ncols * scale)), max(1, int(nrows * scale))
            norm: Optional[list] = None if is_byte else []
            bands: list = []
            for i in range(1, min(ds.RasterCount + 1, 5)):
                arr = ds.GetRasterBand(i).ReadAsArray(buf_xsize=out_w, buf_ysize=out_h)
                if arr is None:
                    continue
                if is_byte:
                    bands.append(arr.astype(np.uint8))
                else:
                    a = arr.astype(np.float32)
                    lo, hi = float(a.min()), float(a.max())
                    norm.append((lo, hi))
                    if hi > lo:
                        a = (a - lo) / (hi - lo) * 255.0
                    bands.append(a.clip(0, 255).astype(np.uint8))
            ds = None
            self._norm = norm
            self._img = self._bands_to_image(bands, np)
            self._backend = "gdal"
            self._valid = self._img is not None
            return self._valid
        except Exception as exc:
            _log.debug("GDAL GeoTIFF load failed for %s: %s", self._path, exc)
            return False

    def _read_window_gdal(self, xoff: int, yoff: int, xsize: int, ysize: int,
                          out_w: int, out_h: int) -> "Optional[Image.Image]":
        from osgeo import gdal  # type: ignore[import]
        import numpy as np  # type: ignore[import]
        ds = gdal.Open(self._path)
        if ds is None:
            return None
        try:
            bands: list = []
            for i in range(1, min(ds.RasterCount + 1, 5)):
                arr = ds.GetRasterBand(i).ReadAsArray(xoff, yoff, xsize, ysize,
                                                      buf_xsize=out_w, buf_ysize=out_h)
                if arr is None:
                    return None
                bands.append(self._normalize_band(arr, i - 1, np))
            return self._bands_to_image(bands, np)
        finally:
            ds = None

    def _try_rasterio(self) -> bool:
        """Same as _try_gdal but via rasterio (optional dev-machine convenience)."""
        try:
            import warnings
            import rasterio  # type: ignore[import]
            from rasterio.warp import transform_bounds  # type: ignore[import]
            from rasterio.crs import CRS  # type: ignore[import]
            from rasterio.enums import Resampling  # type: ignore[import]
            from rasterio.errors import NotGeoreferencedWarning  # type: ignore[import]
            import numpy as np  # type: ignore[import]
        except ImportError:
            return False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", NotGeoreferencedWarning)
                src = rasterio.open(self._path)
            try:
                if not src.crs:
                    return False  # not georeferenced → defer to the PIL/world-file path
                bounds = transform_bounds(src.crs, CRS.from_epsg(4326), *src.bounds)
                if not (bounds[0] < bounds[2] and bounds[1] < bounds[3]):
                    return False
                self._minx, self._miny, self._maxx, self._maxy = bounds
                self._src_w, self._src_h = src.width, src.height
                self._geographic = bool(src.crs.is_geographic)
                is_byte = str(src.dtypes[0]) == "uint8"
                scale = min(1.0, _PREVIEW_PX / max(src.width, src.height, 1))
                out_w, out_h = max(1, int(src.width * scale)), max(1, int(src.height * scale))
                data = src.read(out_shape=(src.count, out_h, out_w),
                                resampling=Resampling.bilinear)
            finally:
                src.close()
            norm: Optional[list] = None if is_byte else []
            bands: list = []
            for i in range(min(data.shape[0], 4)):
                if is_byte:
                    bands.append(data[i].astype(np.uint8))
                else:
                    a = data[i].astype(np.float32)
                    lo, hi = float(a.min()), float(a.max())
                    norm.append((lo, hi))
                    if hi > lo:
                        a = (a - lo) / (hi - lo) * 255.0
                    bands.append(a.clip(0, 255).astype(np.uint8))
            self._norm = norm
            self._img = self._bands_to_image(bands, np)
            self._backend = "rasterio"
            self._valid = self._img is not None
            return self._valid
        except Exception as exc:
            _log.debug("rasterio GeoTIFF load failed for %s: %s", self._path, exc)
            return False

    def _read_window_rasterio(self, xoff: int, yoff: int, xsize: int, ysize: int,
                              out_w: int, out_h: int) -> "Optional[Image.Image]":
        import rasterio  # type: ignore[import]
        from rasterio.windows import Window  # type: ignore[import]
        from rasterio.enums import Resampling  # type: ignore[import]
        import numpy as np  # type: ignore[import]
        with rasterio.open(self._path) as src:
            data = src.read(out_shape=(src.count, out_h, out_w),
                            window=Window(xoff, yoff, xsize, ysize),
                            resampling=Resampling.bilinear)
        bands = [self._normalize_band(data[i], i, np) for i in range(min(data.shape[0], 4))]
        return self._bands_to_image(bands, np)

    # -- pixel helpers shared by both backends --

    def _normalize_band(self, arr, idx: int, np):
        """Scale a window band to 0-255 using the GLOBAL min/max captured at load,
        so brightness stays consistent across viewports (no per-window flicker)."""
        if self._norm is None:
            return arr.astype(np.uint8)
        lo, hi = self._norm[idx] if idx < len(self._norm) else (float(arr.min()), float(arr.max()))
        a = arr.astype(np.float32)
        if hi > lo:
            a = (a - lo) / (hi - lo) * 255.0
        return a.clip(0, 255).astype(np.uint8)

    @staticmethod
    def _bands_to_image(bands: list, np) -> "Optional[Image.Image]":
        if not bands:
            return None
        if len(bands) >= 4:
            return Image.fromarray(np.stack(bands[:4], axis=2), "RGBA")
        if len(bands) >= 3:
            return Image.fromarray(np.stack(bands[:3], axis=2), "RGB").convert("RGBA")
        return Image.fromarray(bands[0], "L").convert("RGBA")

    # World-file sidecar extensions per raster type (standard "replace extension").
    _WORLD_FILE_EXTS = {
        ".tif":  (".tfw", ".tifw", ".wld"),
        ".tiff": (".tfw", ".tifw", ".wld"),
        ".png":  (".pgw", ".pngw", ".wld"),
        ".jpg":  (".jgw", ".jpgw", ".wld"),
        ".jpeg": (".jgw", ".jpegw", ".wld"),
    }

    def _try_pil_worldfile(self) -> bool:
        """Load a raster with PIL alone, georeferenced via a world file, embedded
        GeoTIFF tags, or (for PNG with no world file) assumed full-world.

        Lets large georeferenced GeoTIFF basemaps load without rasterio/GDAL —
        e.g. Natural Earth HYP_HR_SR_OB_DR (.tif + .tfw + .prj). Projected rasters
        are skipped (cannot be reprojected to WGS84 without GDAL)."""
        if not _PIL_AVAILABLE:
            return False
        path = _Path(self._path)
        ext = path.suffix.lower()
        if ext not in self._WORLD_FILE_EXTS:
            return False
        if self._is_projected_sidecar(path):
            _log.debug("PIL fallback: %s has a projected .prj; needs GDAL to reproject", self._path)
            return False
        try:
            img = Image.open(self._path)
            iw, ih = img.size  # available without a full decode
            bounds = (
                self._bounds_from_world_file(path, iw, ih)
                or self._bounds_from_geotiff_tags(img, iw, ih)
                or ((-180.0, -90.0, 180.0, 90.0) if ext == ".png" else None)
            )
            if bounds is None:
                _log.debug("PIL fallback: no georeferencing found for %s", self._path)
                return False
            minx, miny, maxx, maxy = bounds
            if not (minx < maxx and miny < maxy):
                return False
            # Reject extents outside the geographic range — a strong signal the
            # raster is in projected (metre) units we cannot place on a lon/lat map.
            if not (-180.5 <= minx and maxx <= 180.5 and -90.5 <= miny and maxy <= 90.5):
                _log.debug("PIL fallback: bounds out of geographic range for %s: %s", self._path, bounds)
                return False

            img.thumbnail((_MAX_BASEMAP_PX, _MAX_BASEMAP_PX), Image.BILINEAR)
            self._img = img.convert("RGBA")
            self._minx, self._miny, self._maxx, self._maxy = minx, miny, maxx, maxy
            self._src_w, self._src_h = self._img.size
            self._backend = "pil"   # no windowed reads — render crops this image
            self._valid = True
            return True
        except Exception as exc:
            _log.debug("PIL world-file load failed for %s: %s", self._path, exc)
            return False

    @staticmethod
    def _is_projected_sidecar(path: "_Path") -> bool:
        """True when a .prj sidecar describes a projected CRS (PROJCS)."""
        prj = path.with_suffix(".prj")
        try:
            if prj.exists():
                return "PROJCS" in prj.read_text(encoding="utf-8", errors="replace").upper()
        except OSError:
            pass
        return False

    @staticmethod
    def _bounds_from_world_file(path: "_Path", iw: int, ih: int):
        """Compute (minx, miny, maxx, maxy) from a world-file sidecar, or None."""
        for wext in GeoTIFFBasemap._WORLD_FILE_EXTS.get(path.suffix.lower(), ()):
            wf = path.with_suffix(wext)
            if not wf.exists():
                continue
            try:
                nums = wf.read_text(encoding="utf-8", errors="replace").split()
                if len(nums) < 6:
                    continue
                a, d, b, e, c, f = (float(n) for n in nums[:6])
            except (OSError, ValueError):
                continue
            if a == 0 or e == 0 or d != 0 or b != 0:
                continue  # degenerate or rotated raster — unsupported here
            minx = c - a / 2.0          # world-file C/F are pixel-center coords
            maxy = f - e / 2.0          # e is negative for north-up rasters
            maxx = minx + a * iw
            miny = maxy + e * ih
            if minx > maxx:
                minx, maxx = maxx, minx
            if miny > maxy:
                miny, maxy = maxy, miny
            return (minx, miny, maxx, maxy)
        return None

    @staticmethod
    def _bounds_from_geotiff_tags(img: "Image.Image", iw: int, ih: int):
        """Compute bounds from embedded GeoTIFF ModelPixelScale/ModelTiepoint tags."""
        tags = getattr(img, "tag_v2", None)
        if not tags:
            return None
        scale = tags.get(33550)     # ModelPixelScaleTag: (sx, sy, sz)
        tiepoint = tags.get(33922)  # ModelTiepointTag: (i, j, k, X, Y, Z)
        if not scale or not tiepoint or len(scale) < 2 or len(tiepoint) < 6:
            return None
        try:
            sx, sy = float(scale[0]), float(scale[1])
            i, j = float(tiepoint[0]), float(tiepoint[1])
            x, y = float(tiepoint[3]), float(tiepoint[4])
        except (TypeError, ValueError):
            return None
        if sx == 0 or sy == 0:
            return None
        minx = x - i * sx
        maxy = y + j * sy
        maxx = minx + sx * iw
        miny = maxy - sy * ih
        return (minx, miny, maxx, maxy)

    # -- public --

    @property
    def valid(self) -> bool:
        return self._valid

    def render(
        self,
        world_minx: float,
        world_miny: float,
        world_maxx: float,
        world_maxy: float,
        canvas_w: int,
        canvas_h: int,
    ) -> Optional["Image.Image"]:
        """Return a canvas-sized RGBA image with the raster composited in place.

        When zoomed in past the preview's resolution (GDAL/rasterio backend with a
        geographic source), the visible window is re-read at native resolution so
        the full detail of the source data is shown."""
        if not self._valid or self._img is None:
            return None

        ix0 = max(self._minx, world_minx)
        iy0 = max(self._miny, world_miny)
        ix1 = min(self._maxx, world_maxx)
        iy1 = min(self._maxy, world_maxy)
        if ix0 >= ix1 or iy0 >= iy1:
            return None  # not visible in this viewport

        vw = world_maxx - world_minx
        vh = world_maxy - world_miny
        dest_x0 = int((ix0 - world_minx) / vw * canvas_w)
        dest_x1 = int((ix1 - world_minx) / vw * canvas_w)
        dest_y0 = int((world_maxy - iy1) / vh * canvas_h)  # higher lat → top
        dest_y1 = int((world_maxy - iy0) / vh * canvas_h)
        paste_w = max(1, dest_x1 - dest_x0)
        paste_h = max(1, dest_y1 - dest_y0)

        region = self._read_region(ix0, iy0, ix1, iy1, paste_w, paste_h)
        if region is None:
            return None
        out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        out.paste(region, (dest_x0, dest_y0))
        return out

    def _read_region(self, ix0, iy0, ix1, iy1, out_w, out_h) -> "Optional[Image.Image]":
        """Image of the geographic intersection at the best available resolution —
        a native windowed read when it would beat the resident preview."""
        span_x = self._maxx - self._minx
        span_y = self._maxy - self._miny
        if (self._backend in ("gdal", "rasterio") and self._geographic
                and span_x > 0 and span_y > 0 and self._src_w > 0):
            preview_win_px = (ix1 - ix0) / span_x * self._img.width
            if preview_win_px < out_w * 0.98:  # preview would be upscaled → read native
                native_win_px = (ix1 - ix0) / span_x * self._src_w
                native_win_py = (iy1 - iy0) / span_y * self._src_h
                read_w = max(1, min(out_w, int(native_win_px) + 1))
                read_h = max(1, min(out_h, int(native_win_py) + 1))
                xoff, yoff, xsize, ysize = self._source_window(ix0, iy0, ix1, iy1)
                try:
                    reader = (self._read_window_gdal if self._backend == "gdal"
                              else self._read_window_rasterio)
                    img = reader(xoff, yoff, xsize, ysize, read_w, read_h)
                    if img is not None:
                        if img.size != (out_w, out_h):
                            img = img.resize((out_w, out_h), resample=Image.BICUBIC)
                        return img
                except Exception as exc:
                    _log.debug("windowed read failed (%s); falling back to preview: %s",
                               self._backend, exc)
        return self._crop_preview(ix0, iy0, ix1, iy1, out_w, out_h)

    def _source_window(self, ix0, iy0, ix1, iy1):
        """Map a WGS84 lon/lat intersection to a clamped source pixel window."""
        px_per_lon = self._src_w / (self._maxx - self._minx)
        px_per_lat = self._src_h / (self._maxy - self._miny)
        xoff = int((ix0 - self._minx) * px_per_lon)
        yoff = int((self._maxy - iy1) * px_per_lat)   # top edge = maxy
        xsize = int(round((ix1 - ix0) * px_per_lon))
        ysize = int(round((iy1 - iy0) * px_per_lat))
        xoff = max(0, min(self._src_w - 1, xoff))
        yoff = max(0, min(self._src_h - 1, yoff))
        xsize = max(1, min(self._src_w - xoff, xsize))
        ysize = max(1, min(self._src_h - yoff, ysize))
        return xoff, yoff, xsize, ysize

    def _crop_preview(self, ix0, iy0, ix1, iy1, out_w, out_h) -> "Optional[Image.Image]":
        """Crop the resident preview/working image to the intersection and resize."""
        img = self._img
        iw, ih = img.size
        span_x = self._maxx - self._minx
        span_y = self._maxy - self._miny
        cx0 = max(0, int((ix0 - self._minx) / span_x * iw))
        cy0 = max(0, int((self._maxy - iy1) / span_y * ih))
        cx1 = min(iw, int((ix1 - self._minx) / span_x * iw) + 1)
        cy1 = min(ih, int((self._maxy - iy0) / span_y * ih) + 1)
        if cx1 <= cx0 or cy1 <= cy0:
            return None
        return img.crop((cx0, cy0, cx1, cy1)).resize((out_w, out_h), resample=Image.BICUBIC)


class KMLBasemap:
    """Load a KML or KMZ file as an optional basemap layer.

    Primary strategy: <GroundOverlay> + <LatLonBox> (extracts embedded/referenced image).
    Fallback: render <coordinates> polygon/line geometry using PIL.ImageDraw.
    Interface is identical to GeoTIFFBasemap so map_canvas can use either without changes.
    """

    def __init__(self, path: str) -> None:
        try:
            resolved = _Path(path).resolve()
        except (OSError, RuntimeError):
            self._path = path
            self._img: Optional["Image.Image"] = None
            self._minx = self._miny = self._maxx = self._maxy = 0.0
            self._valid = False
            return
        self._path = str(resolved)
        self._img = None
        self._minx = self._miny = self._maxx = self._maxy = 0.0
        self._valid = False
        self._load()

    # -- loading --

    def _load(self) -> None:
        if not _PIL_AVAILABLE:
            return
        if _Path(self._path).suffix.lower() == ".kmz":
            self._load_kmz()
        else:
            self._load_kml_path(self._path, str(_Path(self._path).parent))

    def _load_kmz(self) -> None:
        import zipfile
        try:
            with zipfile.ZipFile(self._path, "r") as zf:
                kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
                if not kml_names:
                    return
                root_kml = next(
                    (n for n in kml_names if _Path(n).name.lower() == "doc.kml"),
                    kml_names[0],
                )
                self._parse_kml(zf.read(root_kml), zf=zf)
        except Exception as exc:
            _log.debug("KMZ load failed for %s: %s", self._path, exc)

    def _load_kml_path(self, path: str, base_dir: str) -> None:
        try:
            with open(path, "rb") as f:
                self._parse_kml(f.read(), base_dir=base_dir)
        except Exception as exc:
            _log.debug("KML file read failed for %s: %s", path, exc)

    def _parse_kml(self, kml_bytes: bytes, zf=None, base_dir: str = "") -> None:
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(kml_bytes)
        except ET.ParseError as exc:
            _log.debug("KML XML parse error: %s", exc)
            return
        for go in _kml_iter(root, "GroundOverlay"):
            if self._try_ground_overlay(go, zf=zf, base_dir=base_dir):
                return
        self._try_vector_render(root)

    def _try_ground_overlay(self, go, zf=None, base_dir: str = "") -> bool:
        llb = _kml_find(go, "LatLonBox")
        if llb is None:
            return False
        try:
            north = float(_kml_find(llb, "north").text.strip())
            south = float(_kml_find(llb, "south").text.strip())
            east = float(_kml_find(llb, "east").text.strip())
            west = float(_kml_find(llb, "west").text.strip())
        except (AttributeError, ValueError, TypeError):
            return False
        if not (west < east and south < north):
            return False

        href = ""
        icon = _kml_find(go, "Icon")
        if icon is not None:
            href_el = _kml_find(icon, "href")
            if href_el is not None and href_el.text:
                href = href_el.text.strip()

        img: Optional["Image.Image"] = None
        if href:
            img = self._load_image_href(href, zf=zf, base_dir=base_dir)

        if img is None:
            # No image found — fill the box with a semi-transparent rectangle
            span_x = east - west
            span_y = north - south
            scale = _MAX_BASEMAP_PX / max(span_x, span_y, 0.01)
            box_w = max(4, min(_MAX_BASEMAP_PX, int(span_x * scale)))
            box_h = max(4, min(_MAX_BASEMAP_PX, int(span_y * scale)))
            from PIL import ImageDraw
            img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
            ImageDraw.Draw(img).rectangle(
                (0, 0, box_w - 1, box_h - 1),
                fill=(100, 149, 237, 140),
                outline=(50, 100, 200, 220),
            )

        img = img.convert("RGBA")
        iw, ih = img.size
        scale = min(1.0, _MAX_BASEMAP_PX / max(iw, ih, 1))
        if scale < 1.0:
            img = img.resize(
                (max(1, int(iw * scale)), max(1, int(ih * scale))),
                resample=Image.BILINEAR,
            )
        self._img = img
        self._minx, self._miny, self._maxx, self._maxy = west, south, east, north
        self._valid = True
        return True

    def _load_image_href(self, href: str, zf=None, base_dir: str = "") -> Optional["Image.Image"]:
        if href.startswith(("http://", "https://")):
            return None  # no network access
        try:
            if zf is not None:
                names = zf.namelist()
                leaf = _Path(href.replace("\\", "/")).name
                match = next(
                    (n for n in names if n == href or n.endswith("/" + leaf)),
                    None,
                )
                if match:
                    import io
                    return Image.open(io.BytesIO(zf.read(match))).convert("RGBA")
            else:
                img_path = _Path(base_dir) / href
                if img_path.exists():
                    return Image.open(str(img_path)).convert("RGBA")
        except Exception as exc:
            _log.debug("KML image href load failed for %s: %s", href, exc)
        return None

    def _try_vector_render(self, root) -> None:
        from PIL import ImageDraw

        all_rings: list[list[tuple[float, float]]] = []
        all_xs: list[float] = []
        all_ys: list[float] = []

        for coords_el in _kml_iter(root, "coordinates"):
            if not coords_el.text:
                continue
            ring: list[tuple[float, float]] = []
            for token in coords_el.text.strip().split():
                parts = token.split(",")
                if len(parts) >= 2:
                    try:
                        lon, lat = float(parts[0]), float(parts[1])
                        ring.append((lon, lat))
                        all_xs.append(lon)
                        all_ys.append(lat)
                    except ValueError:
                        continue
            if ring:
                all_rings.append(ring)

        if not all_rings:
            return

        minx, maxx = min(all_xs), max(all_xs)
        miny, maxy = min(all_ys), max(all_ys)
        span_x = maxx - minx or 0.01
        span_y = maxy - miny or 0.01

        scale = _MAX_BASEMAP_PX / max(span_x, span_y)
        img_w = max(64, min(_MAX_BASEMAP_PX, int(span_x * scale)))
        img_h = max(64, min(_MAX_BASEMAP_PX, int(span_y * scale)))

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        def to_px(lon: float, lat: float) -> tuple:
            px = int((lon - minx) / span_x * (img_w - 1))
            py = int((maxy - lat) / span_y * (img_h - 1))
            return px, py

        for ring in all_rings:
            pts = [to_px(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=(100, 149, 237, 180), outline=(50, 100, 200, 255))
            elif len(pts) == 2:
                draw.line(pts, fill=(50, 100, 200, 255), width=2)
            elif len(pts) == 1:
                x, y = pts[0]
                draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(50, 100, 200, 255))

        self._img = img
        self._minx, self._miny, self._maxx, self._maxy = minx, miny, maxx, maxy
        self._valid = True

    # -- public --

    @property
    def valid(self) -> bool:
        return self._valid

    def render(
        self,
        world_minx: float,
        world_miny: float,
        world_maxx: float,
        world_maxy: float,
        canvas_w: int,
        canvas_h: int,
    ) -> Optional["Image.Image"]:
        """Return a canvas-sized RGBA PIL image with the KML overlay at the correct position."""
        if not self._valid or self._img is None:
            return None

        ix0 = max(self._minx, world_minx)
        iy0 = max(self._miny, world_miny)
        ix1 = min(self._maxx, world_maxx)
        iy1 = min(self._maxy, world_maxy)
        if ix0 >= ix1 or iy0 >= iy1:
            return None

        iw, ih = self._img.size
        raster_w = self._maxx - self._minx
        raster_h = self._maxy - self._miny

        def lon_to_raster_px(lon: float) -> float:
            return (lon - self._minx) / raster_w * iw

        def lat_to_raster_px(lat: float) -> float:
            return (self._maxy - lat) / raster_h * ih

        crop_x0 = max(0, int(lon_to_raster_px(ix0)))
        crop_y0 = max(0, int(lat_to_raster_px(iy1)))
        crop_x1 = min(iw, int(lon_to_raster_px(ix1)) + 1)
        crop_y1 = min(ih, int(lat_to_raster_px(iy0)) + 1)
        if crop_x1 <= crop_x0 or crop_y1 <= crop_y0:
            return None

        cropped = self._img.crop((crop_x0, crop_y0, crop_x1, crop_y1))

        viewport_w = world_maxx - world_minx
        viewport_h = world_maxy - world_miny

        def lon_to_canvas_px(lon: float) -> int:
            return int((lon - world_minx) / viewport_w * canvas_w)

        def lat_to_canvas_px(lat: float) -> int:
            return int((world_maxy - lat) / viewport_h * canvas_h)

        dest_x0 = lon_to_canvas_px(ix0)
        dest_y0 = lat_to_canvas_px(iy1)
        dest_x1 = lon_to_canvas_px(ix1)
        dest_y1 = lat_to_canvas_px(iy0)

        paste_w = max(1, dest_x1 - dest_x0)
        paste_h = max(1, dest_y1 - dest_y0)

        resized = cropped.resize((paste_w, paste_h), resample=Image.BICUBIC)
        out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        out.paste(resized, (dest_x0, dest_y0))
        return out
