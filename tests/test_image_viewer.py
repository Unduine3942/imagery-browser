"""Tests for ui/image_viewer.py — construction + coordinate mapping.

These need Tk and Pillow.ImageTk; skipped automatically where unavailable.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

rasterio = pytest.importorskip("rasterio")
np = pytest.importorskip("numpy")
pytest.importorskip("PIL.ImageTk")
from rasterio.transform import from_origin  # noqa: E402

import clipper  # noqa: E402
from models import ImageryRecord  # noqa: E402


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except Exception:  # pragma: no cover - no display
        pytest.skip("Tk display not available")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def _make_geotiff(path: Path, width: int = 200, height: int = 150) -> None:
    transform = from_origin(10.0, 50.0, 0.01, 0.01)
    data = np.zeros((3, height, width), dtype="uint8")
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height,
                       count=3, dtype="uint8", crs="EPSG:4326", transform=transform) as dst:
        dst.write(data)


def _record_for(path: Path) -> ImageryRecord:
    return ImageryRecord.make(
        filepath=str(path), filename=path.name, fmt="GeoTIFF",
        extent_minx=10.0, extent_miny=48.5, extent_maxx=12.0, extent_maxy=50.0,
        spatial_ref_wkid=4326, acquisition_date=None, ingest_date=datetime(2026, 1, 1),
        file_size_bytes=123, band_count=3, width=200, height=150,
    )


def test_viewer_constructs_and_loads_preview(tk_root, tmp_path):
    from ui.image_viewer import ImageViewerWindow

    src = tmp_path / "img.tif"
    _make_geotiff(src)
    viewer = ImageViewerWindow(tk_root, _record_for(src))

    assert viewer._info is not None
    assert (viewer._info.width, viewer._info.height) == (200, 150)
    assert viewer._preview is not None
    viewer.destroy()


def test_canvas_source_round_trip(tk_root, tmp_path):
    from ui.image_viewer import ImageViewerWindow

    src = tmp_path / "img.tif"
    _make_geotiff(src)
    viewer = ImageViewerWindow(tk_root, _record_for(src))

    # Set a deterministic display placement (avoids depending on real widget size).
    viewer._disp_off = (12, 25)
    viewer._disp_size = (400, 300)
    # Full-preview view.
    viewer._vx0, viewer._vy0 = 0.0, 0.0
    viewer._vx1 = float(viewer._preview.width)
    viewer._vy1 = float(viewer._preview.height)

    for sx, sy in [(0, 0), (50, 40), (199, 149)]:
        cx, cy = viewer._source_to_canvas(sx, sy)
        rx, ry = viewer._canvas_to_source(cx, cy)
        assert rx == pytest.approx(sx, abs=0.5)
        assert ry == pytest.approx(sy, abs=0.5)
    viewer.destroy()


def test_selection_maps_to_source_window(tk_root, tmp_path):
    from ui.image_viewer import ImageViewerWindow

    src = tmp_path / "img.tif"
    _make_geotiff(src)
    viewer = ImageViewerWindow(tk_root, _record_for(src))
    viewer._disp_off = (0, 0)
    viewer._disp_size = (400, 300)
    viewer._vx0, viewer._vy0 = 0.0, 0.0
    viewer._vx1 = float(viewer._preview.width)
    viewer._vy1 = float(viewer._preview.height)

    # Drag a rectangle over the top-left quarter of the displayed image.
    viewer._draw_mode = True
    viewer._finish_selection((0, 0), (200, 150))

    assert viewer._selection_src is not None
    col, row, w, h = viewer._selection_src
    assert (col, row) == (0, 0)
    # Half of 200x150 source pixels.
    assert w == pytest.approx(100, abs=2)
    assert h == pytest.approx(75, abs=2)

    # And that window actually clips.
    out = tmp_path / "clip.tif"
    result = clipper.clip_geotiff_by_pixels(str(src), col, row, w, h, str(out))
    assert result.ok and out.exists()
    viewer.destroy()
