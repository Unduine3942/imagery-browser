"""Pure-Python MGRS → WGS84 lat/lon conversion.

Accepts any MGRS precision (1–5 digit pairs).  Spaces in the input string are
ignored, so both "18TWL91002350" and "18T WL 9100 2350" work.
No external dependencies beyond the standard library.
"""
from __future__ import annotations

import math
import re

# WGS84 ellipsoid
_A = 6_378_137.0
_F = 1 / 298.257223563
_B = _A * (1 - _F)
_E2 = 1 - (_B / _A) ** 2
_E_PRIME2 = _E2 / (1 - _E2)
_K0 = 0.9996

# MGRS latitude band letters (C–X, no I, no O)
_LAT_BANDS = "CDEFGHJKLMNPQRSTUVWX"

# 100-km column (easting) letter sets indexed by (zone_num - 1) % 3
_COL_SETS = (
    "ABCDEFGH",   # zones 1, 4, 7, …
    "JKLMNPQR",   # zones 2, 5, 8, …
    "STUVWXYZ",   # zones 3, 6, 9, …
)

# 100-km row (northing) letter sequences — 20 letters, no I, no O
_ROW_ODD  = "ABCDEFGHJKLMNPQRSTUV"   # odd zone numbers
_ROW_EVEN = "FGHJKLMNPQRSTUVABCDE"   # even zone numbers (offset +5)

# Regex: zone-number + band + 2-letter grid square + even digit block (1–5 pairs)
_MGRS_RE = re.compile(
    r"^(\d{1,2})([A-Z])([A-Z]{2})(\d{2}|\d{4}|\d{6}|\d{8}|\d{10})$"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _meridional_arc(lat_rad: float) -> float:
    """Meridional arc (metres) from the equator; negative for south latitudes."""
    e2 = _E2
    return _A * (
        (1 - e2/4 - 3*e2**2/64  - 5*e2**3/256)  * lat_rad
        - (3*e2/8 + 3*e2**2/32  + 45*e2**3/1024) * math.sin(2*lat_rad)
        + (15*e2**2/256 + 45*e2**3/1024)          * math.sin(4*lat_rad)
        - (35*e2**3/3072)                          * math.sin(6*lat_rad)
    )


def _band_min_northing(band: str) -> float:
    """Northing reference (metres) for the southern edge of the given band.

    For northern-hemisphere bands (N–X) this is the regular UTM northing.
    For southern-hemisphere bands (C–M) the 10 000 000 m false northing is
    already included so that the value is always positive.
    """
    band_idx = _LAT_BANDS.index(band)
    min_lat_deg = -80 + band_idx * 8          # each band is 8°; C starts at −80°
    M = _meridional_arc(math.radians(min_lat_deg)) * _K0
    return (10_000_000.0 + M) if band < "N" else M


# Precomputed once at import time
_BAND_MIN: dict[str, float] = {b: _band_min_northing(b) for b in _LAT_BANDS}


def _utm_to_latlon(zone: int, easting: float, northing: float, northern: bool) -> tuple[float, float]:
    """Convert UTM (WGS84) to geographic decimal-degree (lat, lon)."""
    x = easting - 500_000.0
    y = northing if northern else northing - 10_000_000.0

    lon0 = math.radians((zone - 1) * 6 - 180 + 3)

    M = y / _K0
    mu = M / (_A * (1 - _E2/4 - 3*_E2**2/64 - 5*_E2**3/256))

    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    phi1 = (
        mu
        + (3*e1/2   - 27*e1**3/32)  * math.sin(2*mu)
        + (21*e1**2/16 - 55*e1**4/32) * math.sin(4*mu)
        + (151*e1**3/96)               * math.sin(6*mu)
        + (1097*e1**4/512)             * math.sin(8*mu)
    )

    sin_p = math.sin(phi1)
    tan_p = math.tan(phi1)
    cos_p = math.cos(phi1)

    N1 = _A / math.sqrt(1 - _E2 * sin_p**2)
    T1 = tan_p**2
    C1 = _E_PRIME2 * cos_p**2
    R1 = _A * (1 - _E2) / (1 - _E2 * sin_p**2) ** 1.5
    D  = x / (N1 * _K0)

    lat = phi1 - (N1 * tan_p / R1) * (
        D**2 / 2
        - (5 + 3*T1 + 10*C1 - 4*C1**2 - 9*_E_PRIME2)                        * D**4 / 24
        + (61 + 90*T1 + 298*C1 + 45*T1**2 - 252*_E_PRIME2 - 3*C1**2)        * D**6 / 720
    )
    lon = lon0 + (
        D
        - (1 + 2*T1 + C1)                                                     * D**3 / 6
        + (5 - 2*C1 + 28*T1 - 3*C1**2 + 8*_E_PRIME2 + 24*T1**2)             * D**5 / 120
    ) / cos_p

    return math.degrees(lat), math.degrees(lon)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def utm_to_latlon(zone: int, easting: float, northing: float, northern: bool) -> tuple[float, float]:
    """Convert UTM (WGS84) easting/northing to geographic (latitude, longitude).

    Public wrapper around the internal converter; used to decode NITF IGEOLO
    corner coordinates when ICORDS is 'N' (UTM North) or 'S' (UTM South).
    """
    return _utm_to_latlon(zone, easting, northing, northern)


def mgrs_to_latlon(mgrs: str) -> tuple[float, float]:
    """Convert an MGRS coordinate string to WGS84 (latitude, longitude) degrees.

    Raises ValueError with a descriptive message when the input is invalid.
    """
    cleaned = mgrs.upper().replace(" ", "")
    m = _MGRS_RE.match(cleaned)
    if not m:
        raise ValueError(
            f"Cannot parse MGRS string {mgrs!r}.\n"
            "Expected format: <zone><band><2-letter square><even digits>\n"
            "Example: 18TWL91002350"
        )

    zone_num   = int(m.group(1))
    band       = m.group(2)
    sq         = m.group(3)
    numeric    = m.group(4)
    col_letter = sq[0]
    row_letter = sq[1]

    if not 1 <= zone_num <= 60:
        raise ValueError(f"UTM zone {zone_num} is out of range 1–60.")
    if band not in _LAT_BANDS:
        raise ValueError(f"Band letter {band!r} is not a valid MGRS latitude band.")

    # --- easting ---
    col_set = _COL_SETS[(zone_num - 1) % 3]
    if col_letter not in col_set:
        raise ValueError(
            f"Column letter {col_letter!r} is not valid for UTM zone {zone_num}."
        )
    col_idx = col_set.index(col_letter)
    half = len(numeric) // 2
    east_str  = numeric[:half]
    north_str = numeric[half:]
    easting = (col_idx + 1) * 100_000 + int(east_str.ljust(5, "0"))

    # --- northing ---
    row_letters = _ROW_ODD if zone_num % 2 == 1 else _ROW_EVEN
    if row_letter not in row_letters:
        raise ValueError(f"Row letter {row_letter!r} not valid for zone {zone_num}.")
    row_idx = row_letters.index(row_letter)
    north_in_cycle = row_idx * 100_000 + int(north_str.ljust(5, "0"))

    # Pick the correct 2 000 km northing cycle for this latitude band
    min_north = _BAND_MIN[band]
    cycles    = int(min_north / 2_000_000)
    northing  = cycles * 2_000_000 + north_in_cycle
    if northing < min_north:
        northing += 2_000_000

    return _utm_to_latlon(zone_num, easting, northing, northern=(band >= "N"))
