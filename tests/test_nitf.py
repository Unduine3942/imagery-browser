"""Tests for the pure-Python NITF 2.1 reader (nitf.py).

These tests build synthetic NITF 2.1 files **field by field from the spec
(name, length) layout** (MIL-STD-2500C, Tables A-1 file header and A-3 image
subheader).  The layout here is an INDEPENDENT copy of the spec, deliberately
not imported from nitf.py, so the test acts as a cross-check: if the parser's
byte offsets are wrong (e.g. the historical off-by-one), these tests fail.
"""
from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path

import pytest

import nitf
from ui.mgrs import utm_to_latlon

# ---------------------------------------------------------------------------
# Independent spec layout (do NOT import from nitf.py — this is the cross-check)
# ---------------------------------------------------------------------------

# File header fields up to and including NUMI (MIL-STD-2500C Table A-1).
_FILE_HEADER_FIELDS = [
    ("FHDR", 9), ("CLEVEL", 2), ("STYPE", 4), ("OSTAID", 10), ("FDT", 14),
    ("FTITLE", 80), ("FSCLAS", 1), ("FSCLSY", 2), ("FSCODE", 11), ("FSCTLH", 2),
    ("FSREL", 20), ("FSDCTP", 2), ("FSDCDT", 8), ("FSDCXM", 4), ("FSDG", 1),
    ("FSDGDT", 8), ("FSCLTX", 43), ("FSCATP", 1), ("FSCAUT", 40), ("FSCRSN", 1),
    ("FSSRDT", 8), ("FSCTLN", 15), ("FSCOP", 5), ("FSCPYS", 5), ("ENCRYP", 1),
    ("FBKGC", 3), ("ONAME", 24), ("OPHONE", 18), ("FL", 12), ("HL", 6), ("NUMI", 3),
]

# Image subheader fields up to and including ICORDS (IGEOLO appended separately).
_IMAGE_SUBHEADER_FIELDS = [
    ("IM", 2), ("IID1", 10), ("IDATIM", 14), ("TGTID", 17), ("IID2", 80),
    ("ISCLAS", 1), ("ISCLSY", 2), ("ISCODE", 11), ("ISCTLH", 2), ("ISREL", 20),
    ("ISDCTP", 2), ("ISDCDT", 8), ("ISDCXM", 4), ("ISDG", 1), ("ISDGDT", 8),
    ("ISCLTX", 43), ("ISCATP", 1), ("ISCAUT", 40), ("ISCRSN", 1), ("ISSRDT", 8),
    ("ISCTLN", 15), ("ENCRYP", 1), ("ISORCE", 42), ("NROWS", 8), ("NCOLS", 8),
    ("PVTYPE", 3), ("IREP", 8), ("ICAT", 8), ("ABPP", 2), ("PJUST", 1), ("ICORDS", 1),
]

_NUMERIC = {"FL", "HL", "NUMI", "NROWS", "NCOLS", "FSCOP", "FSCPYS"}

_IGEOLO_LEN = 60
_FH_FIXED_LEN = sum(n for _, n in _FILE_HEADER_FIELDS)        # 363
_SEG_PTR_LEN = 6 + 10                                          # LISH + LI per image


def _encode(name: str, length: int, value) -> bytes:
    if isinstance(value, bytes):
        b = value
    elif name in _NUMERIC:
        b = str(value).encode("ascii").rjust(length, b"0")
    else:
        b = str(value).encode("ascii").ljust(length, b" ")
    if len(b) != length:
        raise ValueError(f"field {name}: value {value!r} -> {len(b)} bytes, expected {length}")
    return b


def _join(fields, values: dict) -> bytes:
    return b"".join(_encode(name, length, values.get(name, "")) for name, length in fields)


def igeolo_g(corners_dms: list[str]) -> str:
    """Join 4 corner DMS strings (each 15 chars: ddmmssH + dddmmssH)."""
    assert len(corners_dms) == 4 and all(len(c) == 15 for c in corners_dms)
    return "".join(corners_dms)


def igeolo_d(corners: list[tuple[float, float]]) -> str:
    """Build a decimal-degree IGEOLO (each corner: +dd.ddd +ddd.ddd = 7 + 8)."""
    out = []
    for lat, lon in corners:
        out.append(f"{lat:+07.3f}"[:7] + f"{lon:+08.3f}"[:8])
    s = "".join(out)
    assert len(s) == 60, len(s)
    return s


