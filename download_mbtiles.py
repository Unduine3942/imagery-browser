#!/usr/bin/env python3
"""
download_mbtiles.py — Download OSM tiles (zoom 0-6) into a .mbtiles file.

Usage:
    python download_mbtiles.py [output.mbtiles]

Defaults to: assets/world_z0-6.mbtiles

Dependencies: Python stdlib only (sqlite3, urllib, concurrent.futures).
The download is resumable — re-run after interruption to continue from
where it left off. Tiles already in the database are skipped.

Tile count by zoom:
    z0:      1   z3:     64   z6:  4,096
    z1:      4   z4:    256   total: 5,461
    z2:     16   z5:  1,024
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TILE_URL   = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = (
    "ArcGIS-Imagery-Browser/1.0 offline-mbtiles-builder "
    "(zoom 0-6 one-time bulk; contact: see project README)"
)
MAX_ZOOM    = 6
WORKERS     = 4      # parallel download threads (be polite)
RATE_DELAY  = 0.25   # seconds between requests per worker (4 workers → ~16 req/s max)
MAX_RETRIES = 3
COMMIT_EVERY = 100   # commit to SQLite every N tiles


# ---------------------------------------------------------------------------
# Tile helpers
# ---------------------------------------------------------------------------

def all_tiles(max_zoom: int) -> Iterator[tuple[int, int, int]]:
    for z in range(max_zoom + 1):
        n = 1 << z
        for x in range(n):
            for y in range(n):
                yield z, x, y


def total_tile_count(max_zoom: int) -> int:
    return sum((1 << z) ** 2 for z in range(max_zoom + 1))


def xyz_to_tms(z: int, y: int) -> int:
    """Convert OSM XYZ y → MBTiles TMS y (flipped axis)."""
    return (1 << z) - 1 - y


# ---------------------------------------------------------------------------
# MBTiles database
# ---------------------------------------------------------------------------

def open_or_create(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            name  TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tiles (
            zoom_level  INTEGER NOT NULL,
            tile_column INTEGER NOT NULL,
            tile_row    INTEGER NOT NULL,
            tile_data   BLOB    NOT NULL,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        )
    """)
    conn.executemany("INSERT OR REPLACE INTO metadata VALUES (?,?)", [
        ("name",        "OSM World Basemap z0-6"),
        ("type",        "baselayer"),
        ("version",     "1"),
        ("description", "OpenStreetMap raster tiles zoom 0-6"),
        ("format",      "png"),
        ("bounds",      "-180,-85.051129,180,85.051129"),
        ("center",      "0,0,2"),
        ("minzoom",     "0"),
        ("maxzoom",     str(MAX_ZOOM)),
    ])
    conn.commit()
    return conn


def already_have(conn: sqlite3.Connection, z: int, x: int, y: int) -> bool:
    tms_y = xyz_to_tms(z, y)
    return conn.execute(
        "SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
        (z, x, tms_y),
    ).fetchone() is not None


def insert_tile(
    conn: sqlite3.Connection, z: int, x: int, y: int, data: bytes
) -> None:
    tms_y = xyz_to_tms(z, y)
    conn.execute(
        "INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
        (z, x, tms_y, data),
    )


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def fetch(z: int, x: int, y: int) -> bytes | None:
    """Download one tile PNG; returns None on permanent failure."""
    url = TILE_URL.format(z=z, x=x, y=y)
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Rate-limited — back off hard
                wait = 10 * (attempt + 1)
                log.warning("Rate-limited (429). Waiting %ds…", wait)
                time.sleep(wait)
            elif exc.code in (404, 204):
                return None  # tile doesn't exist (ocean / no data)
            else:
                log.debug("HTTP %d for z=%d x=%d y=%d (attempt %d)",
                          exc.code, z, x, y, attempt + 1)
                time.sleep(2 ** attempt)
        except Exception as exc:
            log.debug("Error z=%d x=%d y=%d attempt %d: %s", z, x, y, attempt + 1, exc)
            time.sleep(2 ** attempt)
    log.warning("Giving up on z=%d x=%d y=%d after %d attempts", z, x, y, MAX_RETRIES)
    return None


def worker(args: tuple[int, int, int]) -> tuple[int, int, int, bytes | None]:
    z, x, y = args
    time.sleep(RATE_DELAY)
    return z, x, y, fetch(z, x, y)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(output: Path) -> None:
    total = total_tile_count(MAX_ZOOM)
    log.info("OSM MBTiles builder  |  zoom 0-%d  |  %d tiles  |  output: %s",
             MAX_ZOOM, total, output)

    output.parent.mkdir(parents=True, exist_ok=True)
    conn = open_or_create(output)

    existing = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
    if existing:
        log.info("Resuming: %d tiles already saved, skipping those.", existing)

    pending = [
        (z, x, y)
        for z, x, y in all_tiles(MAX_ZOOM)
        if not already_have(conn, z, x, y)
    ]
    log.info("%d tiles to download.", len(pending))
    if not pending:
        log.info("Nothing to do — database is complete.")
        conn.close()
        return

    done = existing
    saved = 0
    failed = 0
    batch: list[tuple[int, int, int, bytes]] = []

    start = time.monotonic()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(worker, t): t for t in pending}
        for future in as_completed(futures):
            z, x, y, data = future.result()
            done += 1
            if data:
                batch.append((z, x, y, data))
                saved += 1
            else:
                failed += 1

            if len(batch) >= COMMIT_EVERY:
                for bz, bx, by, bd in batch:
                    insert_tile(conn, bz, bx, by, bd)
                conn.commit()
                batch.clear()

            if done % 200 == 0 or done == total:
                elapsed = time.monotonic() - start
                rate = saved / elapsed if elapsed > 0 else 0
                eta = (len(pending) - saved) / rate if rate > 0 else 0
                log.info("[%d/%d]  saved=%d  failed=%d  %.1f tiles/s  ETA ~%ds",
                         done, total, saved, failed, rate, int(eta))

    # Flush remaining batch
    for bz, bx, by, bd in batch:
        insert_tile(conn, bz, bx, by, bd)
    conn.commit()
    conn.execute("ANALYZE")
    conn.close()

    size_mb = output.stat().st_size / 1_000_000
    log.info("Done.  %d saved  %d failed  %.1f MB  →  %s",
             saved, failed, size_mb, output)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/world_z0-6.mbtiles")
    main(out)
