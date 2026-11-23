"""
clipper.py — extract a sub-region ("clip" / "snapshot") from an imagery file.

Two output flavours:

  • Geospatial clip  → a new GeoTIFF that preserves coordinates/CRS, so the
    region is still usable in GIS. Primary path uses rasterio (windowed read +
    write with an offset transform); falls back to GDAL ``Translate``.

  • Visual snapshot  → a PNG of a rendered region. No georeferencing; for
    reports, briefings, and quick previews.

All public functions return a ``ClipResult`` and never raise for expected
failure modes (missing backend, out-of-bounds window, write error); they report
the problem in ``ClipResult.error`` instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover — typing only
    from PIL import Image as _PILImageModule

log = logging.getLogger(__name__)

# Optional geospatial backends (same guard pattern as scanner.py / tile_loader.py).
try:
    import rasterio as _rasterio
    from rasterio.windows import Window as _Window
    _RASTERIO_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when rasterio is absent
    _rasterio = None  # type: ignore[assignment]
    _Window = None  # type: ignore[assignment]
    _RASTERIO_AVAILABLE = False

try:
    from osgeo import gdal as _gdal
    _GDAL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when GDAL is absent
    _gdal = None  # type: ignore[assignment]
    _GDAL_AVAILABLE = False


@dataclass(frozen=True)
class ClipResult:
    """Outcome of a clip/snapshot operation."""

    ok: bool
    out_path: str = ""
    width: int = 0
    height: int = 0
    backend: str = ""          # "rasterio" | "gdal" | "pil"
    georeferenced: bool = False
    error: str = ""


def _clamp_window(col_off: int, row_off: int, width: int, height: int,
                  src_w: int, src_h: int) -> Optional[tuple[int, int, int, int]]:
    """Clamp a pixel window to the source extent. Returns None if it has no overlap."""
    x0 = max(0, min(col_off, src_w))
    y0 = max(0, min(row_off, src_h))
    x1 = max(0, min(col_off + width, src_w))
    y1 = max(0, min(row_off + height, src_h))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


def clip_geotiff_by_pixels(
    src_path: str,
    col_off: int,
    row_off: int,
    width: int,
    height: int,
    out_path: str,
) -> ClipResult:
    """Clip a pixel window from *src_path* into a new GeoTIFF at *out_path*.

    The window is clamped to the image extent. Georeferencing (CRS + an offset
    transform) is preserved when the source has it.
    """
    if width <= 0 or height <= 0:
        return ClipResult(ok=False, error="Clip region has zero size.")
    if not Path(src_path).is_file():
        return ClipResult(ok=False, error=f"Source not found: {src_path}")

    if _RASTERIO_AVAILABLE:
        return _clip_pixels_rasterio(src_path, col_off, row_off, width, height, out_path)
    if _GDAL_AVAILABLE:
        return _clip_pixels_gdal(src_path, col_off, row_off, width, height, out_path)
    return ClipResult(
        ok=False,
        error="No geospatial backend available (need rasterio or GDAL) to write a GeoTIFF clip. "
              "Use a PNG snapshot instead.",
    )


def _clip_pixels_rasterio(src_path, col_off, row_off, width, height, out_path) -> ClipResult:
    try:
        with _rasterio.open(src_path) as src:
            clamped = _clamp_window(col_off, row_off, width, height, src.width, src.height)
            if clamped is None:
                return ClipResult(ok=False, error="Clip region is outside the image.")
            x0, y0, w, h = clamped
            window = _Window(x0, y0, w, h)
            data = src.read(window=window)
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                width=w,
                height=h,
                transform=src.window_transform(window),
            )
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            with _rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data)
            return ClipResult(
                ok=True, out_path=str(out_path), width=w, height=h,
                backend="rasterio", georeferenced=src.crs is not None,
            )
    except Exception as exc:  # noqa: BLE001 - report, don't crash the UI
        log.warning("rasterio clip failed for %s: %s", src_path, exc)
        if _GDAL_AVAILABLE:
            return _clip_pixels_gdal(src_path, col_off, row_off, width, height, out_path)
        return ClipResult(ok=False, error=f"Clip failed: {exc}")


def _clip_pixels_gdal(src_path, col_off, row_off, width, height, out_path) -> ClipResult:
    try:
        ds = _gdal.Open(src_path)
        if ds is None:
            return ClipResult(ok=False, error=f"GDAL could not open: {src_path}")
        clamped = _clamp_window(col_off, row_off, width, height, ds.RasterXSize, ds.RasterYSize)
        if clamped is None:
            return ClipResult(ok=False, error="Clip region is outside the image.")
        x0, y0, w, h = clamped
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        georef = ds.GetProjection() not in (None, "")
        out = _gdal.Translate(out_path, ds, srcWin=[x0, y0, w, h], format="GTiff")
        ds = None
        if out is None:
            return ClipResult(ok=False, error="GDAL Translate produced no output.")
        out = None
        return ClipResult(ok=True, out_path=str(out_path), width=w, height=h,
                          backend="gdal", georeferenced=georef)
    except Exception as exc:  # noqa: BLE001
        log.warning("GDAL clip failed for %s: %s", src_path, exc)
        return ClipResult(ok=False, error=f"Clip failed: {exc}")


def clip_geotiff_by_bounds(
    src_path: str,
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    out_path: str,
) -> ClipResult:
    """Clip a geographic bounding box (in the source's own CRS units) to GeoTIFF.

    Convenience wrapper that converts bounds to a pixel window via the source
    transform, then delegates to :func:`clip_geotiff_by_pixels`.
    """
    if not _RASTERIO_AVAILABLE:
        return ClipResult(ok=False, error="rasterio is required for bounds-based clipping.")
    if maxx <= minx or maxy <= miny:
        return ClipResult(ok=False, error="Clip bounds have zero or negative size.")
    try:
        with _rasterio.open(src_path) as src:
            window = _rasterio.windows.from_bounds(minx, miny, maxx, maxy, transform=src.transform)
        col_off = int(window.col_off)
        row_off = int(window.row_off)
        width = max(1, int(round(window.width)))
        height = max(1, int(round(window.height)))
    except Exception as exc:  # noqa: BLE001
        return ClipResult(ok=False, error=f"Could not map bounds to pixels: {exc}")
    return clip_geotiff_by_pixels(src_path, col_off, row_off, width, height, out_path)


@dataclass(frozen=True)
class RasterInfo:
    """Lightweight dimensions/georeferencing summary of a raster."""

    width: int
    height: int
    count: int
    has_crs: bool


def raster_info(src_path: str) -> Optional[RasterInfo]:
    """Return pixel dimensions + band count for *src_path*, or None if unreadable."""
    if _RASTERIO_AVAILABLE:
        try:
            with _rasterio.open(src_path) as src:
                return RasterInfo(src.width, src.height, src.count, src.crs is not None)
        except Exception as exc:  # noqa: BLE001
            log.debug("rasterio raster_info failed for %s: %s", src_path, exc)
    if _GDAL_AVAILABLE:
        try:
            ds = _gdal.Open(src_path)
            if ds is not None:
                info = RasterInfo(ds.RasterXSize, ds.RasterYSize, ds.RasterCount,
                                  ds.GetProjection() not in (None, ""))
                ds = None
                return info
        except Exception as exc:  # noqa: BLE001
            log.debug("GDAL raster_info failed for %s: %s", src_path, exc)
    # Last resort: PIL (non-georeferenced rasters / plain images).
    try:
        from PIL import Image
        with Image.open(src_path) as im:
            return RasterInfo(im.width, im.height, len(im.getbands()), False)
    except Exception as exc:  # noqa: BLE001
        log.debug("PIL raster_info failed for %s: %s", src_path, exc)
    return None


def _normalize_to_uint8(arr, np):
    """Scale a single band to 0-255 uint8 using a robust 2-98 percentile stretch."""
    if arr.dtype == np.uint8:
        return arr
    finite = arr[np.isfinite(arr)] if np.issubdtype(arr.dtype, np.floating) else arr
    if finite.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    lo, hi = np.percentile(finite, (2, 98))
    if hi <= lo:
        lo, hi = float(finite.min()), float(finite.max())
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (arr.astype("float64") - lo) / (hi - lo)
    return (np.clip(scaled, 0.0, 1.0) * 255).astype(np.uint8)


def read_region_as_image(
    src_path: str,
    col_off: int,
    row_off: int,
    width: int,
    height: int,
    max_px: int = 2048,
) -> "Optional[_PILImageModule.Image]":
    """Read a pixel window and return it as an 8-bit RGB PIL image, decimated so
    the longer side is at most *max_px* (efficient for very large rasters).

    Used for both on-screen display and PNG snapshots. ``width``/``height`` of 0
    or negative are treated as the full image extent.
    """
    from PIL import Image

    info = raster_info(src_path)
    if info is None:
        return None
    if width <= 0 or height <= 0:
        col_off, row_off, width, height = 0, 0, info.width, info.height
    clamped = _clamp_window(col_off, row_off, width, height, info.width, info.height)
    if clamped is None:
        return None
    x0, y0, w, h = clamped
    scale = min(1.0, max_px / max(w, h, 1))
    out_w = max(1, int(round(w * scale)))
    out_h = max(1, int(round(h * scale)))

    if _RASTERIO_AVAILABLE:
        try:
            import numpy as np
            with _rasterio.open(src_path) as src:
                count = min(3, src.count)
                indexes = list(range(1, count + 1))
                data = src.read(
                    indexes,
                    window=_Window(x0, y0, w, h),
                    out_shape=(count, out_h, out_w),
                )
                bands = [_normalize_to_uint8(data[i], np) for i in range(count)]
                while len(bands) < 3:
                    bands.append(bands[0])  # grey → RGB
                rgb = np.dstack(bands[:3])
                return Image.fromarray(rgb, mode="RGB")
        except Exception as exc:  # noqa: BLE001
            log.debug("rasterio region read failed for %s: %s", src_path, exc)

    # PIL fallback (non-georeferenced or rasterio unavailable).
    try:
        with Image.open(src_path) as im:
            region = im.crop((x0, y0, x0 + w, y0 + h)).convert("RGB")
            if scale < 1.0:
                region = region.resize((out_w, out_h), Image.BILINEAR)
            return region
    except Exception as exc:  # noqa: BLE001
        log.debug("PIL region read failed for %s: %s", src_path, exc)
        return None


def save_snapshot_png(image: "_PILImageModule.Image", out_path: str) -> ClipResult:
    """Save a rendered PIL image as a PNG snapshot (no georeferencing)."""
    try:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        rgb = image.convert("RGBA") if image.mode not in ("RGB", "RGBA") else image
        rgb.save(str(out), format="PNG")
        return ClipResult(ok=True, out_path=str(out), width=image.width,
                          height=image.height, backend="pil", georeferenced=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("PNG snapshot failed for %s: %s", out_path, exc)
        return ClipResult(ok=False, error=f"Snapshot failed: {exc}")
