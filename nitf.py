"""Dependency-free NITF 2.1 metadata reader (MIL-STD-2500C).

Extracts file-level collection naming and image-subheader metadata used by NTM /
commercial (NCDRD-style) imagery — image ID, date/time, category, source,
classification, segment count — plus the four geographic corner coordinates from
the IGEOLO field.  CADRG ``.r0``–``.r9`` zone files and plain ``.ntf``/``.nitf``
files share the NITF wrapper, so a single parser serves both.

Byte offsets are derived from the spec field-length tables (cumulative sums)
rather than hand-typed absolute constants, which removes the whole class of
off-by-one errors and makes adding fields trivial.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ui.mgrs import utm_to_latlon

log = logging.getLogger(__name__)

_MAGIC = b"NITF"
_VERSION_21 = b"02.10"

# Extensions that wrap their payload in a NITF container.
NITF_EXTENSIONS: frozenset[str] = frozenset({
    ".ntf", ".nitf",
    ".r0", ".r1", ".r2", ".r3", ".r4",
    ".r5", ".r6", ".r7", ".r8", ".r9",
})

# File header fields up to and including NUMI (MIL-STD-2500C Table A-1).
_FILE_HEADER_FIELDS = [
    ("FHDR", 9), ("CLEVEL", 2), ("STYPE", 4), ("OSTAID", 10), ("FDT", 14),
    ("FTITLE", 80), ("FSCLAS", 1), ("FSCLSY", 2), ("FSCODE", 11), ("FSCTLH", 2),
    ("FSREL", 20), ("FSDCTP", 2), ("FSDCDT", 8), ("FSDCXM", 4), ("FSDG", 1),
    ("FSDGDT", 8), ("FSCLTX", 43), ("FSCATP", 1), ("FSCAUT", 40), ("FSCRSN", 1),
    ("FSSRDT", 8), ("FSCTLN", 15), ("FSCOP", 5), ("FSCPYS", 5), ("ENCRYP", 1),
    ("FBKGC", 3), ("ONAME", 24), ("OPHONE", 18), ("FL", 12), ("HL", 6), ("NUMI", 3),
]

# Image subheader fields up to and including ICORDS (MIL-STD-2500C Table A-3).
# The NITF 2.1 security block is fixed-width and always present, so every offset
# below is deterministic for the first image segment.  IGEOLO (60 bytes) follows
# ICORDS only when ICORDS is not blank.
_IMAGE_SUBHEADER_FIELDS = [
    ("IM", 2), ("IID1", 10), ("IDATIM", 14), ("TGTID", 17), ("IID2", 80),
    ("ISCLAS", 1), ("ISCLSY", 2), ("ISCODE", 11), ("ISCTLH", 2), ("ISREL", 20),
    ("ISDCTP", 2), ("ISDCDT", 8), ("ISDCXM", 4), ("ISDG", 1), ("ISDGDT", 8),
    ("ISCLTX", 43), ("ISCATP", 1), ("ISCAUT", 40), ("ISCRSN", 1), ("ISSRDT", 8),
    ("ISCTLN", 15), ("ENCRYP", 1), ("ISORCE", 42), ("NROWS", 8), ("NCOLS", 8),
    ("PVTYPE", 3), ("IREP", 8), ("ICAT", 8), ("ABPP", 2), ("PJUST", 1), ("ICORDS", 1),
]

_IGEOLO_LEN = 60


def _build_layout(fields: list[tuple[str, int]]) -> tuple[dict[str, tuple[int, int]], int]:
    """Return ({name: (offset, length)}, total_length) from a field-length list."""
    offsets: dict[str, tuple[int, int]] = {}
    pos = 0
    for name, length in fields:
        offsets[name] = (pos, length)
        pos += length
    return offsets, pos


_FH_LAYOUT, _FH_LEN = _build_layout(_FILE_HEADER_FIELDS)            # _FH_LEN == 363
_IS_LAYOUT, _IS_LEN = _build_layout(_IMAGE_SUBHEADER_FIELDS)        # _IS_LEN == 372
_IGEOLO_OFFSET = _IS_LEN                                            # IGEOLO starts at 372
_MIN_SUBHEADER_LEN = _IGEOLO_OFFSET + _IGEOLO_LEN                   # 432


@dataclass(frozen=True)
class NitfMetadata:
    """Parsed NITF 2.1 metadata.  Geo fields are None when ICORDS is unsupported."""
    # File-level
    file_title: Optional[str]
    file_datetime: Optional[datetime]
    originating_station: Optional[str]
    file_classification: Optional[str]
    num_image_segments: Optional[int]
    # Image subheader
    image_id: Optional[str]
    image_title: Optional[str]
    image_datetime: Optional[datetime]
    image_category: Optional[str]
    image_source: Optional[str]
    image_classification: Optional[str]
    # Geometry
    icords: Optional[str]
    corners: Optional[tuple[tuple[float, float], ...]]  # 4× (lon, lat), file order
    extent_minx: Optional[float]
    extent_miny: Optional[float]
    extent_maxx: Optional[float]
    extent_maxy: Optional[float]
    spatial_ref_wkid: Optional[int]
    width: Optional[int]
    height: Optional[int]


def _text(buf: bytes, layout: dict[str, tuple[int, int]], name: str) -> str:
    off, length = layout[name]
    return buf[off:off + length].decode("ascii", errors="replace").strip()


def _int_or_none(value: str) -> Optional[int]:
    value = value.strip()
    return int(value) if value.isdigit() else None


def _parse_nitf_datetime(value: str) -> Optional[datetime]:
    """Parse a NITF CCYYMMDDhhmmss timestamp; tolerate blank/hyphen fill."""
    value = value.strip()
    if len(value) != 14 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _parse_corners(icords: str, igeolo: str) -> Optional[list[tuple[float, float]]]:
    """Parse the 4 IGEOLO corners into (lon, lat) pairs for the given ICORDS type."""
    corners: list[tuple[float, float]] = []
    try:
        if icords == "G":  # ddmmssH (lat, 7) + dddmmssH (lon, 8) per corner
            for i in range(4):
                off = i * 15
                lat_s, lon_s = igeolo[off:off + 7], igeolo[off + 7:off + 15]
                lat = int(lat_s[:2]) + int(lat_s[2:4]) / 60.0 + int(lat_s[4:6]) / 3600.0
                if lat_s[6] == "S":
                    lat = -lat
                lon = int(lon_s[:3]) + int(lon_s[3:5]) / 60.0 + int(lon_s[5:7]) / 3600.0
                if lon_s[7] == "W":
                    lon = -lon
                corners.append((lon, lat))
        elif icords == "D":  # ±dd.ddd (lat, 7) + ±ddd.ddd (lon, 8) per corner
            for i in range(4):
                off = i * 15
                lat = float(igeolo[off:off + 7])
                lon = float(igeolo[off + 7:off + 15])
                corners.append((lon, lat))
        elif icords in ("N", "S"):  # zone(2) + easting(6) + northing(7) per corner
            northern = icords == "N"
            for i in range(4):
                off = i * 15
                zone = int(igeolo[off:off + 2])
                easting = int(igeolo[off + 2:off + 8])
                northing = int(igeolo[off + 8:off + 15])
                lat, lon = utm_to_latlon(zone, easting, northing, northern)
                corners.append((lon, lat))
        else:
            # ICORDS 'U' (MGRS-packed IGEOLO) is not yet supported. TODO: decode
            # the per-corner MGRS strings via ui.mgrs and convert to lat/lon.
            return None
    except (ValueError, IndexError):
        return None
    return corners if len(corners) == 4 else None


def parse_nitf21(filepath: str) -> Optional[NitfMetadata]:
    """Parse a NITF 2.1 file's first image segment; return None on any failure."""
    try:
        with open(filepath, "rb") as f:
            fh = f.read(400)
            if len(fh) < _FH_LEN or fh[:4] != _MAGIC or fh[4:9] != _VERSION_21:
                return None

            hl = _int_or_none(_text(fh, _FH_LAYOUT, "HL"))
            if hl is None:
                return None

            f.seek(hl)
            ish = f.read(500)

        if len(ish) < _MIN_SUBHEADER_LEN or ish[:2] != b"IM":
            return None

        icords = chr(ish[_IS_LAYOUT["ICORDS"][0]])
        corners = None
        if icords not in (" ", ""):
            igeolo = ish[_IGEOLO_OFFSET:_IGEOLO_OFFSET + _IGEOLO_LEN].decode("ascii", errors="replace")
            corners = _parse_corners(icords, igeolo)

        minx = miny = maxx = maxy = None
        wkid = None
        if corners is not None:
            lons = [c[0] for c in corners]
            lats = [c[1] for c in corners]
            minx, maxx = min(lons), max(lons)
            miny, maxy = min(lats), max(lats)
            if not (minx < maxx and miny < maxy):
                corners = minx = miny = maxx = maxy = None
            else:
                wkid = 4326

        return NitfMetadata(
            file_title=_text(fh, _FH_LAYOUT, "FTITLE") or None,
            file_datetime=_parse_nitf_datetime(_text(fh, _FH_LAYOUT, "FDT")),
            originating_station=_text(fh, _FH_LAYOUT, "OSTAID") or None,
            file_classification=_text(fh, _FH_LAYOUT, "FSCLAS") or None,
            num_image_segments=_int_or_none(_text(fh, _FH_LAYOUT, "NUMI")),
            image_id=_text(ish, _IS_LAYOUT, "IID1") or None,
            image_title=_text(ish, _IS_LAYOUT, "IID2") or None,
            image_datetime=_parse_nitf_datetime(_text(ish, _IS_LAYOUT, "IDATIM")),
            image_category=_text(ish, _IS_LAYOUT, "ICAT") or None,
            image_source=_text(ish, _IS_LAYOUT, "ISORCE") or None,
            image_classification=_text(ish, _IS_LAYOUT, "ISCLAS") or None,
            icords=icords if icords.strip() else None,
            corners=tuple(corners) if corners is not None else None,
            extent_minx=minx, extent_miny=miny, extent_maxx=maxx, extent_maxy=maxy,
            spatial_ref_wkid=wkid,
            width=_int_or_none(_text(ish, _IS_LAYOUT, "NCOLS")),
            height=_int_or_none(_text(ish, _IS_LAYOUT, "NROWS")),
        )
    except OSError as exc:
        log.debug("NITF read failed for %s: %s", filepath, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — never let a malformed file crash a scan
        log.debug("NITF parse failed for %s: %s", filepath, exc)
        return None
