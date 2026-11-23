from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from models import ImageryRecord
from ui import wheel
from ui.styles import (
    COLOR_CANVAS_BG,
    COLOR_SELECTED_BOX, IMAGE_TYPE_COLORS, ICAT_COLORS, ICAT_LABELS, FONT_SMALL,
    format_bytes,
)
from ui.tile_loader import BasemapRenderer, GeoTIFFBasemap, KMLBasemap, _KML_EXTENSIONS

_DEFAULT_FOOTPRINT_COLOR = "#7f8c8d"


def _footprint_color(record: ImageryRecord) -> str:
    """Outline color for a footprint: NITF category → image type → gray."""
    if record.image_category and record.image_category in ICAT_COLORS:
        return ICAT_COLORS[record.image_category]
    return IMAGE_TYPE_COLORS.get(record.image_type or "", _DEFAULT_FOOTPRINT_COLOR)

try:
    from PIL import Image as _PILImage
    from PIL import ImageTk as _ImageTk
    _TILES_AVAILABLE = True
except ImportError:
    _PILImage = None  # type: ignore[assignment]
    _ImageTk = None   # type: ignore[assignment]
    _TILES_AVAILABLE = False

_MARGIN = 0               # no margin — tiles fill the full canvas
_WORLD_PAD_FACTOR = 0.1   # fractional padding around record extents
_DEFAULT_CANVAS_W = 400
_DEFAULT_CANVAS_H = 300
_MIN_WORLD_EXTENT = 0.001  # degrees — prevent zooming in beyond ~100 m
_MAX_WORLD_EXTENT = 400.0  # degrees — prevent zooming past full globe


