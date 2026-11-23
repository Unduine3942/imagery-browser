from __future__ import annotations

from pathlib import Path


def _load_version() -> str:
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text(
            encoding="utf-8").strip()
    except OSError:
        return "unknown"


APP_VERSION = _load_version()

IMAGERY_EXTENSIONS: set[str] = {
    # GeoTIFF / TIFF
    ".tif", ".tiff",
    # NITF / NTF
    ".nitf", ".ntf",
    # JPEG2000
    ".jp2", ".j2k", ".j2c",
    # MrSID
    ".sid",
    # ECW
    ".ecw",
    # ERDAS Imagine / ERS
    ".img", ".ers",
    # CADRG / RPF  (R0–R9 zone files)
    ".r0", ".r1", ".r2", ".r3", ".r4",
    ".r5", ".r6", ".r7", ".r8", ".r9",
    # DTED elevation
    ".dt0", ".dt1", ".dt2", ".dt3",
    # HDF / HDF-EOS
    ".h4", ".h5", ".hdf", ".hdf5", ".he4", ".he5",
    # Meta Raster Format (ArcGIS)
    ".mrf",
    # Band-interleaved rasters
    ".bil", ".bip", ".bsq",
    # ArcInfo binary grid
    ".adf",
    # ADRG / SRP
    ".gen",
    # PNG (plain or georeferenced with world file)
    ".png",
    # KML / KMZ
    ".kml", ".kmz",
}

ARCGIS_MIN_VERSION = "3.3"

FORMAT_COLORS: dict[str, str] = {
    "GeoTIFF":  "#4472c4",
    "NITF":     "#e74c3c",
    "JPEG2000": "#27ae60",
    "SID":      "#f39c12",
    "ECW":      "#9b59b6",
    "IMG":      "#34495e",
    "CADRG":    "#c0392b",
    "DTED":     "#16a085",
    "HDF":      "#8e44ad",
    "MRF":      "#1abc9c",
    "BIL":      "#d35400",
    "ArcGrid":  "#2c3e50",
    "ADRG":     "#e67e22",
    "PNG":      "#3498db",
    "KML":      "#e8b84b",
    "Unknown":  "#7f8c8d",
}

# Footprint colors keyed by image type from filename (SensorPlatform_Date_Type_Name)
IMAGE_TYPE_COLORS: dict[str, str] = {
    "PAN":  "#4472c4",   # blue  — panchromatic
    "MS":   "#27ae60",   # green — multispectral
    "MUL":  "#2ecc71",   # light green — multispectral (alt)
    "PSM":  "#1abc9c",   # teal — pan-sharpened
    "RGB":  "#16a085",   # dark teal — visible RGB
    "IR":   "#e74c3c",   # red — infrared
    "NIR":  "#c0392b",   # dark red — near-infrared
    "SAR":  "#9b59b6",   # purple — synthetic aperture radar
    "HSP":  "#8e44ad",   # dark purple — hyperspectral
    "TIR":  "#e67e22",   # orange — thermal infrared
    "EO":   "#f39c12",   # amber — electro-optical
}

# Footprint colors keyed by NITF image category (ICAT, MIL-STD-2500C).
# Used to color NTM footprints; falls back to IMAGE_TYPE_COLORS then gray.
ICAT_COLORS: dict[str, str] = {
    "VIS":  "#4472c4",   # blue   — visible
    "EO":   "#f39c12",   # amber  — electro-optical
    "OP":   "#e8b84b",   # gold   — optical
    "MS":   "#27ae60",   # green  — multispectral
    "HS":   "#8e44ad",   # purple — hyperspectral
    "IR":   "#e74c3c",   # red    — infrared
    "TI":   "#e67e22",   # orange — thermal infrared
    "FL":   "#d35400",   # dk orange — forward-looking IR
    "SAR":  "#9b59b6",   # purple — synthetic aperture radar
    "SARIQ":"#8e44ad",   # dk purple — SAR phase history
    "RD":   "#c0392b",   # dk red — radar
    "HR":   "#16a085",   # teal   — high-res radar
    "VD":   "#1abc9c",   # turquoise — video
    "MAP":  "#34495e",   # slate  — map
    "DTEM": "#2c3e50",   # dk slate — elevation
}

# Human-readable ICAT labels for the details panel and legend.
ICAT_LABELS: dict[str, str] = {
    "VIS": "Visible", "EO": "Electro-Optical", "OP": "Optical",
    "MS": "Multispectral", "HS": "Hyperspectral", "IR": "Infrared",
    "TI": "Thermal IR", "FL": "Forward-Looking IR", "SAR": "SAR",
    "SARIQ": "SAR Phase History", "RD": "Radar", "HR": "High-Res Radar",
    "VD": "Video", "MAP": "Map", "DTEM": "Elevation (DTED)",
}

# Map arcpy format strings to display names
ARCPY_FORMAT_MAP: dict[str, str] = {
    "TIFF":     "GeoTIFF",
    "GEOTIFF":  "GeoTIFF",
    "TIF":      "GeoTIFF",
    "NITF":     "NITF",
    "NTF":      "NITF",
    "JP2":      "JPEG2000",
    "JPEG2000": "JPEG2000",
    "SID":      "SID",
    "MrSID":    "SID",
    "ECW":      "ECW",
    "IMG":      "IMG",
    "HFA":      "IMG",
    "ERS":      "IMG",
    "CADRG":    "CADRG",
    "RPF":      "CADRG",
    "DTED":     "DTED",
    "HDF":      "HDF",
    "HDF4":     "HDF",
    "HDF5":     "HDF",
    "MRF":      "MRF",
    "BIL":      "BIL",
    "BSQ":      "BIL",
    "BIP":      "BIL",
    "ADF":      "ArcGrid",
    "ADRG":     "ADRG",
    "SRP":      "ADRG",
    "PNG":      "PNG",
    "KML":      "KML",
    "KMZ":      "KML",
}

FOOTPRINT_LAYER_NAME = "Imagery_Footprints"
MEMORY_FC_PATH = "memory/Imagery_Footprints"

# Maximum on-disk size for a user-supplied basemap raster (startup validation).
# Large georeferenced rasters (e.g. Natural Earth HYP_HR_SR_OB_DR ~667 MB) are
# loaded with decimated/downsampled reads, so the cap only guards against
# accidentally selecting an unreasonably large file.
MAX_BASEMAP_MB = 2048
MAX_BASEMAP_BYTES = MAX_BASEMAP_MB * 1024 * 1024

# PIL-fallback working resolution (long axis) — used ONLY when neither GDAL nor
# rasterio is available. In that mode the whole raster is downsampled to this cap
# once and cropped/scaled, so it bounds zoomed-in sharpness. Higher = sharper but
# more RAM: 4096 ≈ 34 MB, 8192 ≈ 134 MB, 16384 ≈ 537 MB (RGBA resident).
# With GDAL or rasterio present (incl. ArcGIS Pro), this is irrelevant — the map
# keeps a small preview and reads the visible window at native resolution on demand.
MAX_BASEMAP_PX = 16384

DATE_RANGE_OPTIONS = ["Any Date", "Last 30 Days", "Last 90 Days", "Last Year", "Custom Range"]
SORT_KEYS = ["scene_name", "sensor_platform", "image_type", "image_category", "image_id", "acquisition_date", "ingest_date", "file_size"]
SORT_LABELS = ["Scene Name", "Sensor/Platform", "Image Type", "Category", "Image ID", "Date", "Ingest Date", "File Size"]
