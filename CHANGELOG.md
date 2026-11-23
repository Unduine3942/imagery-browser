# Changelog — Imagery Browser

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Provenance:** This changelog was created retroactively on 2026-08-04.
> The project carried no version designation before that date; 1.0.0 was
> assigned to the state last modified 2026-06-24, which matches the two
> snapshot archives (`Imagery_Browser_backup_20260624_114857.zip`,
> `Imagery_Browser_no-arcgis_20260624.zip`) and the PyInstaller build in
> `dist/ImageryBrowser`. Details below are reconstructed from the code,
> README, and file timestamps; no changelog was kept contemporaneously.

## [1.1.0] - 2026-08-04 — Sentinel dark theme, imagery context menu

### Added
- Right-click context menu on the imagery list: View Metadata (full-record
  dialog including NITF NTM fields and corner geometry), Zoom to Image
  (map centres on the footprint), Download Image, Open/Clip.
- App version (from `VERSION`) shown in the title bar, toolbar, and
  startup dialog; `VERSION` bundled into the frozen build.

### Changed
- UI restyled to the Sentinel dark theme shared with the Shared Drive
  Policy Manager and GEOINT Data Manager (`ui/styles.py` palette swap,
  dark ttk styling, option-database defaults for plain tk widgets). The
  map canvas keeps its ocean-blue background to blend with the light
  basemap tiles.

### Fixed
- Startup crashed with RuntimeError when arcpy was importable but no
  ArcGIS license was active; import guards in `footprint_manager` and
  `scanner` now fall back to canvas-only / rasterio mode on any arcpy
  import failure.

## [1.0.0] - 2026-06-24 — Baseline release (versioned retroactively)

### Added
- Standalone desktop tool for scanning, filtering, previewing, and
  transferring geospatial imagery (GeoTIFF, NITF, JPEG2000, MrSID, ECW,
  KML/KMZ, and more) from shared drives.
- Offline map canvas drawing imagery footprints over a bundled world
  basemap (`assets/world_z0-6.mbtiles`); footprint management and clipping
  (`footprint_manager.py`, `clipper.py`).
- Dual-mode geospatial backend: uses ArcGIS Pro `arcpy` when available
  (adds footprints to a live Pro map); otherwise runs canvas-only via
  rasterio/GDAL/Pillow. ArcGIS Pro 3.3+ checked at startup, optional.
- NITF metadata handling (`nitf.py`) with sample data in `sample_nitf/`.
- Air-gapped transfer packaging for selected imagery
  (`airgapped_transfer.py`).
- Image viewer, imagery panel, and map canvas UI (`ui/`).
- PyInstaller packaging (`imagery_browser.spec`, `build.bat`) producing
  `dist/ImageryBrowser`.
- Test suite: 336 tests across scanner, models, NITF, clipper, downloader,
  transfer, viewer, map canvas, tile loader, styles, and UI panels.

### Known issues (at time of versioning, 2026-08-04)
- 7 tests in `tests/test_downloader.py::TestImageryDownloaderCopyToDesktop`
  fail: they exercise a `copy_to_desktop` method that no longer exists on
  `ImageryDownloader` (superseded by the air-gapped transfer flow). The
  stale tests need removal or rewrite; remaining suite: 326 passed,
  3 skipped.
