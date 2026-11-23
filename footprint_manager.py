from __future__ import annotations

import logging
import re
from typing import Optional

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
)

from config import FOOTPRINT_LAYER_NAME, MEMORY_FC_PATH
from models import ImageryRecord

log = logging.getLogger(__name__)

# arcpy raises RuntimeError ("Product License has not been initialized")
# rather than ImportError when no ArcGIS license is active, so any failure
# must drop us into canvas-only mode.
try:
    import arcpy
    _ARCPY_AVAILABLE = True
except Exception:
    arcpy = None  # type: ignore[assignment]
    _ARCPY_AVAILABLE = False


class FootprintManager:
    """Manages an in-memory arcpy feature class displayed in the active ArcGIS Pro map."""

    def __init__(self, aprx_path: Optional[str] = None) -> None:
        self._aprx_path = aprx_path
        self._layer_ref = None  # reference to the added layer object

    # -- public API --

    def add_records_to_map(self, records: list[ImageryRecord]) -> bool:
        if not _ARCPY_AVAILABLE:
            log.warning("arcpy not available; skipping footprint layer creation.")
            return False

        aprx, active_map = self._get_map()
        if active_map is None:
            return False

        spatial_records = [r for r in records if r.has_extent()]
        if not spatial_records:
            log.warning("No records with valid extents; nothing added to map.")
            return False

        try:
            self._build_memory_fc(spatial_records)
        except Exception as exc:
            log.error("Failed to build memory feature class: %s", exc)
            return False

        try:
            self._layer_ref = active_map.addDataFromPath(MEMORY_FC_PATH)
            self._apply_hollow_symbology()
            return True
        except Exception as exc:
            log.error("Failed to add footprints layer to map: %s", exc)
            return False

    def update_filter_query(self, visible_ids: list[str]) -> bool:
        if not _ARCPY_AVAILABLE or self._layer_ref is None:
            return False
        try:
            if not visible_ids:
                self._layer_ref.definitionQuery = "1=0"
            else:
                # SECURITY: UUID validation is the only barrier between visible_ids
                # and the ArcGIS definition query string. Do not weaken or remove this check.
                invalid = [i for i in visible_ids if not _UUID_RE.match(i)]
                if invalid:
                    log.error("Refusing to build query: non-UUID record IDs detected: %s", invalid[:5])
                    return False
                joined = "','".join(visible_ids)
                # Filter on the internal record UUID (record_id), not the NITF image id.
                self._layer_ref.definitionQuery = f"record_id IN ('{joined}')"
            return True
        except Exception as exc:
            log.error("Failed to update definition query: %s", exc)
            return False

    def clear_footprints(self) -> bool:
        if not _ARCPY_AVAILABLE:
            return False
        _, active_map = self._get_map()
        if active_map is None:
            return False
        try:
            layers = [l for l in active_map.listLayers() if l.name == FOOTPRINT_LAYER_NAME]
            for lyr in layers:
                active_map.removeLayer(lyr)
            self._layer_ref = None
            if arcpy.Exists(MEMORY_FC_PATH):
                arcpy.management.Delete(MEMORY_FC_PATH)
            return True
        except Exception as exc:
            log.error("Failed to clear footprints: %s", exc)
            return False

    # -- private helpers --

    def _get_map(self):
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
        except Exception:
            if self._aprx_path:
                try:
                    aprx = arcpy.mp.ArcGISProject(self._aprx_path)
                except Exception as exc:
                    log.error("Cannot open project %s: %s", self._aprx_path, exc)
                    return None, None
            else:
                log.warning("No active ArcGIS Pro project and no aprx path provided.")
                return None, None

        active_map = aprx.activeMap
        if active_map is None:
            log.warning("No active map in the ArcGIS Pro project.")
            return aprx, None
        return aprx, active_map

    def _build_memory_fc(self, records: list[ImageryRecord]) -> None:
        if arcpy.Exists(MEMORY_FC_PATH):
            arcpy.management.Delete(MEMORY_FC_PATH)

        sr = arcpy.SpatialReference(4326)  # WGS84 default; records may vary
        arcpy.management.CreateFeatureclass("memory", FOOTPRINT_LAYER_NAME, "POLYGON",
                                            spatial_reference=sr)
        # record_id holds the internal UUID used by the definition query;
        # nitf_image_id holds the NITF IID1 so analysts see the real image id.
        arcpy.management.AddField(MEMORY_FC_PATH, "record_id", "TEXT", field_length=40)
        arcpy.management.AddField(MEMORY_FC_PATH, "nitf_image_id", "TEXT", field_length=80)
        arcpy.management.AddField(MEMORY_FC_PATH, "filename",  "TEXT", field_length=255)
        arcpy.management.AddField(MEMORY_FC_PATH, "img_format","TEXT", field_length=50)
        arcpy.management.AddField(MEMORY_FC_PATH, "img_category","TEXT", field_length=16)
        arcpy.management.AddField(MEMORY_FC_PATH, "img_source","TEXT", field_length=64)
        arcpy.management.AddField(MEMORY_FC_PATH, "acq_date",  "DATE")
        arcpy.management.AddField(MEMORY_FC_PATH, "ing_date",  "DATE")
        arcpy.management.AddField(MEMORY_FC_PATH, "size_bytes","LONG")

        fields = ["SHAPE@", "record_id", "nitf_image_id", "filename", "img_format",
                  "img_category", "img_source", "acq_date", "ing_date", "size_bytes"]
        with arcpy.da.InsertCursor(MEMORY_FC_PATH, fields) as cur:
            for r in records:
                polygon = self._make_polygon(
                    r.extent_minx, r.extent_miny, r.extent_maxx, r.extent_maxy,
                    r.spatial_ref_wkid, r.corners,
                )
                cur.insertRow([
                    polygon,
                    r.id,
                    r.image_id,
                    r.filename,
                    r.format,
                    r.image_category,
                    r.image_source,
                    r.acquisition_date,
                    r.ingest_date,
                    r.file_size_bytes,
                ])

    def _make_polygon(
        self,
        xmin: float, ymin: float, xmax: float, ymax: float,
        wkid: Optional[int],
        corners: Optional[tuple[tuple[float, float], ...]] = None,
    ) -> "arcpy.Polygon":
        # True four-corner geometry (NITF IGEOLO) when available — renders the
        # real, non-rectangular NTM footprint. Corners are WGS84 lon/lat.
        if corners and len(corners) == 4:
            pts = [arcpy.Point(lon, lat) for lon, lat in corners]
            pts.append(pts[0])  # close the ring
            return arcpy.Polygon(arcpy.Array(pts), arcpy.SpatialReference(4326))

        # Fallback: axis-aligned bounding box.
        sr = arcpy.SpatialReference(wkid if wkid else 4326)
        array = arcpy.Array([
            arcpy.Point(xmin, ymin),
            arcpy.Point(xmin, ymax),
            arcpy.Point(xmax, ymax),
            arcpy.Point(xmax, ymin),
            arcpy.Point(xmin, ymin),
        ])
        return arcpy.Polygon(array, sr)

    def _apply_hollow_symbology(self) -> None:
        if self._layer_ref is None:
            return
        try:
            sym = self._layer_ref.symbology
            sym.renderer.symbol.color = {"RGB": [0, 0, 0, 0]}       # transparent fill
            sym.renderer.symbol.outlineColor = {"RGB": [255, 165, 0, 255]}  # orange outline
            sym.renderer.symbol.outlineWidth = 1.5
            self._layer_ref.symbology = sym
        except Exception as exc:
            log.warning("Could not apply footprint symbology: %s", exc)
