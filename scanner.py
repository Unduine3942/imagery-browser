from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import nitf
from config import ARCPY_FORMAT_MAP, IMAGERY_EXTENSIONS
from models import ImageryRecord, ImageryScanResult

log = logging.getLogger(__name__)

# Any arcpy failure (ImportError, or RuntimeError when unlicensed) means
# we fall back to the rasterio/GDAL/NITF metadata chain.
try:
    import arcpy
    _ARCPY_AVAILABLE = True
except Exception:
    arcpy = None  # type: ignore[assignment]
    _ARCPY_AVAILABLE = False

try:
    import rasterio as _rasterio
    from rasterio.crs import CRS as _RasterioCRS
    from rasterio.warp import transform_bounds as _rasterio_transform_bounds
    _RASTERIO_AVAILABLE = True
except ImportError:
    _rasterio = None  # type: ignore[assignment]
    _RASTERIO_AVAILABLE = False

try:
    from osgeo import gdal as _gdal, osr as _osr
    _GDAL_AVAILABLE = True
except ImportError:
    _gdal = None  # type: ignore[assignment]
    _osr = None   # type: ignore[assignment]
    _GDAL_AVAILABLE = False


@dataclass
class _GeoMetadata:
    extent_minx: float
    extent_miny: float
    extent_maxx: float
    extent_maxy: float
    spatial_ref_wkid: Optional[int]
    band_count: Optional[int]
    width: Optional[int]
    height: Optional[int]


def scan_imagery_folder(
    folder_path: str,
    recursive: bool = True,
    stop_event: Optional[threading.Event] = None,
) -> ImageryScanResult:
    result = ImageryScanResult()
    root = Path(folder_path).resolve()

    try:
        if root.is_symlink():
            result.warnings.append(f"Cannot scan symbolic link: {folder_path}")
            return result
    except OSError as exc:
        result.warnings.append(f"Cannot access path: {exc}")
        return result

    if not root.exists():
        result.warnings.append(f"Folder not found: {folder_path}")
        return result

    if not root.is_dir():
        result.warnings.append(f"Path is not a directory: {folder_path}")
        return result

    iterator = root.rglob("*") if recursive else root.iterdir()

    for filepath in iterator:
        if stop_event is not None and stop_event.is_set():
            result.cancelled = True
            break
        if not filepath.is_file():
            continue
        if filepath.suffix.lower() not in IMAGERY_EXTENSIONS:
            continue

        record = _build_record(filepath, result.warnings)
        if record is not None:
            result.records.append(record)
            result.processed_count += 1
        else:
            result.failed_count += 1

    result.scan_timestamp = datetime.now()
    return result


