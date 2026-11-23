from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_FNAME_RE = re.compile(r"^([^_]+)_(\d{8})_([^_]+)_(.+)$")


def _parse_filename_stem(
    stem: str,
) -> tuple[Optional[str], Optional[datetime], Optional[str], Optional[str]]:
    """Parse SensorPlatform_Date_Type_Name stem into components."""
    m = _FNAME_RE.match(stem)
    if not m:
        return None, None, None, None
    sensor = m.group(1) or None
    date_str = m.group(2)
    img_type = m.group(3) or None
    scene = m.group(4) or None
    try:
        cap_date = datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        cap_date = None
    return sensor, cap_date, img_type, scene


@dataclass(frozen=True)
class ImageryRecord:
    id: str
    filepath: str
    filename: str
    format: str

    # Parsed from SensorPlatform_Date_Type_Name filename convention
    sensor_platform: Optional[str]
    image_type: Optional[str]
    scene_name: Optional[str]

    extent_minx: Optional[float]
    extent_miny: Optional[float]
    extent_maxx: Optional[float]
    extent_maxy: Optional[float]
    centroid_x: Optional[float]
    centroid_y: Optional[float]

    spatial_ref_wkid: Optional[int]
    acquisition_date: Optional[datetime]
    ingest_date: datetime
    file_size_bytes: int

    band_count: Optional[int]
    width: Optional[int]
    height: Optional[int]

    # NITF 2.1 / NTM metadata (optional — populated for NITF/CADRG imagery)
    corners: Optional[tuple[tuple[float, float], ...]] = None  # 4× (lon, lat), file order
    icords: Optional[str] = None              # ICORDS coordinate-system code (G/D/N/S/U)
    image_id: Optional[str] = None            # IID1
    image_title: Optional[str] = None         # IID2
    image_category: Optional[str] = None      # ICAT
    image_source: Optional[str] = None        # ISORCE
    file_title: Optional[str] = None          # FTITLE
    classification: Optional[str] = None       # FSCLAS / ISCLAS
    num_image_segments: Optional[int] = None  # NUMI

    @staticmethod
    def make(
        filepath: str,
        filename: str,
        fmt: str,
        extent_minx: Optional[float],
        extent_miny: Optional[float],
        extent_maxx: Optional[float],
        extent_maxy: Optional[float],
        spatial_ref_wkid: Optional[int],
        acquisition_date: Optional[datetime],
        ingest_date: datetime,
        file_size_bytes: int,
        band_count: Optional[int],
        width: Optional[int],
        height: Optional[int],
        corners: Optional[list[tuple[float, float]]] = None,
        icords: Optional[str] = None,
        image_id: Optional[str] = None,
        image_title: Optional[str] = None,
        image_category: Optional[str] = None,
        image_source: Optional[str] = None,
        file_title: Optional[str] = None,
        classification: Optional[str] = None,
        num_image_segments: Optional[int] = None,
        image_datetime: Optional[datetime] = None,
    ) -> "ImageryRecord":
        stem = Path(filename).stem
        sensor, fname_date, img_type, scene = _parse_filename_stem(stem)
        # Acquisition date precedence: explicit (arcpy) → NITF IDATIM → filename date
        if acquisition_date is None:
            acquisition_date = image_datetime if image_datetime is not None else fname_date
        # Sensor precedence: filename convention → NITF image source (ISORCE)
        if sensor is None and image_source:
            sensor = image_source
        cx = None
        cy = None
        if None not in (extent_minx, extent_miny, extent_maxx, extent_maxy):
            cx = (extent_minx + extent_maxx) / 2.0  # type: ignore[operator]
            cy = (extent_miny + extent_maxy) / 2.0  # type: ignore[operator]
        norm_corners = (
            tuple((float(x), float(y)) for x, y in corners) if corners else None
        )
        return ImageryRecord(
            id=str(uuid.uuid4()),
            filepath=filepath,
            filename=filename,
            format=fmt,
            sensor_platform=sensor,
            image_type=img_type,
            scene_name=scene,
            extent_minx=extent_minx,
            extent_miny=extent_miny,
            extent_maxx=extent_maxx,
            extent_maxy=extent_maxy,
            centroid_x=cx,
            centroid_y=cy,
            spatial_ref_wkid=spatial_ref_wkid,
            acquisition_date=acquisition_date,
            ingest_date=ingest_date,
            file_size_bytes=file_size_bytes,
            band_count=band_count,
            width=width,
            height=height,
            corners=norm_corners,
            icords=icords,
            image_id=image_id,
            image_title=image_title,
            image_category=image_category,
            image_source=image_source,
            file_title=file_title,
            classification=classification,
            num_image_segments=num_image_segments,
        )

    def get_display_name(self) -> str:
        parts = []
        if self.sensor_platform:
            parts.append(self.sensor_platform)
        if self.image_type:
            parts.append(self.image_type)
        if self.scene_name:
            parts.append(self.scene_name)
        if not parts:
            parts.append(self.filename)
        if self.width and self.height:
            parts.append(f"{self.width}x{self.height}")
        if self.band_count:
            parts.append(f"{self.band_count}B")
        return " | ".join(parts)

    def has_extent(self) -> bool:
        return None not in (self.extent_minx, self.extent_miny, self.extent_maxx, self.extent_maxy)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filepath": self.filepath,
            "filename": self.filename,
            "format": self.format,
            "sensor_platform": self.sensor_platform,
            "image_type": self.image_type,
            "scene_name": self.scene_name,
            "extent_minx": self.extent_minx,
            "extent_miny": self.extent_miny,
            "extent_maxx": self.extent_maxx,
            "extent_maxy": self.extent_maxy,
            "centroid_x": self.centroid_x,
            "centroid_y": self.centroid_y,
            "spatial_ref_wkid": self.spatial_ref_wkid,
            "acquisition_date": self.acquisition_date.isoformat() if self.acquisition_date else None,
            "ingest_date": self.ingest_date.isoformat(),
            "file_size_bytes": self.file_size_bytes,
            "band_count": self.band_count,
            "width": self.width,
            "height": self.height,
            "corners": [list(c) for c in self.corners] if self.corners else None,
            "icords": self.icords,
            "image_id": self.image_id,
            "image_title": self.image_title,
            "image_category": self.image_category,
            "image_source": self.image_source,
            "file_title": self.file_title,
            "classification": self.classification,
            "num_image_segments": self.num_image_segments,
        }

    @staticmethod
    def from_dict(d: dict) -> "ImageryRecord":
        acq = datetime.fromisoformat(d["acquisition_date"]) if d.get("acquisition_date") else None
        ing = datetime.fromisoformat(d["ingest_date"])
        raw_corners = d.get("corners")
        corners = (
            tuple((float(c[0]), float(c[1])) for c in raw_corners) if raw_corners else None
        )
        return ImageryRecord(
            id=d["id"],
            filepath=d["filepath"],
            filename=d["filename"],
            format=d["format"],
            sensor_platform=d.get("sensor_platform"),
            image_type=d.get("image_type"),
            scene_name=d.get("scene_name"),
            extent_minx=d.get("extent_minx"),
            extent_miny=d.get("extent_miny"),
            extent_maxx=d.get("extent_maxx"),
            extent_maxy=d.get("extent_maxy"),
            centroid_x=d.get("centroid_x"),
            centroid_y=d.get("centroid_y"),
            spatial_ref_wkid=d.get("spatial_ref_wkid"),
            acquisition_date=acq,
            ingest_date=ing,
            file_size_bytes=d.get("file_size_bytes", 0),
            band_count=d.get("band_count"),
            width=d.get("width"),
            height=d.get("height"),
            corners=corners,
            icords=d.get("icords"),
            image_id=d.get("image_id"),
            image_title=d.get("image_title"),
            image_category=d.get("image_category"),
            image_source=d.get("image_source"),
            file_title=d.get("file_title"),
            classification=d.get("classification"),
            num_image_segments=d.get("num_image_segments"),
        )


@dataclass
class ImageryScanResult:
    records: list[ImageryRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scan_timestamp: datetime = field(default_factory=datetime.now)
    processed_count: int = 0
    failed_count: int = 0
    cancelled: bool = False


@dataclass
class DownloadResult:
    success_count: int = 0
    failed_count: int = 0
    dest_path: str = ""
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Downloaded {self.success_count} file(s) to:\n{self.dest_path}"]
        if self.failed_count:
            lines.append(f"\n{self.failed_count} file(s) failed:")
            lines.extend(f"  • {e}" for e in self.errors[:5])
        return "\n".join(lines)