def igeolo_utm(corners: list[tuple[int, int, int]]) -> str:
    """Build a UTM IGEOLO (each corner: zz eeeeee nnnnnnn = 2 + 6 + 7)."""
    out = [f"{z:02d}{e:06d}{n:07d}" for z, e, n in corners]
    s = "".join(out)
    assert len(s) == 60, len(s)
    return s


def build_nitf21(
    *,
    fhdr: bytes = b"NITF02.10",
    numi: int = 1,
    icords: str = "G",
    igeolo: str | None = None,
    values: dict | None = None,
    data: bytes = b"\x00" * 16,
    truncate: int | None = None,
) -> bytes:
    """Assemble a minimal valid single-image NITF 2.1 file from field lengths."""
    fh_vals = {
        "FHDR": fhdr, "CLEVEL": "03", "STYPE": "BF01", "OSTAID": "TESTSTN001",
        "FDT": "20250115120000", "FTITLE": "NTM TEST COLLECTION ALPHA",
        "FSCLAS": "U", "FSCOP": 0, "FSCPYS": 0, "ENCRYP": "0",
        "FBKGC": b"\x00\x00\x00", "NUMI": numi,
    }
    img_vals = {
        "IM": "IM", "IID1": "TESTIMG001", "IDATIM": "20250115120000",
        "IID2": "NTM commercial scene alpha", "ISCLAS": "U", "ENCRYP": "0",
        "ISORCE": "TESTSENSOR-1", "NROWS": 1024, "NCOLS": 2048,
        "PVTYPE": "INT", "IREP": "MONO", "ICAT": "VIS", "ABPP": "08",
        "PJUST": "R", "ICORDS": icords,
    }
    if values:
        for k, v in values.items():
            (fh_vals if k in dict(_FILE_HEADER_FIELDS) else img_vals)[k] = v

    subheader = _join(_IMAGE_SUBHEADER_FIELDS, img_vals)
    if icords != " " and igeolo is not None:
        subheader += igeolo.encode("ascii")

    lish = len(subheader)
    li = len(data)
    hl = _FH_FIXED_LEN + numi * _SEG_PTR_LEN
    fl = hl + numi * (lish + li)
    fh_vals["HL"] = hl
    fh_vals["FL"] = fl

    header = _join(_FILE_HEADER_FIELDS, fh_vals)
    for _ in range(numi):
        header += _encode("LISH", 6, str(lish).rjust(6, "0").encode())
        header += _encode("LI", 10, str(li).rjust(10, "0").encode())
    assert len(header) == hl, (len(header), hl)

    blob = header + subheader + data
    if truncate is not None:
        blob = blob[:truncate]
    return blob


# Default skewed quadrilateral (ICORDS='G'): UL, UR, LR, LL  -> (lon, lat)
_DEFAULT_CORNERS_DMS = [
    "340000N" "1170000W",   # UL  (-117.0, 34.0)
    "340000N" "1160000W",   # UR  (-116.0, 34.0)
    "330000N" "1163000W",   # LR  (-116.5, 33.0)
    "330000N" "1173000W",   # LL  (-117.5, 33.0)
]
_EXPECTED_CORNERS = [(-117.0, 34.0), (-116.0, 34.0), (-116.5, 33.0), (-117.5, 33.0)]


