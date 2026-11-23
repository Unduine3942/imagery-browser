"""Headless smoke tests for the NTM metadata UI: DetailsPanel, the FilterPanel
category section, and the ImageryBrowserApp right-pane wiring.

These build real Tk widgets on a withdrawn root, so they catch construction and
wiring errors (bad imports, geometry, callbacks) without asserting pixels.
"""
from __future__ import annotations

from datetime import datetime

import pytest

try:
    import tkinter as tk
    _TK_AVAILABLE = True
except ImportError:
    _TK_AVAILABLE = False

from models import ImageryRecord


def _record():
    return ImageryRecord.make(
        filepath="/d/NTM001.ntf", filename="NTM001.ntf", fmt="NITF",
        extent_minx=-117.5, extent_miny=33.0, extent_maxx=-116.0, extent_maxy=34.0,
        spatial_ref_wkid=4326, acquisition_date=datetime(2025, 1, 15, 12, 0, 0),
        ingest_date=datetime(2025, 1, 15), file_size_bytes=2048,
        band_count=1, width=2048, height=1024,
        corners=[(-117.0, 34.0), (-116.0, 34.0), (-116.5, 33.0), (-117.5, 33.0)],
        icords="G", image_id="TESTIMG001", image_title="scene alpha",
        image_category="VIS", image_source="SENSOR-1", file_title="NTM COLLECTION",
        classification="U", num_image_segments=1,
    )


@pytest.fixture
def root():
    if not _TK_AVAILABLE:
        pytest.skip("tkinter not available")
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("No display available for tkinter")
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


class TestDetailsPanel:
    def test_placeholder_then_record(self, root):
        from ui.details_panel import DetailsPanel
        panel = DetailsPanel(root)
        # Placeholder before any selection
        assert panel._body.winfo_children()
        # Populating with a record rebuilds the body without error
        panel.show(_record())
        texts = [w.cget("text") for w in _all_labels(panel._body)]
        joined = " ".join(texts)
        assert "TESTIMG001" in joined
        assert "VIS" in joined          # category code (with label)
        assert "NTM COLLECTION" in joined
        # Clearing returns to the placeholder
        panel.show(None)
        assert panel._body.winfo_children()

    def test_record_without_corners(self, root):
        from ui.details_panel import DetailsPanel
        rec = ImageryRecord.make(
            filepath="/d/x.tif", filename="x.tif", fmt="GeoTIFF",
            extent_minx=0.0, extent_miny=0.0, extent_maxx=1.0, extent_maxy=1.0,
            spatial_ref_wkid=4326, acquisition_date=None,
            ingest_date=datetime(2025, 1, 1), file_size_bytes=10,
            band_count=None, width=None, height=None,
        )
        panel = DetailsPanel(root)
        panel.show(rec)  # must not raise on missing NITF fields
        assert panel._body.winfo_children()


class TestFilterPanelCategories:
    def test_category_section_and_filter(self, root):
        from ui.filter_panel import FilterPanel
        panel = FilterPanel(root, on_change=lambda: None)
        panel.set_image_categories(["VIS", "SAR"])
        assert set(panel._image_category_vars) == {"VIS", "SAR"}

        # All selected -> no category filter emitted (no narrowing)
        assert "categories" not in panel.get_filters()

        # Deselect one -> the remaining category is emitted as a filter
        panel._image_category_vars["VIS"].set(False)
        assert panel.get_filters()["categories"] == ["SAR"]

        # Reset re-selects everything
        panel._reset()
        assert all(v.get() for v in panel._image_category_vars.values())

    def test_empty_categories_shows_placeholder(self, root):
        from ui.filter_panel import FilterPanel
        panel = FilterPanel(root, on_change=lambda: None)
        panel.set_image_categories([])
        assert panel._image_category_vars == {}


class TestAppWiring:
    def test_app_builds_with_details_panel(self):
        if not _TK_AVAILABLE:
            pytest.skip("tkinter not available")
        try:
            from ui.app import ImageryBrowserApp
            app = ImageryBrowserApp(arcpy_available=False)
        except tk.TclError:
            pytest.skip("No display available for tkinter")
        try:
            app.withdraw()
            assert hasattr(app, "_details_panel")
            # Selection routing with an empty selection must not raise
            app._on_selection_change(set())
        finally:
            app.destroy()


def _all_labels(widget):
    """Recursively yield all tk.Label descendants of a widget."""
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            out.append(child)
        out.extend(_all_labels(child))
    return out
