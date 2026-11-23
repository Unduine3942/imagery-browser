"""
Unit tests for ui/map_canvas.py coordinate transform methods.

Tests cover:
- FootprintCanvas._world_to_canvas(): lon/lat → canvas pixel coords
- FootprintCanvas._canvas_to_world(): pixel → lon/lat (inverse)
- Round-trip consistency (both directions)
- Custom viewport (non-default world bounds)
- Degenerate viewport (zero extent handled via 'or 1.0' guard)
"""
from __future__ import annotations

import math
import pytest

try:
    import tkinter as tk
    _TK_AVAILABLE = True
except ImportError:
    _TK_AVAILABLE = False

_CANVAS_W = 400
_CANVAS_H = 300


def _set_world(c, minx: float, miny: float, maxx: float, maxy: float) -> None:
    c._world_minx = minx
    c._world_miny = miny
    c._world_maxx = maxx
    c._world_maxy = maxy


@pytest.fixture(scope="module")
def canvas():
    if not _TK_AVAILABLE:
        pytest.skip("tkinter not available")
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("No display available for tkinter")

    from ui.map_canvas import FootprintCanvas
    c = FootprintCanvas(root, width=_CANVAS_W, height=_CANVAS_H)
    # Patch winfo_{width,height} so math uses a stable size before the window is shown.
    c.winfo_width = lambda: _CANVAS_W
    c.winfo_height = lambda: _CANVAS_H
    yield c
    try:
        root.destroy()
    except tk.TclError:
        pass


class TestWorldToCanvas:
    """_world_to_canvas: lon/lat → canvas pixel coordinates."""

    def test_world_center_maps_to_canvas_center(self, canvas):
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx, cy = canvas._world_to_canvas(0.0, 0.0)
        assert math.isclose(cx, 200.0, abs_tol=0.5)
        assert math.isclose(cy, 150.0, abs_tol=0.5)

    def test_sw_corner_maps_to_canvas_bottom_left(self, canvas):
        """(-180, -90) world SW → canvas bottom-left (0, H)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx, cy = canvas._world_to_canvas(-180.0, -90.0)
        assert math.isclose(cx, 0.0, abs_tol=0.5)
        assert math.isclose(cy, _CANVAS_H, abs_tol=0.5)

    def test_ne_corner_maps_to_canvas_top_right(self, canvas):
        """(180, 90) world NE → canvas top-right (W, 0)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx, cy = canvas._world_to_canvas(180.0, 90.0)
        assert math.isclose(cx, _CANVAS_W, abs_tol=0.5)
        assert math.isclose(cy, 0.0, abs_tol=0.5)

    def test_nw_corner_maps_to_canvas_top_left(self, canvas):
        """(-180, 90) world NW → canvas top-left (0, 0)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx, cy = canvas._world_to_canvas(-180.0, 90.0)
        assert math.isclose(cx, 0.0, abs_tol=0.5)
        assert math.isclose(cy, 0.0, abs_tol=0.5)

    def test_se_corner_maps_to_canvas_bottom_right(self, canvas):
        """(180, -90) world SE → canvas bottom-right (W, H)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx, cy = canvas._world_to_canvas(180.0, -90.0)
        assert math.isclose(cx, _CANVAS_W, abs_tol=0.5)
        assert math.isclose(cy, _CANVAS_H, abs_tol=0.5)

    def test_quarter_point(self, canvas):
        """(90, 45) is 3/4 east and 3/4 north → canvas (300, 75)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx, cy = canvas._world_to_canvas(90.0, 45.0)
        assert math.isclose(cx, 300.0, abs_tol=0.5)
        assert math.isclose(cy, 75.0, abs_tol=0.5)

    def test_y_axis_is_flipped(self, canvas):
        """Higher latitude → smaller canvas Y (canvas Y increases downward)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        _, cy_north = canvas._world_to_canvas(0.0, 45.0)
        _, cy_south = canvas._world_to_canvas(0.0, -45.0)
        assert cy_north < cy_south

    def test_x_increases_eastward(self, canvas):
        """More eastern longitude → larger canvas X."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx_west, _ = canvas._world_to_canvas(-90.0, 0.0)
        cx_east, _ = canvas._world_to_canvas(90.0, 0.0)
        assert cx_east > cx_west

    def test_custom_viewport_center(self, canvas):
        """Center of a zoomed viewport maps to canvas center."""
        _set_world(canvas, 0.0, 0.0, 10.0, 10.0)
        cx, cy = canvas._world_to_canvas(5.0, 5.0)
        assert math.isclose(cx, 200.0, abs_tol=0.5)
        assert math.isclose(cy, 150.0, abs_tol=0.5)

    def test_custom_viewport_nw_corner(self, canvas):
        """NW corner of custom viewport → canvas (0, 0)."""
        _set_world(canvas, 100.0, 20.0, 110.0, 30.0)
        cx, cy = canvas._world_to_canvas(100.0, 30.0)
        assert math.isclose(cx, 0.0, abs_tol=0.5)
        assert math.isclose(cy, 0.0, abs_tol=0.5)

    def test_custom_viewport_se_corner(self, canvas):
        """SE corner of custom viewport → canvas (_CANVAS_W, _CANVAS_H)."""
        _set_world(canvas, 100.0, 20.0, 110.0, 30.0)
        cx, cy = canvas._world_to_canvas(110.0, 20.0)
        assert math.isclose(cx, _CANVAS_W, abs_tol=0.5)
        assert math.isclose(cy, _CANVAS_H, abs_tol=0.5)


class TestCanvasToWorld:
    """_canvas_to_world: canvas pixel → lon/lat (inverse of _world_to_canvas)."""

    def test_canvas_center_maps_to_world_center(self, canvas):
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        wx, wy = canvas._canvas_to_world(200.0, 150.0)
        assert math.isclose(wx, 0.0, abs_tol=0.5)
        assert math.isclose(wy, 0.0, abs_tol=0.5)

    def test_canvas_origin_maps_to_nw_world_corner(self, canvas):
        """Canvas (0, 0) is top-left, matching the NW world corner."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        wx, wy = canvas._canvas_to_world(0.0, 0.0)
        assert math.isclose(wx, -180.0, abs_tol=0.5)
        assert math.isclose(wy, 90.0, abs_tol=0.5)

    def test_canvas_bottom_right_maps_to_se_world_corner(self, canvas):
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        wx, wy = canvas._canvas_to_world(float(_CANVAS_W), float(_CANVAS_H))
        assert math.isclose(wx, 180.0, abs_tol=0.5)
        assert math.isclose(wy, -90.0, abs_tol=0.5)

    def test_top_edge_maps_to_max_latitude(self, canvas):
        """Any point on the top row (cy=0) should have latitude = world_maxy."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        _, wy = canvas._canvas_to_world(200.0, 0.0)
        assert math.isclose(wy, 90.0, abs_tol=0.5)

    def test_bottom_edge_maps_to_min_latitude(self, canvas):
        """Any point on the bottom row (cy=H) should have latitude = world_miny."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        _, wy = canvas._canvas_to_world(200.0, float(_CANVAS_H))
        assert math.isclose(wy, -90.0, abs_tol=0.5)

    def test_custom_viewport_center(self, canvas):
        _set_world(canvas, 10.0, 10.0, 20.0, 20.0)
        wx, wy = canvas._canvas_to_world(200.0, 150.0)
        assert math.isclose(wx, 15.0, abs_tol=0.5)
        assert math.isclose(wy, 15.0, abs_tol=0.5)