def _build_record(filepath: Path, warnings: list[str]) -> Optional[ImageryRecord]:
    try:
        stat = os.stat(filepath)
        file_size = stat.st_size
        ingest_date = datetime.fromtimestamp(stat.st_ctime)
    except OSError as exc:
        warnings.append(f"Cannot stat {filepath.name}: {exc}")
        return None

    fmt = "Unknown"
    extent_minx = extent_miny = extent_maxx = extent_maxy = None
    spatial_ref_wkid: Optional[int] = None
    acquisition_date: Optional[datetime] = None
    band_count: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

    # NITF/CADRG: parse once for NTM metadata + true corner geometry. Cheap
    # (reads only the header) and the sole source of these fields, so we parse
    # even when arcpy supplies the extent.
    nitf_meta = (
        nitf.parse_nitf21(str(filepath))
        if filepath.suffix.lower() in nitf.NITF_EXTENSIONS
        else None
    )

    if _ARCPY_AVAILABLE:
        try:
            desc = arcpy.Describe(str(filepath))
            raw_fmt = getattr(desc, "format", "") or ""
            fmt = ARCPY_FORMAT_MAP.get(raw_fmt.upper(), raw_fmt or _ext_to_format(filepath.suffix))

            ext = getattr(desc, "extent", None)
            if ext is not None:
                extent_minx = float(ext.XMin)
                extent_miny = float(ext.YMin)
                extent_maxx = float(ext.XMax)
                extent_maxy = float(ext.YMax)

            sr = getattr(desc, "spatialReference", None)
            if sr is not None:
                wkid = getattr(sr, "factoryCode", None)
                spatial_ref_wkid = int(wkid) if wkid else None

            raw_acq = getattr(desc, "acquisitionDate", None)
            if raw_acq:
                acquisition_date = _parse_arcpy_date(raw_acq)

            band_count = getattr(desc, "bandCount", None)
            width = getattr(desc, "width", None)
            height = getattr(desc, "height", None)
        except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
            # Not yet a user-facing warning: header-only NITFs (NTM headers
            # with no renderable payload) always fail arcpy.Describe but are
            # fully recovered by the fallback chain below. Only warn when no
            # source can produce an extent.
            log.debug("arcpy.Describe failed for %s (%s): %s", filepath.name, type(exc).__name__, exc)
            arcpy_error = f"arcpy.Describe failed for {filepath.name}: {exc}"
            fmt = _ext_to_format(filepath.suffix)
        else:
            arcpy_error = None

        if extent_minx is None:
            meta = _try_rasterio_metadata(filepath) or _try_gdal_metadata(filepath) or _geo_from_nitf(nitf_meta)
            if meta is not None:
                extent_minx, extent_miny = meta.extent_minx, meta.extent_miny
                extent_maxx, extent_maxy = meta.extent_maxx, meta.extent_maxy
                if spatial_ref_wkid is None:
                    spatial_ref_wkid = meta.spatial_ref_wkid
                if band_count is None:
                    band_count = meta.band_count
                if width is None:
                    width = meta.width
                if height is None:
                    height = meta.height

        if arcpy_error and extent_minx is None:
            warnings.append(arcpy_error)
    else:
        fmt = _ext_to_format(filepath.suffix)
        meta = _try_rasterio_metadata(filepath) or _try_gdal_metadata(filepath) or _geo_from_nitf(nitf_meta)
        if meta is not None:
            extent_minx, extent_miny = meta.extent_minx, meta.extent_miny
            extent_maxx, extent_maxy = meta.extent_maxx, meta.extent_maxy
            spatial_ref_wkid = meta.spatial_ref_wkid
            band_count = meta.band_count
            width = meta.width
            height = meta.height

    return ImageryRecord.make(
        filepath=str(filepath),
        filename=filepath.name,
        fmt=fmt,
        extent_minx=extent_minx,
        extent_miny=extent_miny,
        extent_maxx=extent_maxx,
        extent_maxy=extent_maxy,
        spatial_ref_wkid=spatial_ref_wkid,
        acquisition_date=acquisition_date,
        ingest_date=ingest_date,
        file_size_bytes=file_size,
        band_count=band_count,
        width=width,
        height=height,
        corners=list(nitf_meta.corners) if nitf_meta and nitf_meta.corners else None,
        icords=nitf_meta.icords if nitf_meta else None,
        image_id=nitf_meta.image_id if nitf_meta else None,
        image_title=nitf_meta.image_title if nitf_meta else None,
        image_category=nitf_meta.image_category if nitf_meta else None,
        image_source=nitf_meta.image_source if nitf_meta else None,
        file_title=nitf_meta.file_title if nitf_meta else None,
        classification=(
            (nitf_meta.image_classification or nitf_meta.file_classification)
            if nitf_meta else None
        ),
        num_image_segments=nitf_meta.num_image_segments if nitf_meta else None,
        image_datetime=nitf_meta.image_datetime if nitf_meta else None,
    )


def _try_rasterio_metadata(filepath: Path) -> Optional[_GeoMetadata]:
    if not _RASTERIO_AVAILABLE:
        return None
    try:
        with _rasterio.open(str(filepath)) as src:
            if src.crs is None:
                return None
            wgs84 = _RasterioCRS.from_epsg(4326)
            minx, miny, maxx, maxy = _rasterio_transform_bounds(
                src.crs, wgs84, *src.bounds
            )
            if not (minx < maxx and miny < maxy):
                return None
            wkid = src.crs.to_epsg()
            return _GeoMetadata(
                extent_minx=minx, extent_miny=miny,
                extent_maxx=maxx, extent_maxy=maxy,
                spatial_ref_wkid=int(wkid) if wkid else None,
                band_count=src.count or None,
                width=src.width, height=src.height,
            )
    except Exception as exc:
        log.debug("rasterio metadata failed for %s: %s", filepath.name, exc)
        return None


