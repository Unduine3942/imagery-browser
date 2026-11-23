"""
ui/image_viewer.py — open a single imagery record, pan/zoom it, draw a
rectangular region, and export that region as a georeferenced GeoTIFF clip
and/or a PNG snapshot.

All raster I/O goes through clipper.py (rasterio/GDAL/PIL guarded), so the
on-screen preview can be downsampled while the exported GeoTIFF clip is always
read from the source at native resolution.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import clipper
from models import ImageryRecord
from ui.styles import (
    COLOR_BG, COLOR_FRAME_BG, COLOR_HEADER, COLOR_HEADER_FG,
    COLOR_BTN, COLOR_BTN_FG, COLOR_MUTED, COLOR_WARN, COLOR_SELECTED_BOX,
    COLOR_BTN_NEUTRAL, COLOR_BTN_NEUTRAL_FG,
    FONT_HEADER, FONT_NORMAL, FONT_SMALL, PAD, PAD_SMALL,
)

log = logging.getLogger(__name__)

try:
    from PIL import ImageTk as _ImageTk
    _IMAGETK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ImageTk = None  # type: ignore[assignment]
    _IMAGETK_AVAILABLE = False

_PREVIEW_MAX_PX = 2048      # resident downsampled preview cap
_SNAPSHOT_MAX_PX = 4096     # snapshot render cap
_MIN_VIEW_PX = 16           # don't zoom in past this many preview px across


class ImageViewerWindow(tk.Toplevel):
    """Top-level window that previews one raster and exports clips/snapshots."""

    def __init__(self, master, record: ImageryRecord) -> None:
        super().__init__(master)
        self._record = record
        self._src_path = record.filepath

        self.title(f"Image Viewer — {record.filename}")
        self.geometry("960x720")
        self.configure(bg=COLOR_BG)
        self.minsize(640, 480)

        # Source dimensions + downsampled preview.
        self._info = clipper.raster_info(self._src_path)
        self._preview = (
            clipper.read_region_as_image(self._src_path, 0, 0, 0, 0, max_px=_PREVIEW_MAX_PX)
            if self._info else None
        )
        if self._info is None or self._preview is None or not _IMAGETK_AVAILABLE:
            self._build_unavailable()
            return

        # preview px ↔ source px (preview is a uniform downsample of the source).
        self._preview_scale = self._preview.width / max(1, self._info.width)

        # View rectangle in *preview* pixel coords (what is currently shown).
        self._vx0, self._vy0 = 0.0, 0.0
        self._vx1 = float(self._preview.width)
        self._vy1 = float(self._preview.height)

        # Displayed-image placement on the canvas (filled in by _render).
        self._disp_off = (0, 0)
        self._disp_size = (1, 1)
        self._tk_img: Optional["_ImageTk.PhotoImage"] = None

        self._draw_mode = False
        self._drag_start: Optional[tuple[int, int]] = None
        self._sel_rect_item: Optional[int] = None
        self._selection_src: Optional[tuple[int, int, int, int]] = None  # col,row,w,h

        self._build_ui()
        self.bind("<Escape>", lambda _e: self._cancel_selection())

    # -- build --

    def _build_unavailable(self) -> None:
        msg = "Cannot open this image."
        if not _IMAGETK_AVAILABLE:
            msg = "Image preview requires Pillow (PIL.ImageTk), which is not available."
        elif self._info is None:
            msg = f"Could not read raster:\n{self._src_path}"
        tk.Label(self, text=msg, bg=COLOR_BG, fg=COLOR_WARN,
                 font=FONT_NORMAL, wraplength=520, justify=tk.LEFT,
                 padx=PAD * 2, pady=PAD * 2).pack(expand=True)
        tk.Button(self, text="Close", command=self.destroy,
                  bg=COLOR_BTN, fg=COLOR_BTN_FG, relief=tk.FLAT, padx=12).pack(pady=PAD)

    def _build_ui(self) -> None:
        toolbar = tk.Frame(self, bg=COLOR_HEADER, padx=PAD, pady=PAD_SMALL)
        toolbar.pack(fill=tk.X)

        dims = f"{self._info.width} × {self._info.height} px"
        geo = "georeferenced" if self._info.has_crs else "no georeferencing"
        tk.Label(toolbar, text=f"{dims}  ·  {geo}", bg=COLOR_HEADER,
                 fg=COLOR_HEADER_FG, font=FONT_SMALL).pack(side=tk.LEFT)

        self._btn_draw = tk.Button(
            toolbar, text="Draw clip region", bg=COLOR_BTN, fg=COLOR_BTN_FG,
            font=FONT_NORMAL, relief=tk.FLAT, padx=10, command=self._toggle_draw_mode,
        )
        self._btn_draw.pack(side=tk.LEFT, padx=(PAD, 0))

        tk.Button(toolbar, text="Save GeoTIFF clip…", bg=COLOR_BTN, fg=COLOR_BTN_FG,
                  font=FONT_NORMAL, relief=tk.FLAT, padx=10,
                  command=self._save_clip).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))
        tk.Button(toolbar, text="Save PNG snapshot…", bg=COLOR_BTN, fg=COLOR_BTN_FG,
                  font=FONT_NORMAL, relief=tk.FLAT, padx=10,
                  command=self._save_snapshot).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))
        tk.Button(toolbar, text="Reset view", bg=COLOR_BTN_NEUTRAL,
                  fg=COLOR_BTN_NEUTRAL_FG,
                  font=FONT_NORMAL, relief=tk.FLAT, padx=8,
                  command=self._reset_view).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))

        self._canvas = tk.Canvas(self, bg=COLOR_BG, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._status = tk.Label(
            self, text="Scroll to zoom · drag to pan · 'Draw clip region' then drag to select",
            bg=COLOR_FRAME_BG, fg=COLOR_MUTED, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._status.pack(fill=tk.X)

        self._canvas.bind("<Configure>", lambda _e: self._render())
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

    # -- rendering --

    def _render(self) -> None:
        if self._preview is None:
            return
        cw = max(1, self._canvas.winfo_width())
        ch = max(1, self._canvas.winfo_height())
        view = self._preview.crop((int(self._vx0), int(self._vy0),
                                   int(self._vx1), int(self._vy1)))
        vw, vh = max(1, view.width), max(1, view.height)
        scale = min(cw / vw, ch / vh)
        disp_w, disp_h = max(1, int(vw * scale)), max(1, int(vh * scale))
        off_x, off_y = (cw - disp_w) // 2, (ch - disp_h) // 2
        self._disp_off = (off_x, off_y)
        self._disp_size = (disp_w, disp_h)

        from PIL import Image
        shown = view.resize((disp_w, disp_h), Image.BILINEAR)
        self._tk_img = _ImageTk.PhotoImage(shown)
        self._canvas.delete("all")
        self._canvas.create_image(off_x, off_y, anchor=tk.NW, image=self._tk_img)
        self._sel_rect_item = None
        self._redraw_selection()

    def _redraw_selection(self) -> None:
        """Redraw the persisted selection rectangle (in source px) onto the canvas."""
        if self._selection_src is None:
            return
        col, row, w, h = self._selection_src
        x0, y0 = self._source_to_canvas(col, row)
        x1, y1 = self._source_to_canvas(col + w, row + h)
        self._sel_rect_item = self._canvas.create_rectangle(
            x0, y0, x1, y1, outline=COLOR_SELECTED_BOX, width=2,
        )

    # -- coordinate mapping --

    def _canvas_to_source(self, cx: float, cy: float) -> tuple[float, float]:
        off_x, off_y = self._disp_off
        disp_w, disp_h = self._disp_size
        # canvas → preview px (within current view)
        pvx = self._vx0 + (cx - off_x) * (self._vx1 - self._vx0) / disp_w
        pvy = self._vy0 + (cy - off_y) * (self._vy1 - self._vy0) / disp_h
        # preview px → source px
        return pvx / self._preview_scale, pvy / self._preview_scale

    def _source_to_canvas(self, sx: float, sy: float) -> tuple[float, float]:
        off_x, off_y = self._disp_off
        disp_w, disp_h = self._disp_size
        pvx = sx * self._preview_scale
        pvy = sy * self._preview_scale
        cx = off_x + (pvx - self._vx0) * disp_w / (self._vx1 - self._vx0)
        cy = off_y + (pvy - self._vy0) * disp_h / (self._vy1 - self._vy0)
        return cx, cy

    # -- interaction --

    def _toggle_draw_mode(self) -> None:
        self._draw_mode = not self._draw_mode
        self._btn_draw.config(relief=tk.SUNKEN if self._draw_mode else tk.FLAT,
                              bg=COLOR_SELECTED_BOX if self._draw_mode else COLOR_BTN)
        self._status.config(
            text="Draw mode ON — drag to select a region (Esc to cancel)"
            if self._draw_mode else
            "Scroll to zoom · drag to pan · 'Draw clip region' then drag to select"
        )

    def _on_press(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)
        if self._draw_mode and self._sel_rect_item is not None:
            self._canvas.delete(self._sel_rect_item)
            self._sel_rect_item = None

    def _on_motion(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        if self._draw_mode:
            x0, y0 = self._drag_start
            if self._sel_rect_item is not None:
                self._canvas.delete(self._sel_rect_item)
            self._sel_rect_item = self._canvas.create_rectangle(
                x0, y0, event.x, event.y, outline=COLOR_SELECTED_BOX, width=2,
            )
        else:
            self._pan(event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        if self._draw_mode:
            self._finish_selection(self._drag_start, (event.x, event.y))
        self._drag_start = None

    def _pan(self, cx: int, cy: int) -> None:
        sx, sy = self._drag_start  # type: ignore[misc]
        disp_w, disp_h = self._disp_size
        dvx = (sx - cx) * (self._vx1 - self._vx0) / disp_w
        dvy = (sy - cy) * (self._vy1 - self._vy0) / disp_h
        pw, ph = self._preview.width, self._preview.height  # type: ignore[union-attr]
        # Keep the view within the preview bounds.
        if self._vx0 + dvx < 0:
            dvx = -self._vx0
        if self._vx1 + dvx > pw:
            dvx = pw - self._vx1
        if self._vy0 + dvy < 0:
            dvy = -self._vy0
        if self._vy1 + dvy > ph:
            dvy = ph - self._vy1
        self._vx0 += dvx; self._vx1 += dvx
        self._vy0 += dvy; self._vy1 += dvy
        self._drag_start = (cx, cy)
        self._render()

    def _on_wheel(self, event: tk.Event) -> None:
        factor = 0.85 if event.delta > 0 else 1.0 / 0.85
        # Anchor zoom at the cursor.
        off_x, off_y = self._disp_off
        disp_w, disp_h = self._disp_size
        ax = self._vx0 + (event.x - off_x) * (self._vx1 - self._vx0) / disp_w
        ay = self._vy0 + (event.y - off_y) * (self._vy1 - self._vy0) / disp_h
        new_w = (self._vx1 - self._vx0) * factor
        new_h = (self._vy1 - self._vy0) * factor
        pw, ph = self._preview.width, self._preview.height  # type: ignore[union-attr]
        if new_w < _MIN_VIEW_PX or new_h < _MIN_VIEW_PX:
            return
        if new_w > pw and new_h > ph:
            self._reset_view()
            return
        rx = (ax - self._vx0) / max(1e-6, self._vx1 - self._vx0)
        ry = (ay - self._vy0) / max(1e-6, self._vy1 - self._vy0)
        self._vx0 = ax - rx * new_w
        self._vx1 = self._vx0 + new_w
        self._vy0 = ay - ry * new_h
        self._vy1 = self._vy0 + new_h
        # Clamp into preview.
        self._vx0 = max(0.0, self._vx0); self._vy0 = max(0.0, self._vy0)
        self._vx1 = min(float(pw), self._vx1); self._vy1 = min(float(ph), self._vy1)
        self._render()

    def _reset_view(self) -> None:
        self._vx0, self._vy0 = 0.0, 0.0
        self._vx1 = float(self._preview.width)   # type: ignore[union-attr]
        self._vy1 = float(self._preview.height)  # type: ignore[union-attr]
        self._render()

    def _cancel_selection(self) -> None:
        self._selection_src = None
        if self._sel_rect_item is not None:
            self._canvas.delete(self._sel_rect_item)
            self._sel_rect_item = None
        self._status.config(text="Selection cleared.")

    def _finish_selection(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        (x0, y0), (x1, y1) = start, end
        if abs(x1 - x0) < 3 or abs(y1 - y0) < 3:
            self._selection_src = None
            return
        sx0, sy0 = self._canvas_to_source(min(x0, x1), min(y0, y1))
        sx1, sy1 = self._canvas_to_source(max(x0, x1), max(y0, y1))
        col, row = int(round(sx0)), int(round(sy0))
        w, h = int(round(sx1 - sx0)), int(round(sy1 - sy0))
        col = max(0, col); row = max(0, row)
        w = max(1, min(w, self._info.width - col))
        h = max(1, min(h, self._info.height - row))
        self._selection_src = (col, row, w, h)
        self._status.config(text=f"Selected region: {w} × {h} px at ({col}, {row}).")

    # -- export --

    def _require_selection(self) -> Optional[tuple[int, int, int, int]]:
        if self._selection_src is None:
            messagebox.showinfo(
                "No region selected",
                "Click 'Draw clip region' and drag a rectangle over the area first.",
                parent=self,
            )
            return None
        return self._selection_src

    def _default_name(self, suffix: str) -> str:
        return f"{Path(self._record.filename).stem}_{suffix}"

    def _save_clip(self) -> None:
        sel = self._require_selection()
        if sel is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save GeoTIFF clip",
            defaultextension=".tif",
            initialfile=self._default_name("clip.tif"),
            filetypes=[("GeoTIFF", "*.tif *.tiff"), ("All files", "*.*")],
        )
        if not path:
            return
        col, row, w, h = sel
        result = clipper.clip_geotiff_by_pixels(self._src_path, col, row, w, h, path)
        if result.ok:
            geo = "georeferenced" if result.georeferenced else "no CRS (source not georeferenced)"
            messagebox.showinfo(
                "Clip saved",
                f"Saved {result.width} × {result.height} px clip ({geo}) via {result.backend}:\n{result.out_path}",
                parent=self,
            )
        else:
            messagebox.showerror("Clip failed", result.error, parent=self)

    def _save_snapshot(self) -> None:
        # Snapshot the selected region if any, else the current view.
        if self._selection_src is not None:
            col, row, w, h = self._selection_src
        else:
            sx0, sy0 = self._vx0 / self._preview_scale, self._vy0 / self._preview_scale
            sx1, sy1 = self._vx1 / self._preview_scale, self._vy1 / self._preview_scale
            col, row = int(sx0), int(sy0)
            w, h = int(sx1 - sx0), int(sy1 - sy0)

        path = filedialog.asksaveasfilename(
            parent=self, title="Save PNG snapshot",
            defaultextension=".png",
            initialfile=self._default_name("snapshot.png"),
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        img = clipper.read_region_as_image(self._src_path, col, row, w, h, max_px=_SNAPSHOT_MAX_PX)
        if img is None:
            messagebox.showerror("Snapshot failed", "Could not read the selected region.", parent=self)
            return
        result = clipper.save_snapshot_png(img, path)
        if result.ok:
            messagebox.showinfo("Snapshot saved", f"Saved snapshot:\n{result.out_path}", parent=self)
        else:
            messagebox.showerror("Snapshot failed", result.error, parent=self)
