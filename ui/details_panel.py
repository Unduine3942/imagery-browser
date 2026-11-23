from __future__ import annotations

import tkinter as tk
from typing import Optional

from models import ImageryRecord
from ui import wheel
from ui.styles import (
    COLOR_FRAME_BG, COLOR_HEADER, COLOR_HEADER_FG, COLOR_SECTION_BG,
    COLOR_MUTED, COLOR_TEXT, COLOR_BORDER, ICAT_LABELS,
    FONT_HEADER, FONT_NORMAL, FONT_SMALL, FONT_MONO, PAD, PAD_SMALL,
    format_bytes,
)

_PLACEHOLDER = "Select an image to view its NITF / NTM metadata."


class DetailsPanel(tk.Frame):
    """Metadata inspector for the selected image — file-level and image-subheader
    NITF 2.1 fields grouped for NTM imagery review."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("bg", COLOR_FRAME_BG)
        super().__init__(master, **kwargs)
        self._build()

    # -- build --

    def _build(self) -> None:
        header = tk.Frame(self, bg=COLOR_HEADER, padx=PAD, pady=PAD_SMALL)
        header.pack(fill=tk.X)
        tk.Label(header, text="Image Details", bg=COLOR_HEADER, fg=COLOR_HEADER_FG,
                 font=FONT_HEADER).pack(side=tk.LEFT)

        # NITF/NTM records carry more metadata than fits in this pane, so the
        # body scrolls. Without it the lower sections are simply unreachable
        # whenever the pane is shorter than the content.
        wrap = tk.Frame(self, bg=COLOR_FRAME_BG)
        wrap.pack(fill=tk.BOTH, expand=True)

        self._scroll_canvas = tk.Canvas(
            wrap, bg=COLOR_FRAME_BG, highlightthickness=0, bd=0,
        )
        vsb = tk.Scrollbar(wrap, orient=tk.VERTICAL,
                           command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                 padx=(PAD, 0), pady=PAD_SMALL)

        self._body = tk.Frame(self._scroll_canvas, bg=COLOR_FRAME_BG)
        self._body_window = self._scroll_canvas.create_window(
            (0, 0), window=self._body, anchor=tk.NW,
        )

        def _on_body_configure(_event=None) -> None:
            self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all"))

        def _on_canvas_configure(event) -> None:
            # Keep the inner frame as wide as the viewport so text wraps
            # against the panel rather than scrolling sideways.
            self._scroll_canvas.itemconfigure(self._body_window,
                                              width=event.width)

        self._body.bind("<Configure>", _on_body_configure)
        self._scroll_canvas.bind("<Configure>", _on_canvas_configure)

        # Registering the panel itself covers every row built inside it, which
        # an <Enter>/<Leave> grab would not: moving onto a child label fires
        # <Leave> on the container and would silently drop the binding.
        wheel.register(self, self._on_wheel)

        self._show_placeholder()

    # -- scrolling --

    def _on_wheel(self, event) -> None:
        if self._scroll_canvas.bbox("all") is None:
            return
        self._scroll_canvas.yview_scroll(-1 * (event.delta // 120), "units")

    # -- public --

    def show(self, record: Optional[ImageryRecord]) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        if record is None:
            self._show_placeholder()
            return

        self._section("File")
        self._row("Title", record.file_title)
        self._row("Classification", record.classification)
        self._row("Image Segments", record.num_image_segments)
        self._row("Format", record.format)

        self._section("Image")
        self._row("Image ID", record.image_id)
        self._row("Title", record.image_title)
        self._row("Date / Time", self._fmt_datetime(record))
        self._row("Category", self._fmt_category(record))
        self._row("Source", record.image_source)
        self._row("Dimensions", self._fmt_dimensions(record))
        self._row("File Size", format_bytes(record.file_size_bytes))

        self._section("Geographic")
        self._row("Coord System", record.icords)
        self._row("EPSG / WKID", record.spatial_ref_wkid)
        self._corners(record)

    # -- helpers --

    def _show_placeholder(self) -> None:
        tk.Label(self._body, text=_PLACEHOLDER, bg=COLOR_FRAME_BG, fg=COLOR_MUTED,
                 font=FONT_SMALL, wraplength=300, justify=tk.LEFT).pack(anchor=tk.W, pady=PAD)

    def _section(self, title: str) -> None:
        tk.Label(self._body, text=title.upper(), bg=COLOR_FRAME_BG, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(anchor=tk.W, pady=(PAD_SMALL, 0))
        tk.Frame(self._body, bg=COLOR_BORDER, height=1).pack(fill=tk.X, pady=(0, PAD_SMALL))

    def _row(self, label: str, value) -> None:
        text = "—" if value is None or value == "" else str(value)
        row = tk.Frame(self._body, bg=COLOR_FRAME_BG)
        row.pack(fill=tk.X)
        tk.Label(row, text=f"{label}:", bg=COLOR_FRAME_BG, fg=COLOR_MUTED,
                 font=FONT_SMALL, width=14, anchor=tk.W).pack(side=tk.LEFT)
        tk.Label(row, text=text, bg=COLOR_FRAME_BG, fg=COLOR_TEXT, font=FONT_NORMAL,
                 anchor=tk.W, justify=tk.LEFT, wraplength=200).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _corners(self, record: ImageryRecord) -> None:
        if not record.corners:
            self._row("Corners", None)
            return
        tk.Label(self._body, text="Corners (lon, lat):", bg=COLOR_FRAME_BG, fg=COLOR_MUTED,
                 font=FONT_SMALL, anchor=tk.W).pack(anchor=tk.W)
        box = tk.Frame(self._body, bg=COLOR_SECTION_BG, highlightbackground=COLOR_BORDER,
                       highlightthickness=1)
        box.pack(fill=tk.X, pady=(0, PAD_SMALL))
        labels = ("UL", "UR", "LR", "LL")
        for i, (lon, lat) in enumerate(record.corners):
            tag = labels[i] if i < len(labels) else str(i + 1)
            tk.Label(box, text=f"{tag}  {lon:>11.5f}, {lat:>10.5f}", bg=COLOR_SECTION_BG,
                     fg=COLOR_TEXT, font=FONT_MONO, anchor=tk.W).pack(anchor=tk.W, padx=PAD_SMALL)

    @staticmethod
    def _fmt_datetime(record: ImageryRecord) -> Optional[str]:
        dt = record.acquisition_date
        if dt is None:
            return None
        has_time = any((dt.hour, dt.minute, dt.second))
        return dt.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d")

    @staticmethod
    def _fmt_category(record: ImageryRecord) -> Optional[str]:
        cat = record.image_category
        if not cat:
            return None
        label = ICAT_LABELS.get(cat)
        return f"{cat} — {label}" if label else cat

    @staticmethod
    def _fmt_dimensions(record: ImageryRecord) -> Optional[str]:
        if record.width and record.height:
            bands = f" × {record.band_count} band(s)" if record.band_count else ""
            return f"{record.width} × {record.height} px{bands}"
        return None
