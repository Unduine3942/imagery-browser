from __future__ import annotations

import csv
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from downloader import ImageryDownloader
from models import ImageryRecord
from ui.styles import (
    COLOR_BG, COLOR_FRAME_BG, COLOR_HEADER, COLOR_HEADER_FG,
    COLOR_SELECT, COLOR_BTN, COLOR_BTN_FG, COLOR_MUTED, COLOR_TEXT,
    COLOR_ACCENT, COLOR_BORDER,
    COLOR_BTN_NEUTRAL, COLOR_BTN_NEUTRAL_FG,
    FONT_HEADER, FONT_NORMAL, FONT_SMALL, FONT_MONO, PAD, PAD_SMALL,
    format_bytes,
)

_COLUMNS = ("scene", "image_id", "sensor", "type", "category", "classification", "size", "date")
_HEADERS = ("Scene Name", "Image ID", "Sensor/Platform", "Type", "Category", "Class", "Size", "Date")
_WIDTHS   = (170, 110, 110, 50, 80, 50, 70, 90)


class ImageryPanel(tk.Frame):
    """Right-side panel: imagery list, multi-select, and download button."""

    def __init__(
        self,
        master,
        on_selection_change: Callable[[set[str]], None],
        on_open_record: Optional[Callable[[ImageryRecord], None]] = None,
        on_zoom_to_record: Optional[Callable[[ImageryRecord], None]] = None,
        **kwargs,
    ):
        kwargs.setdefault("bg", COLOR_FRAME_BG)
        super().__init__(master, **kwargs)
        self._on_selection_change = on_selection_change
        self._on_open_record = on_open_record
        self._on_zoom_to_record = on_zoom_to_record
        self._records: list[ImageryRecord] = []
        self._id_map: dict[str, ImageryRecord] = {}
        self._sort_col = "scene_name"
        self._sort_rev = False
        self._downloader = ImageryDownloader()
        self._build()

    # -- public --

    def refresh(self, records: list[ImageryRecord]) -> None:
        """Refresh the imagery list with new records."""
        self._records = list(records)
        self._id_map = {r.id: r for r in records}
        self._repopulate()
        self._btn_download.config(state=tk.DISABLED)

    def selected_records(self) -> list[ImageryRecord]:
        """Return the currently selected ImageryRecord objects."""
        return [self._id_map[i] for i in self._tree.selection() if i in self._id_map]

    def selected_ids(self) -> set[str]:
        """Return the IDs of currently selected records."""
        return {r.id for r in self.selected_records()}

    # -- build --

    def _build(self) -> None:
        # Header
        header = tk.Frame(self, bg=COLOR_HEADER, padx=PAD, pady=PAD_SMALL)
        header.pack(fill=tk.X)
        tk.Label(header, text="Available Imagery", bg=COLOR_HEADER, fg=COLOR_HEADER_FG,
                 font=FONT_HEADER).pack(side=tk.LEFT)
        self._count_label = tk.Label(header, text="0 items", bg=COLOR_HEADER,
                                     fg=COLOR_HEADER_FG, font=FONT_SMALL)
        self._count_label.pack(side=tk.RIGHT)

        # Treeview + scrollbars
        tree_frame = tk.Frame(self, bg=COLOR_FRAME_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=_COLUMNS,
            show="headings",
            selectmode="extended",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        for col, header_text, width in zip(_COLUMNS, _HEADERS, _WIDTHS):
            self._tree.heading(col, text=header_text,
                               command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=width, anchor=tk.W, stretch=False)

        self._tree.tag_configure("odd",  background=COLOR_BG)
        self._tree.tag_configure("even", background=COLOR_FRAME_BG)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", self._on_open)
        self._tree.bind("<Button-3>", self._on_right_click)

        # Right-click context menu
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="View Metadata…", command=self._show_metadata)
        self._menu.add_command(label="Zoom to Image", command=self._zoom_to)
        self._menu.add_command(label="Download Image…", command=self._on_download)
        self._menu.add_separator()
        self._menu.add_command(label="Open / Clip…", command=self._on_open)

        # Bottom bar
        bottom = tk.Frame(self, bg=COLOR_FRAME_BG, pady=PAD)
        bottom.pack(fill=tk.X, padx=PAD)

        self._sel_label = tk.Label(bottom, text="0 selected", bg=COLOR_FRAME_BG,
                                   fg=COLOR_MUTED, font=FONT_SMALL)
        self._sel_label.pack(side=tk.LEFT)

        self._btn_download = tk.Button(
            bottom, text="Download Selected",
            bg=COLOR_BTN, fg=COLOR_BTN_FG,
            font=FONT_NORMAL, relief=tk.FLAT,
            padx=10, state=tk.DISABLED,
            command=self._on_download,
        )
        self._btn_download.pack(side=tk.RIGHT)

        tk.Button(
            bottom, text="Export CSV…",
            bg=COLOR_BTN_NEUTRAL, fg=COLOR_BTN_NEUTRAL_FG,
            font=FONT_NORMAL, relief=tk.FLAT, padx=8,
            command=self._export_csv,
        ).pack(side=tk.RIGHT, padx=(0, PAD_SMALL))

        self._btn_open = tk.Button(
            bottom, text="Open / Clip…",
            bg=COLOR_BTN, fg=COLOR_BTN_FG,
            font=FONT_NORMAL, relief=tk.FLAT, padx=10, state=tk.DISABLED,
            command=self._on_open,
        )
        self._btn_open.pack(side=tk.RIGHT, padx=(0, PAD_SMALL))

    # -- populate --

    def _repopulate(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._count_label.config(text=f"{len(self._records)} items")
        self._tree["displaycolumns"] = _COLUMNS
        for col, hdr, w in zip(_COLUMNS, _HEADERS, _WIDTHS):
            self._tree.heading(col, text=hdr, command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=w, anchor=tk.W, stretch=(col == "scene"))

        for i, r in enumerate(self._records):
            tag = "odd" if i % 2 else "even"
            date = r.acquisition_date.strftime("%Y-%m-%d") if r.acquisition_date else "—"
            self._tree.insert("", tk.END, iid=r.id, tags=(tag,), values=(
                r.scene_name or r.filename,
                r.image_id or "—",
                r.sensor_platform or "—",
                r.image_type or "—",
                r.image_category or "—",
                r.classification or "—",
                format_bytes(r.file_size_bytes),
                date,
            ))

    # -- sort --

    def _sort_by(self, col: str) -> None:
        sort_map = {
            "scene":          "scene_name",
            "image_id":       "image_id",
            "sensor":         "sensor_platform",
            "type":           "image_type",
            "category":       "image_category",
            "classification": "image_category",
            "size":           "file_size",
            "date":           "acquisition_date",
        }
        key = sort_map.get(col, "filename")
        if self._sort_col == key:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = key
            self._sort_rev = False

        from imagery_manager import ImageryManager
        mgr = ImageryManager(self._records)
        self._records = mgr.sort_records(self._records, self._sort_col, self._sort_rev)
        for i, r in enumerate(self._records):
            self._tree.move(r.id, "", i)
            self._tree.item(r.id, tags=("odd" if i % 2 else "even",))
        self._count_label.config(text=f"{len(self._records)} items")

    # -- selection --

    def _on_select(self, _event: tk.Event) -> None:
        sel = self._tree.selection()
        n = len(sel)
        self._sel_label.config(text=f"{n} selected")
        self._btn_download.config(state=tk.NORMAL if n > 0 else tk.DISABLED)
        self._btn_open.config(state=tk.NORMAL if n == 1 else tk.DISABLED)
        self._on_selection_change(set(sel))  # iids are record ids

    # -- context menu --

    def _on_right_click(self, event: tk.Event) -> None:
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        # Right-clicking outside the current selection retargets it
        if iid not in self._tree.selection():
            self._tree.selection_set(iid)
        self._tree.focus(iid)
        single = len(self._tree.selection()) == 1
        self._menu.entryconfig("View Metadata…",
                               state=tk.NORMAL if single else tk.DISABLED)
        self._menu.entryconfig("Zoom to Image",
                               state=tk.NORMAL if single else tk.DISABLED)
        self._menu.entryconfig("Open / Clip…",
                               state=tk.NORMAL if single else tk.DISABLED)
        self._menu.tk_popup(event.x_root, event.y_root)

    def _focused_record(self) -> Optional[ImageryRecord]:
        records = self.selected_records()
        return records[0] if len(records) == 1 else None

    def _show_metadata(self) -> None:
        record = self._focused_record()
        if record is not None:
            MetadataDialog(self, record)

    def _zoom_to(self) -> None:
        record = self._focused_record()
        if record is None:
            return
        if record.extent_minx is None:
            messagebox.showinfo(
                "Zoom to Image",
                f"'{record.scene_name or record.filename}' has no georeference "
                "— it cannot be located on the map.",
                parent=self,
            )
            return
        if self._on_zoom_to_record is not None:
            self._on_zoom_to_record(record)

    # -- open / clip --

    def _on_open(self, _event: tk.Event | None = None) -> None:
        """Open the (single) selected record in the image viewer for clipping."""
        if self._on_open_record is None:
            return
        records = self.selected_records()
        if len(records) != 1:
            return
        self._on_open_record(records[0])

    # -- download --

    def _on_download(self) -> None:
        records = self.selected_records()
        if not records:
            return
        dest_dir = filedialog.askdirectory(title="Choose download destination")
        if not dest_dir:
            return
        result = self._downloader.copy_to(records, dest_dir)
        messagebox.showinfo("Download Complete", result.summary())

    # -- export --

    def _export_csv(self) -> None:
        if not self._records:
            messagebox.showinfo("Export CSV", "No records to export.")
            return
        path = filedialog.asksaveasfilename(
            title="Export imagery list as CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        fields = [
            "filename", "scene_name", "image_id", "image_title",
            "sensor_platform", "image_type", "image_category", "image_source",
            "classification", "file_title", "num_image_segments",
            "format", "file_size_bytes", "acquisition_date", "ingest_date",
            "extent_minx", "extent_miny", "extent_maxx", "extent_maxy",
            "icords", "corners",
            "width", "height", "band_count", "spatial_ref_wkid", "filepath",
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for r in self._records:
                    writer.writerow({
                        "filename": r.filename,
                        "scene_name": r.scene_name or "",
                        "image_id": r.image_id or "",
                        "image_title": r.image_title or "",
                        "sensor_platform": r.sensor_platform or "",
                        "image_type": r.image_type or "",
                        "image_category": r.image_category or "",
                        "image_source": r.image_source or "",
                        "classification": r.classification or "",
                        "file_title": r.file_title or "",
                        "num_image_segments": r.num_image_segments if r.num_image_segments is not None else "",
                        "icords": r.icords or "",
                        "corners": "; ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in r.corners) if r.corners else "",
                        "format": r.format,
                        "file_size_bytes": r.file_size_bytes,
                        "acquisition_date": r.acquisition_date.isoformat() if r.acquisition_date else "",
                        "ingest_date": r.ingest_date.isoformat(),
                        "extent_minx": r.extent_minx if r.extent_minx is not None else "",
                        "extent_miny": r.extent_miny if r.extent_miny is not None else "",
                        "extent_maxx": r.extent_maxx if r.extent_maxx is not None else "",
                        "extent_maxy": r.extent_maxy if r.extent_maxy is not None else "",
                        "width": r.width if r.width is not None else "",
                        "height": r.height if r.height is not None else "",
                        "band_count": r.band_count if r.band_count is not None else "",
                        "spatial_ref_wkid": r.spatial_ref_wkid if r.spatial_ref_wkid is not None else "",
                        "filepath": r.filepath,
                    })
            messagebox.showinfo("Export CSV", f"Exported {len(self._records)} record(s) to:\n{path}")
        except OSError as exc:
            messagebox.showerror("Export CSV", f"Failed to write file:\n{exc}")


class MetadataDialog(tk.Toplevel):
    """Read-only view of EVERY populated field on one imagery record."""

    _SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
        ("File", [
            ("filename", "Filename"),
            ("filepath", "Full Path"),
            ("format", "Format"),
            ("file_size_bytes", "File Size"),
            ("ingest_date", "Ingest Date"),
            ("file_title", "File Title (NITF)"),
            ("classification", "Classification"),
        ]),
        ("Image", [
            ("scene_name", "Scene Name"),
            ("image_id", "Image ID"),
            ("image_title", "Image Title"),
            ("sensor_platform", "Sensor / Platform"),
            ("image_type", "Image Type"),
            ("image_category", "Category (ICAT)"),
            ("image_source", "Source (ISORCE)"),
            ("num_image_segments", "Image Segments"),
            ("acquisition_date", "Acquisition Date"),
            ("width", "Width (px)"),
            ("height", "Height (px)"),
            ("band_count", "Bands"),
        ]),
        ("Geographic", [
            ("spatial_ref_wkid", "Spatial Ref (WKID)"),
            ("icords", "ICORDS"),
            ("extent_minx", "Extent Min X"),
            ("extent_miny", "Extent Min Y"),
            ("extent_maxx", "Extent Max X"),
            ("extent_maxy", "Extent Max Y"),
            ("centroid_x", "Centroid X"),
            ("centroid_y", "Centroid Y"),
        ]),
    ]

    def __init__(self, parent: tk.Widget, record: ImageryRecord) -> None:
        super().__init__(parent)
        self.title(f"Metadata — {record.scene_name or record.filename}")
        self.configure(bg=COLOR_BG)
        self.geometry("560x620")
        self.minsize(460, 400)
        self.grab_set()

        # Scrollable body
        canvas = tk.Canvas(self, bg=COLOR_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(fill=tk.BOTH, expand=True)
        body = tk.Frame(canvas, bg=COLOR_BG, padx=14, pady=10)
        win = canvas.create_window((0, 0), window=body, anchor=tk.NW)
        body.bind("<Configure>",
                  lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))

        for section, fields in self._SECTIONS:
            rows = [(label, self._fmt(record, attr, getattr(record, attr, None)))
                    for attr, label in fields]
            rows = [(label, value) for label, value in rows if value is not None]
            if not rows:
                continue
            tk.Label(body, text=section.upper(), bg=COLOR_BG, fg=COLOR_ACCENT,
                     font=FONT_HEADER, anchor=tk.W).pack(fill=tk.X, pady=(8, 2))
            tk.Frame(body, bg=COLOR_BORDER, height=1).pack(fill=tk.X, pady=(0, 4))
            for label, value in rows:
                row = tk.Frame(body, bg=COLOR_BG)
                row.pack(fill=tk.X, pady=1)
                tk.Label(row, text=label, bg=COLOR_BG, fg=COLOR_MUTED,
                         font=FONT_SMALL, width=20, anchor=tk.NW,
                         justify=tk.LEFT).pack(side=tk.LEFT)
                tk.Label(row, text=value, bg=COLOR_BG, fg=COLOR_TEXT,
                         font=FONT_MONO, anchor=tk.NW, justify=tk.LEFT,
                         wraplength=340).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Corner geometry (NITF IGEOLO)
        if record.corners:
            tk.Label(body, text="CORNERS (UL, UR, LR, LL)", bg=COLOR_BG,
                     fg=COLOR_ACCENT, font=FONT_HEADER, anchor=tk.W).pack(
                fill=tk.X, pady=(8, 2))
            tk.Frame(body, bg=COLOR_BORDER, height=1).pack(fill=tk.X, pady=(0, 4))
            corner_text = "\n".join(
                f"{name}:  {lon:>12.6f}, {lat:>11.6f}"
                for name, (lon, lat) in zip(("UL", "UR", "LR", "LL"), record.corners)
            )
            tk.Label(body, text=corner_text, bg=COLOR_BG, fg=COLOR_TEXT,
                     font=FONT_MONO, anchor=tk.W, justify=tk.LEFT).pack(fill=tk.X)

        tk.Button(self, text="Close", bg=COLOR_BTN_NEUTRAL,
                  fg=COLOR_BTN_NEUTRAL_FG, font=FONT_NORMAL, relief=tk.FLAT,
                  padx=14, command=self.destroy).pack(pady=8)

    @staticmethod
    def _fmt(record: ImageryRecord, attr: str, value) -> str | None:
        """Format one field for display; None hides the row entirely."""
        if value is None or value == "":
            return None
        if attr == "file_size_bytes":
            return f"{format_bytes(value)}  ({value:,} bytes)"
        if attr in ("acquisition_date", "ingest_date"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if attr in ("extent_minx", "extent_miny", "extent_maxx", "extent_maxy",
                    "centroid_x", "centroid_y"):
            return f"{value:.6f}"
        return str(value)