def _try_gdal_metadata(filepath: Path) -> Optional[_GeoMetadata]:
    if not _GDAL_AVAILABLE:
        return None
    try:
        ds = _gdal.Open(str(filepath), _gdal.GA_ReadOnly)
        if ds is None:
            return None
        gt = ds.GetGeoTransform()
        w, h = ds.RasterXSize, ds.RasterYSize
        x0, y0 = gt[0], gt[3]
        x1 = x0 + gt[1] * w + gt[2] * h
        y1 = y0 + gt[4] * w + gt[5] * h
        minx_n, maxx_n = min(x0, x1), max(x0, x1)
        miny_n, maxy_n = min(y0, y1), max(y0, y1)
        if not (minx_n < maxx_n and miny_n < maxy_n):
            return None
        proj_wkt = ds.GetProjection()
        if not proj_wkt:
            return None
        src_srs = _osr.SpatialReference()
        src_srs.ImportFromWkt(proj_wkt)
        wgs84 = _osr.SpatialReference()
        wgs84.ImportFromEPSG(4326)
        wgs84.SetAxisMappingStrategy(_osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = _osr.CoordinateTransformation(src_srs, wgs84)
        lon0, lat0, _ = ct.TransformPoint(minx_n, miny_n)
        lon1, lat1, _ = ct.TransformPoint(maxx_n, maxy_n)
        minx, miny = min(lon0, lon1), min(lat0, lat1)
        maxx, maxy = max(lon0, lon1), max(lat0, lat1)
        if not (minx < maxx and miny < maxy):
            return None
        wkid = None
        epsg = src_srs.GetAuthorityCode(None)
        if epsg:
            try:
                wkid = int(epsg)
            except ValueError:
                pass
        return _GeoMetadata(
            extent_minx=minx, extent_miny=miny,
            extent_maxx=maxx, extent_maxy=maxy,
            spatial_ref_wkid=wkid,
            band_count=ds.RasterCount or None,
            width=w, height=h,
        )
    except Exception as exc:
        log.debug("GDAL metadata failed for %s: %s", filepath.name, exc)
        return None


def _geo_from_nitf(nitf_meta: "nitf.NitfMetadata | None") -> Optional[_GeoMetadata]:
    """Adapt parsed NitfMetadata to a _GeoMetadata for the extent-fallback chain.

    Returns None when the NITF file yielded no usable geographic extent (e.g.
    an unsupported ICORDS). The richer NTM fields — image id, category, source,
    corner geometry — are read directly from the NitfMetadata in _build_record.
    """
    if nitf_meta is None or nitf_meta.extent_minx is None:
        return None
    return _GeoMetadata(
        extent_minx=nitf_meta.extent_minx,
        extent_miny=nitf_meta.extent_miny,
        extent_maxx=nitf_meta.extent_maxx,
        extent_maxy=nitf_meta.extent_maxy,
        spatial_ref_wkid=nitf_meta.spatial_ref_wkid,
        band_count=None,
        width=nitf_meta.width,
        height=nitf_meta.height,
    )


def _ext_to_format(suffix: str) -> str:
    mapping = {
        ".tif": "GeoTIFF", ".tiff": "GeoTIFF",
        ".nitf": "NITF", ".ntf": "NITF",
        ".jp2": "JPEG2000", ".j2k": "JPEG2000", ".j2c": "JPEG2000",
        ".sid": "SID",
        ".ecw": "ECW",
        ".img": "IMG", ".ers": "IMG",
        ".r0": "CADRG", ".r1": "CADRG", ".r2": "CADRG", ".r3": "CADRG",
        ".r4": "CADRG", ".r5": "CADRG", ".r6": "CADRG", ".r7": "CADRG",
        ".r8": "CADRG", ".r9": "CADRG",
        ".dt0": "DTED", ".dt1": "DTED", ".dt2": "DTED", ".dt3": "DTED",
        ".h4": "HDF", ".h5": "HDF", ".hdf": "HDF", ".hdf5": "HDF",
        ".he4": "HDF", ".he5": "HDF",
        ".mrf": "MRF",
        ".bil": "BIL", ".bip": "BIL", ".bsq": "BIL",
        ".adf": "ArcGrid",
        ".gen": "ADRG",
        ".png": "PNG",
        ".kml": "KML",
        ".kmz": "KML",
    }
    return mapping.get(suffix.lower(), "Unknown")


def _parse_arcpy_date(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
    return None