class TestCoordinateRoundTrip:
    """Round-trip: inverse(_forward(p)) ≈ p for arbitrary points."""

    @pytest.mark.parametrize("wx,wy", [
        (0.0, 0.0),
        (-90.0, 45.0),
        (120.0, -30.0),
        (-180.0, -90.0),
        (180.0, 90.0),
        (45.123, -67.456),
        (-1.5, 51.5),   # London-ish
    ])
    def test_world_forward_inverse_round_trip(self, canvas, wx, wy):
        """_canvas_to_world(_world_to_canvas(wx, wy)) ≈ (wx, wy)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        cx, cy = canvas._world_to_canvas(wx, wy)
        wx2, wy2 = canvas._canvas_to_world(cx, cy)
        assert math.isclose(wx2, wx, abs_tol=1e-6)
        assert math.isclose(wy2, wy, abs_tol=1e-6)

    @pytest.mark.parametrize("cx,cy", [
        (0.0, 0.0),
        (200.0, 150.0),
        (400.0, 300.0),
        (100.0, 75.0),
        (350.7, 210.3),
        (1.0, 1.0),
    ])
    def test_canvas_inverse_forward_round_trip(self, canvas, cx, cy):
        """_world_to_canvas(_canvas_to_world(cx, cy)) ≈ (cx, cy)."""
        _set_world(canvas, -180.0, -90.0, 180.0, 90.0)
        wx, wy = canvas._canvas_to_world(cx, cy)
        cx2, cy2 = canvas._world_to_canvas(wx, wy)
        assert math.isclose(cx2, cx, abs_tol=1e-6)
        assert math.isclose(cy2, cy, abs_tol=1e-6)

    def test_round_trip_in_custom_viewport(self, canvas):
        """Round-trip is exact in a zoomed-in custom viewport."""
        _set_world(canvas, -100.0, 30.0, -80.0, 50.0)
        wx, wy = -90.0, 40.0
        cx, cy = canvas._world_to_canvas(wx, wy)
        wx2, wy2 = canvas._canvas_to_world(cx, cy)
        assert math.isclose(wx2, wx, abs_tol=1e-6)
        assert math.isclose(wy2, wy, abs_tol=1e-6)


class TestDegenerateViewport:
    """Zero-extent world bounds: 'or 1.0' guard prevents ZeroDivisionError."""

    def test_zero_world_width_does_not_raise(self, canvas):
        """world_maxx == world_minx: width denominator is protected by 'or 1.0'."""
        _set_world(canvas, 10.0, -90.0, 10.0, 90.0)
        cx, cy = canvas._world_to_canvas(10.0, 0.0)
        assert isinstance(cx, float)
        assert isinstance(cy, float)

    def test_zero_world_height_does_not_raise(self, canvas):
        """world_maxy == world_miny: height denominator is protected by 'or 1.0'."""
        _set_world(canvas, -180.0, 45.0, 180.0, 45.0)
        cx, cy = canvas._world_to_canvas(0.0, 45.0)
        assert isinstance(cx, float)
        assert isinstance(cy, float)

    def test_canvas_to_world_zero_extent_does_not_raise(self, canvas):
        """Inverse also uses 'or 1.0' guard on both denominators."""
        _set_world(canvas, 10.0, 20.0, 10.0, 20.0)
        wx, wy = canvas._canvas_to_world(200.0, 150.0)
        assert isinstance(wx, float)
        assert isinstance(wy, float)


def _make_record(corners=None, **kw):
    from datetime import datetime
    from models import ImageryRecord
    base = dict(
        filepath="/d/x.ntf", filename="x.ntf", fmt="NITF",
        extent_minx=-117.5, extent_miny=33.0, extent_maxx=-116.0, extent_maxy=34.0,
        spatial_ref_wkid=4326, acquisition_date=datetime(2025, 1, 15, 12, 0, 0),
        ingest_date=datetime(2025, 1, 15), file_size_bytes=2048,
        band_count=1, width=2048, height=1024, corners=corners,
    )
    base.update(kw)
    return ImageryRecord.make(**base)


class TestFootprintGeometry:
    """The wireframe must be a true quadrilateral when corners are present."""

    _CORNERS = [(-117.0, 34.0), (-116.0, 34.0), (-116.5, 33.0), (-117.5, 33.0)]

    def test_corners_render_as_polygon(self, canvas):
        rec = _make_record(corners=self._CORNERS, icords="G", image_category="VIS")
        canvas.draw_footprints([rec])
        items = list(canvas._box_map)
        assert len(items) == 1
        assert canvas.type(items[0]) == "polygon"

    def test_no_corners_render_as_rectangle(self, canvas):
        rec = _make_record(corners=None)
        canvas.draw_footprints([rec])
        items = list(canvas._box_map)
        assert len(items) == 1
        assert canvas.type(items[0]) == "rectangle"


class TestFootprintColorAndTooltip:
    def test_color_prefers_category_then_type(self):
        if not _TK_AVAILABLE:
            pytest.skip("tkinter not available")
        from config import ICAT_COLORS, IMAGE_TYPE_COLORS
        from ui.map_canvas import _footprint_color
        rec_cat = _make_record(image_category="SAR")
        assert _footprint_color(rec_cat) == ICAT_COLORS["SAR"]
        # Unknown category falls back to the filename-derived image type color
        rec_type = _make_record(filepath="/d/WV03_20250101_PAN_s.ntf",
                                filename="WV03_20250101_PAN_s.ntf")
        assert _footprint_color(rec_type) == IMAGE_TYPE_COLORS["PAN"]

    def test_tooltip_includes_ntm_fields(self):
        if not _TK_AVAILABLE:
            pytest.skip("tkinter not available")
        from ui.map_canvas import FootprintCanvas
        rec = _make_record(
            corners=[(-117.0, 34.0), (-116.0, 34.0), (-116.5, 33.0), (-117.5, 33.0)],
            icords="G", image_id="TESTIMG001", image_category="VIS", classification="U",
        )
        text = FootprintCanvas._tooltip_text(rec)
        assert "Image ID: TESTIMG001" in text
        assert "Visible" in text          # ICAT label
        assert "Corners (G)" in text
        assert "-117.0000, 34.0000" in text
        assert "Class:    U" in text