def _write(tmp_path: Path, blob: bytes, suffix: str = ".ntf") -> str:
    p = tmp_path / f"sample{suffix}"
    p.write_bytes(blob)
    return str(p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseHeaderFields:
    def test_file_and_image_fields_geographic(self, tmp_path):
        blob = build_nitf21(icords="G", igeolo=igeolo_g(_DEFAULT_CORNERS_DMS))
        meta = nitf.parse_nitf21(_write(tmp_path, blob))
        assert meta is not None

        # File-level collection naming
        assert meta.file_title == "NTM TEST COLLECTION ALPHA"
        assert meta.originating_station == "TESTSTN001"
        assert meta.file_classification == "U"
        assert meta.file_datetime == datetime(2025, 1, 15, 12, 0, 0)
        assert meta.num_image_segments == 1

        # Image subheader
        assert meta.image_id == "TESTIMG001"
        assert meta.image_title == "NTM commercial scene alpha"
        assert meta.image_datetime == datetime(2025, 1, 15, 12, 0, 0)
        assert meta.image_category == "VIS"
        assert meta.image_source == "TESTSENSOR-1"
        assert meta.image_classification == "U"
        assert meta.icords == "G"

        # Dimensions (NROWS/NCOLS)
        assert meta.height == 1024
        assert meta.width == 2048

    def test_geographic_corners_and_bbox(self, tmp_path):
        blob = build_nitf21(icords="G", igeolo=igeolo_g(_DEFAULT_CORNERS_DMS))
        meta = nitf.parse_nitf21(_write(tmp_path, blob))
        assert meta is not None
        assert meta.corners is not None and len(meta.corners) == 4
        for (glon, glat), (elon, elat) in zip(meta.corners, _EXPECTED_CORNERS):
            assert glon == pytest.approx(elon, abs=1e-6)
            assert glat == pytest.approx(elat, abs=1e-6)
        # bbox is the min/max envelope of the (possibly skewed) corners
        assert meta.extent_minx == pytest.approx(-117.5, abs=1e-6)
        assert meta.extent_maxx == pytest.approx(-116.0, abs=1e-6)
        assert meta.extent_miny == pytest.approx(33.0, abs=1e-6)
        assert meta.extent_maxy == pytest.approx(34.0, abs=1e-6)
        assert meta.spatial_ref_wkid == 4326

    def test_skewed_quadrilateral_is_not_axis_aligned(self, tmp_path):
        """The bottom edge is shifted, so corners must not collapse to a rectangle."""
        blob = build_nitf21(icords="G", igeolo=igeolo_g(_DEFAULT_CORNERS_DMS))
        meta = nitf.parse_nitf21(_write(tmp_path, blob))
        lons = {round(lon, 6) for lon, _ in meta.corners}
        assert len(lons) == 4  # four distinct longitudes => genuinely skewed


class TestICORDSVariants:
    def test_decimal_degrees(self, tmp_path):
        corners = [(34.0, -117.0), (34.0, -116.0), (33.0, -116.0), (33.0, -117.0)]
        blob = build_nitf21(icords="D", igeolo=igeolo_d(corners))
        meta = nitf.parse_nitf21(_write(tmp_path, blob))
        assert meta is not None
        assert meta.icords == "D"
        assert meta.corners[0] == pytest.approx((-117.0, 34.0))
        assert meta.extent_minx == pytest.approx(-117.0)
        assert meta.extent_maxy == pytest.approx(34.0)

    def test_utm_north(self, tmp_path):
        # Zone 11N corners around southern California
        utm = [(11, 500000, 3762000), (11, 600000, 3762000),
               (11, 600000, 3651000), (11, 500000, 3651000)]
        blob = build_nitf21(icords="N", igeolo=igeolo_utm(utm))
        meta = nitf.parse_nitf21(_write(tmp_path, blob))
        assert meta is not None
        assert meta.icords == "N"
        assert meta.corners is not None and len(meta.corners) == 4
        # Cross-check against the same UTM converter the parser should use
        elat, elon = utm_to_latlon(11, 500000, 3762000, True)
        assert meta.corners[0] == pytest.approx((elon, elat), abs=1e-6)
        # Plausible geographic envelope
        assert 32.5 < meta.extent_miny < 34.5
        assert -118.5 < meta.extent_minx < -116.5


class TestRobustness:
    def test_non_nitf_returns_none(self, tmp_path):
        meta = nitf.parse_nitf21(_write(tmp_path, b"not a nitf file" * 50))
        assert meta is None

    def test_wrong_version_returns_none(self, tmp_path):
        blob = build_nitf21(fhdr=b"NITF02.00", icords="G",
                            igeolo=igeolo_g(_DEFAULT_CORNERS_DMS))
        assert nitf.parse_nitf21(_write(tmp_path, blob)) is None

    def test_truncated_file_returns_none(self, tmp_path):
        blob = build_nitf21(icords="G", igeolo=igeolo_g(_DEFAULT_CORNERS_DMS), truncate=100)
        assert nitf.parse_nitf21(_write(tmp_path, blob)) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert nitf.parse_nitf21(str(tmp_path / "does_not_exist.ntf")) is None

    def test_cadrg_r0_wrapper(self, tmp_path):
        """CADRG .r0-.r9 zone files use a NITF wrapper and must parse the same way."""
        blob = build_nitf21(icords="G", igeolo=igeolo_g(_DEFAULT_CORNERS_DMS))
        meta = nitf.parse_nitf21(_write(tmp_path, blob, suffix=".r0"))
        assert meta is not None
        assert meta.image_id == "TESTIMG001"
        assert meta.extent_minx == pytest.approx(-117.5)