class FootprintCanvas(tk.Canvas):
    """2-D wireframe preview of imagery footprints."""

    def __init__(self, master, basemap_path: Optional[str] = None, **kwargs):
        kwargs.setdefault("bg", COLOR_CANVAS_BG)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(master, **kwargs)

        self._records: list[ImageryRecord] = []
        self._selected_ids: set[str] = set()

        # View state: all zoom/pan is stored as world bounds so it survives redraws
        self._world_minx = -180.0
        self._world_miny = -90.0
        self._world_maxx = 180.0
        self._world_maxy = 90.0

        self._drag_start: Optional[tuple[int, int]] = None
        self._tooltip: Optional[tk.Toplevel] = None
        self._tooltip_label: Optional[tk.Label] = None
        self._hover_item_id: Optional[int] = None

        self.bind("<Configure>",       self._on_resize)
        # Wheel events are routed by pointer position, not keyboard focus, so
        # the map zooms whenever the cursor is over it. See ui/wheel.py.
        wheel.register(self, self._on_scroll)
        self.bind("<ButtonPress-1>",   self._on_drag_start)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_drag_end)
        self.bind("<Motion>",          self._on_mouse_move)
        self.bind("<Leave>",           self._on_leave)

        self._box_map: dict[int, ImageryRecord] = {}  # canvas item id → record
        self._last_mouse_ms: int = 0  # monotonic ms of last hit-test

        self._basemap = BasemapRenderer()
        self._geotiff: Optional[GeoTIFFBasemap] = None
        if basemap_path:
            ext = Path(basemap_path).suffix.lower()
            self._geotiff = (
                KMLBasemap(basemap_path) if ext in _KML_EXTENSIONS
                else GeoTIFFBasemap(basemap_path)
            )
        self._world_basemap_cache: Optional[tuple] = None   # (bbox_key, PhotoImage | None)
        self._geotiff_cache: Optional[tuple] = None         # (bbox_key, PhotoImage | None)
        self._tk_basemap_images: list = []  # keep PhotoImage refs alive until next redraw
        self._pending_redraw: Optional[str] = None

    # -- public --

    def draw_footprints(
        self,
        records: list[ImageryRecord],
        selected_ids: set[str] | None = None,
    ) -> None:
        """Render footprint boxes for the given records."""
        self._records = [r for r in records if r.has_extent()]
        self._selected_ids = selected_ids or set()
        self._fit_world_to_records()
        self._redraw()

    def highlight_selected(self, selected_ids: set[str]) -> None:
        """Re-render with the given record IDs highlighted."""
        self._selected_ids = selected_ids
        if self._box_map:
            # Fast path: update only outline/width in-place — no tile operations
            for item, record in self._box_map.items():
                is_selected = record.id in selected_ids
                color = COLOR_SELECTED_BOX if is_selected else _footprint_color(record)
                width = 2 if is_selected else 1
                self.itemconfig(item, outline=color, width=width)
        else:
            self._redraw()

    def navigate_to(self, lat: float, lon: float, zoom_deg: float = 2.0) -> None:
        """Pan and zoom the map to centre on the given WGS84 lat/lon."""
        half = zoom_deg / 2.0
        self._world_minx = lon - half
        self._world_maxx = lon + half
        self._world_miny = lat - half
        self._world_maxy = lat + half
        self._schedule_redraw(50)

    # -- internal drawing --

    def _fit_world_to_records(self) -> None:
        if not self._records:
            self._world_minx, self._world_miny = -180.0, -90.0
            self._world_maxx, self._world_maxy = 180.0, 90.0
            return
        self._world_minx = min(r.extent_minx for r in self._records)  # type: ignore[arg-type]
        self._world_miny = min(r.extent_miny for r in self._records)  # type: ignore[arg-type]
        self._world_maxx = max(r.extent_maxx for r in self._records)  # type: ignore[arg-type]
        self._world_maxy = max(r.extent_maxy for r in self._records)  # type: ignore[arg-type]
        dx = (self._world_maxx - self._world_minx) * _WORLD_PAD_FACTOR or 1.0
        dy = (self._world_maxy - self._world_miny) * _WORLD_PAD_FACTOR or 1.0
        self._world_minx -= dx
        self._world_miny -= dy
        self._world_maxx += dx
        self._world_maxy += dy
        self._clamp_view()

    def _fit_aspect(self) -> None:
        """Give the view the same aspect ratio as the canvas.

        World bounds are mapped onto the canvas independently in x and y, so
        unless the two aspect ratios agree the map is drawn squished or
        stretched, and the distortion changes whenever a panel is resized.
        Widening the short axis about the view centre keeps degrees-per-pixel
        equal on both axes, which is what makes the equirectangular basemap
        render undistorted.
        """
        cw = self.winfo_width() or _DEFAULT_CANVAS_W
        ch = self.winfo_height() or _DEFAULT_CANVAS_H
        if cw <= 0 or ch <= 0:
            return
        world_w = self._world_maxx - self._world_minx
        world_h = self._world_maxy - self._world_miny
        if world_w <= 0 or world_h <= 0:
            return

        target = cw / ch          # world_w / world_h the canvas wants
        current = world_w / world_h
        if abs(current - target) < 1e-9:
            return

        if current < target:      # view too tall for the canvas: widen it
            new_w = world_h * target
            mid = (self._world_minx + self._world_maxx) / 2.0
            self._world_minx, self._world_maxx = mid - new_w / 2.0, mid + new_w / 2.0
        else:                     # view too wide: heighten it
            new_h = world_w / target
            mid = (self._world_miny + self._world_maxy) / 2.0
            self._world_miny, self._world_maxy = mid - new_h / 2.0, mid + new_h / 2.0

    def _clamp_view(self) -> None:
        """Keep the visible window inside the world.

        Without this the view can be panned indefinitely past the antimeridian
        or the poles, where the basemap has no pixels to draw but footprints
        keep being plotted, so the two appear to come apart.
        """
        for lo_attr, hi_attr, lo_lim, hi_lim in (
            ("_world_minx", "_world_maxx", -180.0, 180.0),
            ("_world_miny", "_world_maxy", -90.0, 90.0),
        ):
            lo = getattr(self, lo_attr)
            hi = getattr(self, hi_attr)
            span = hi - lo
            limit_span = hi_lim - lo_lim
            if span >= limit_span:      # wider than the world: centre it
                mid = (lo_lim + hi_lim) / 2.0
                lo, hi = mid - span / 2.0, mid + span / 2.0
            elif lo < lo_lim:           # slid off the low edge
                lo, hi = lo_lim, lo_lim + span
            elif hi > hi_lim:           # slid off the high edge
                lo, hi = hi_lim - span, hi_lim
            setattr(self, lo_attr, lo)
            setattr(self, hi_attr, hi)

    def _world_to_canvas(self, wx: float, wy: float) -> tuple[float, float]:
        """Map world lon/lat to canvas pixel coordinates."""
        cw = self.winfo_width() or _DEFAULT_CANVAS_W
        ch = self.winfo_height() or _DEFAULT_CANVAS_H
        draw_w = max(1.0, cw - 2 * _MARGIN)
        draw_h = max(1.0, ch - 2 * _MARGIN)
        world_w = self._world_maxx - self._world_minx or 1.0
        world_h = self._world_maxy - self._world_miny or 1.0
        cx = _MARGIN + (wx - self._world_minx) / world_w * draw_w
        # Canvas Y increases downward; world Y increases upward — flip here
        cy = ch - _MARGIN - (wy - self._world_miny) / world_h * draw_h
        return cx, cy

    def _canvas_to_world(self, cx: float, cy: float) -> tuple[float, float]:
        """Inverse of _world_to_canvas — used to anchor zoom to the mouse cursor."""
        cw = self.winfo_width() or _DEFAULT_CANVAS_W
        ch = self.winfo_height() or _DEFAULT_CANVAS_H
        draw_w = max(1.0, cw - 2 * _MARGIN)
        draw_h = max(1.0, ch - 2 * _MARGIN)
        world_w = self._world_maxx - self._world_minx or 1.0
        world_h = self._world_maxy - self._world_miny or 1.0
        wx = self._world_minx + (cx - _MARGIN) / draw_w * world_w
        wy = self._world_miny + (ch - _MARGIN - cy) / draw_h * world_h
        return wx, wy

    def _schedule_redraw(self, delay_ms: int = 50) -> None:
        """Cancel any pending redraw and schedule a fresh one after delay_ms."""
        if self._pending_redraw is not None:
            try:
                self.after_cancel(self._pending_redraw)
            except tk.TclError:
                pass
        try:
            self._pending_redraw = self.after(delay_ms, self._do_redraw)
        except tk.TclError:
            pass

    def _do_redraw(self) -> None:
        self._pending_redraw = None
        self._redraw()

    def _redraw(self) -> None:
        # The canvas size is only reliable at draw time, so square the view up
        # here. Every visual update goes through this path, which covers panel
        # resizes as well as pan and zoom.
        self._fit_aspect()
        self._clamp_view()
        self.delete("all")
        self._box_map.clear()
        self._tk_basemap_images = []  # safe to clear after delete("all")
        self._hover_item_id = None
        self._draw_basemap()
        cw = self.winfo_width() or _DEFAULT_CANVAS_W
        ch = self.winfo_height() or _DEFAULT_CANVAS_H
        world_minx = self._world_minx
        world_miny = self._world_miny
        world_maxx = self._world_maxx
        world_maxy = self._world_maxy
        for record in self._records:
            # Skip records entirely outside the visible world bounds
            if (record.extent_maxx < world_minx or record.extent_minx > world_maxx or
                    record.extent_maxy < world_miny or record.extent_miny > world_maxy):
                continue
            self._draw_record(record)

    def _draw_basemap(self) -> None:
        if not _TILES_AVAILABLE:
            return
        cw = self.winfo_width() or _DEFAULT_CANVAS_W
        ch = self.winfo_height() or _DEFAULT_CANVAS_H

        # Round world bounds to 4 dp (~11 m precision) so tiny float drifts during
        # interactive pan/zoom don't bust the cache unnecessarily.
        bbox_key = (
            round(self._world_minx, 4), round(self._world_miny, 4),
            round(self._world_maxx, 4), round(self._world_maxy, 4),
            cw, ch,
        )

        # Layer 1: bundled equirectangular world PNG (always attempted first)
        if self._world_basemap_cache is None or self._world_basemap_cache[0] != bbox_key:
            bm_img = self._basemap.render(
                self._world_minx, self._world_miny,
                self._world_maxx, self._world_maxy,
                cw, ch,
            )
            tk_bm = _ImageTk.PhotoImage(bm_img) if bm_img is not None else None
            self._world_basemap_cache = (bbox_key, tk_bm)
        if self._world_basemap_cache[1] is not None:
            self._tk_basemap_images.append(self._world_basemap_cache[1])
            self.create_image(0, 0, anchor=tk.NW, image=self._world_basemap_cache[1])

        # Layer 2: optional user-supplied GeoTIFF basemap drawn on top
        if self._geotiff is not None and self._geotiff.valid:
            if self._geotiff_cache is None or self._geotiff_cache[0] != bbox_key:
                gt_img = self._geotiff.render(
                    self._world_minx, self._world_miny,
                    self._world_maxx, self._world_maxy,
                    cw, ch,
                )
                tk_gt = _ImageTk.PhotoImage(gt_img) if gt_img is not None else None
                self._geotiff_cache = (bbox_key, tk_gt)
            if self._geotiff_cache[1] is not None:
                self._tk_basemap_images.append(self._geotiff_cache[1])
                self.create_image(0, 0, anchor=tk.NW, image=self._geotiff_cache[1])

    def _draw_record(self, record: ImageryRecord) -> None:
        if (record.extent_minx is None or record.extent_miny is None or
                record.extent_maxx is None or record.extent_maxy is None):
            return

        is_selected = record.id in self._selected_ids
        color = COLOR_SELECTED_BOX if is_selected else _footprint_color(record)
        width = 2 if is_selected else 1

        # Preferred: draw the true four-corner quadrilateral ("wireframe") so that
        # off-nadir / NTM collects render with their real, non-rectangular shape.
        if record.corners and len(record.corners) == 4:
            pts: list[float] = []
            xs: list[float] = []
            ys: list[float] = []
            for lon, lat in record.corners:
                cx, cy = self._world_to_canvas(lon, lat)
                pts.extend((cx, cy))
                xs.append(cx)
                ys.append(cy)
            # Skip footprints smaller than 2×2 px — invisible and costly
            if (max(xs) - min(xs)) < 2 and (max(ys) - min(ys)) < 2:
                return
            item = self.create_polygon(*pts, outline=color, fill="", width=width,
                                       tags=("footprint",))
            self._box_map[item] = record
            return

        # Fallback: axis-aligned bounding box (no corner geometry available).
        # Clip to visible world bounds before projecting — prevents off-screen
        # edges from appearing as long lines running across the canvas.
        clip_minx = max(record.extent_minx, self._world_minx)  # type: ignore[type-var]
        clip_miny = max(record.extent_miny, self._world_miny)  # type: ignore[type-var]
        clip_maxx = min(record.extent_maxx, self._world_maxx)  # type: ignore[type-var]
        clip_maxy = min(record.extent_maxy, self._world_maxy)  # type: ignore[type-var]

        x1, y1 = self._world_to_canvas(clip_minx, clip_miny)
        x2, y2 = self._world_to_canvas(clip_maxx, clip_maxy)
        # y1/y2 are flipped because canvas Y increases downward
        top_y, bot_y = min(y1, y2), max(y1, y2)

        # Skip footprints that would render smaller than 2×2 px — invisible and costly
        if abs(x2 - x1) < 2 and (bot_y - top_y) < 2:
            return

        item = self.create_rectangle(x1, top_y, x2, bot_y,
                                     outline=color, fill="", width=width,
                                     tags=("footprint",))
        self._box_map[item] = record

    # -- interaction --

    def _on_resize(self, _event: tk.Event) -> None:
        self._schedule_redraw(50)

    def _on_scroll(self, event: tk.Event) -> None:
        factor = 1.1 if event.delta > 0 else 0.9
        world_w = self._world_maxx - self._world_minx
        world_h = self._world_maxy - self._world_miny
        if world_w <= 0 or world_h <= 0:
            return

        new_w = world_w / factor
        new_h = world_h / factor
        # Test the smaller axis. Keeping the scale uniform means the axis that
        # does not match the canvas shape gets inflated -- on a tall narrow
        # panel the latitude span legitimately exceeds 180 degrees -- so
        # guarding on the larger axis would refuse to zoom at all.
        narrow = min(new_w, new_h)
        if narrow < _MIN_WORLD_EXTENT:      # zoomed in past the useful limit
            return
        if narrow > _MAX_WORLD_EXTENT:      # zoomed out well past the globe
            return

        # Keep the world point under the mouse cursor fixed during zoom
        wx, wy = self._canvas_to_world(event.x, event.y)
        self._world_minx = wx - (wx - self._world_minx) / factor
        self._world_maxx = wx + (self._world_maxx - wx) / factor
        self._world_miny = wy - (wy - self._world_miny) / factor
        self._world_maxy = wy + (self._world_maxy - wy) / factor
        self._clamp_view()
        self._schedule_redraw(50)

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._drag_start = (event.x, event.y)

        cw = self.winfo_width() or _DEFAULT_CANVAS_W
        ch = self.winfo_height() or _DEFAULT_CANVAS_H
        draw_w = max(1.0, cw - 2 * _MARGIN)
        draw_h = max(1.0, ch - 2 * _MARGIN)
        world_w = self._world_maxx - self._world_minx
        world_h = self._world_maxy - self._world_miny
        if world_w <= 0 or world_h <= 0:
            return

        # Update world bounds to track the new viewport position
        world_dx = dx / draw_w * world_w
        world_dy = dy / draw_h * world_h
        self._world_minx -= world_dx
        self._world_maxx -= world_dx
        self._world_miny += world_dy
        self._world_maxy += world_dy
        self._clamp_view()

        # Shift existing canvas items instantly (C-layer move, no recalculation)
        # for responsiveness, then redraw shortly after so the basemap image is
        # re-rendered for the new bounds instead of sliding off the canvas.
        self.move("all", dx, dy)
        self._schedule_redraw(40)

    def _on_drag_end(self, _event: tk.Event) -> None:
        self._drag_start = None
        # Short delay allows the release event to settle before redrawing
        self._schedule_redraw(30)

    def _on_mouse_move(self, event: tk.Event) -> None:
        now_ms = int(time.monotonic() * 1000)
        if now_ms - self._last_mouse_ms < 30:
            # Throttle hit-tests to ~33 fps — tooltip still moves via position update below
            if self._hover_item_id is not None and self._tooltip:
                x = self.winfo_rootx() + event.x + 12
                y = self.winfo_rooty() + event.y + 12
                self._tooltip.wm_geometry(f"+{x}+{y}")
            return
        self._last_mouse_ms = now_ms
        hit = self.find_overlapping(event.x - 2, event.y - 2, event.x + 2, event.y + 2)
        record = None
        for item in reversed(hit):
            if item in self._box_map:
                record = self._box_map[item]
                break

        hovered_id = record.id if record else None
        if hovered_id == self._hover_item_id:
            return
        self._hover_item_id = hovered_id

        if record:
            self._show_tooltip(event, self._tooltip_text(record))
        else:
            self._hide_tooltip()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hide_tooltip()

    @staticmethod
    def _tooltip_text(r: ImageryRecord) -> str:
        lines = [r.scene_name or r.image_id or r.filename]
        if r.image_id:
            lines.append(f"Image ID: {r.image_id}")
        if r.sensor_platform:
            lines.append(f"Sensor:   {r.sensor_platform}")
        if r.image_category:
            label = ICAT_LABELS.get(r.image_category, r.image_category)
            lines.append(f"Category: {label}")
        elif r.image_type:
            lines.append(f"Type:     {r.image_type}")
        if r.acquisition_date:
            has_time = any((r.acquisition_date.hour, r.acquisition_date.minute,
                            r.acquisition_date.second))
            fmt = "%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d"
            lines.append(f"Date:     {r.acquisition_date.strftime(fmt)}")
        if r.width and r.height:
            bands = f"  {r.band_count}B" if r.band_count else ""
            lines.append(f"Size:     {r.width} × {r.height}{bands}")
        if r.classification:
            lines.append(f"Class:    {r.classification}")
        lines.append(f"File:     {format_bytes(r.file_size_bytes)}")
        if r.corners:
            coord_type = f" ({r.icords})" if r.icords else ""
            lines.append(f"Corners{coord_type} lon, lat:")
            lines.extend(f"  {lon:.4f}, {lat:.4f}" for lon, lat in r.corners)
        return "\n".join(lines)

    def _show_tooltip(self, event: tk.Event, text: str) -> None:
        if self._tooltip is None:
            self._tooltip = tk.Toplevel(self)
            self._tooltip.wm_overrideredirect(True)
            from ui.styles import COLOR_TOOLTIP_BG, COLOR_TOOLTIP_FG
            self._tooltip_label = tk.Label(
                self._tooltip, text="", background=COLOR_TOOLTIP_BG,
                foreground=COLOR_TOOLTIP_FG,
                relief="solid", borderwidth=1, wraplength=300,
                justify="left", padx=4, pady=2,
                font=FONT_SMALL,
            )
            self._tooltip_label.pack()
        self._tooltip_label.config(text=text)
        x = self.winfo_rootx() + event.x + 12
        y = self.winfo_rooty() + event.y + 12
        self._tooltip.wm_geometry(f"+{x}+{y}")
        self._tooltip.deiconify()

    def _hide_tooltip(self) -> None:
        if self._tooltip:
            self._tooltip.withdraw()
