# Imagery_Browser

## Overview

A standalone desktop tool for scanning, filtering, previewing, and transferring
geospatial imagery (GeoTIFF, NITF, JPEG2000, MrSID, ECW, KML/KMZ, and more) from
shared drives. It draws imagery footprints on an offline map canvas and can
package selected imagery for transfer to an air-gapped system.

**ArcGIS Pro is optional.** When ArcGIS Pro's `arcpy` is available, the app adds
footprints to a live Pro map. Without it, the app runs in **canvas-only mode** —
every other feature works, using `rasterio`/GDAL/Pillow instead of `arcpy`.

## Quick Start

Choose the option that matches the machine you are running on.

### 1. Self-contained build — no ArcGIS Pro, no Python (recommended for air-gapped)

On a **dev machine with internet**, build a frozen distribution:

```bat
build.bat
```

This produces `dist\ImageryBrowser\` containing `ImageryBrowser.exe` plus a
bundled Python runtime and all dependencies (tkinter, Pillow, numpy, rasterio +
GDAL, pyproj). Copy the **entire `dist\ImageryBrowser` folder** to the target
machine and double-click `ImageryBrowser.exe`. Nothing else needs to be
installed there.

The build ends with a self-test. You can re-run it any time:

```bat
dist\ImageryBrowser\ImageryBrowser.exe --selftest
```

### 2. Any Python 3.9+ with dependencies installed

```bat
python -m pip install -r requirements.txt
python imagery_browser.py
```

### 3. ArcGIS Pro's bundled Python (enables live Pro map integration)

```bat
launch.bat
```

`launch.bat` locates ArcGIS Pro's Python automatically and falls back to the
system Python if Pro is not installed.

## Clipping & snapshots

To extract just a portion of an image (e.g. a customer only wants a certain
area), select a single record and click **Open / Clip…** (or double-click the
row). In the viewer:

- Scroll to zoom, drag to pan.
- Click **Draw clip region**, then drag a rectangle over the area (Esc clears it).
- **Save GeoTIFF clip…** writes a new GeoTIFF read from the source at native
  resolution, preserving coordinates/CRS — still usable in GIS.
- **Save PNG snapshot…** writes a flat PNG of the region (no georeferencing) for
  reports and briefings.

Clipping requires rasterio or GDAL (both bundled in the standalone build);
without them only PNG snapshots are available.

## Air-gapped transfer

From within the app, select imagery records and use **Transfer** to write a
package (imagery + sidecar files + `manifest.json`) to a removable drive. If a
frozen build exists in `dist\ImageryBrowser`, it is bundled into the package
automatically so the receiving machine can run `ImageryBrowser.exe` with no
ArcGIS Pro and no Python. Otherwise the raw source is bundled (run via
`launch.bat`).

## Dependencies

- **Required:** Python 3.9+ with tkinter (bundled with standard CPython on
  Windows), Pillow, numpy.
- **Recommended:** rasterio, pyproj — native-quality basemaps, full raster
  metadata, and on-the-fly reprojection. The app degrades gracefully without
  them.
- **Optional:** arcpy (ArcGIS Pro 3.3+) — live Pro map footprint integration.

See `requirements.txt` (runtime) and `requirements-build.txt` (build).

## Troubleshooting

The app writes `imagery_browser.log` next to the program (or to the temp
directory if that location is read-only). A fatal startup error is also shown in
a dialog. If a standalone build misbehaves, run `ImageryBrowser.exe --selftest`
and check `selftest_result.txt`.
