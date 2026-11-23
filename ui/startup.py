from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

from config import MAX_BASEMAP_BYTES, MAX_BASEMAP_MB
from ui.styles import (
    COLOR_BG, COLOR_FRAME_BG, COLOR_HEADER, COLOR_HEADER_FG,
    COLOR_BTN, COLOR_BTN_FG, COLOR_MUTED, COLOR_SUCCESS, COLOR_WARN,
    COLOR_BORDER, COLOR_TEXT,
    FONT_TITLE, FONT_HEADER, FONT_NORMAL, FONT_SMALL,
    PAD, PAD_SMALL,
)

_WIN_W = 520
_WIN_H = 480


class StartupDialog(tk.Tk):
    """Initial window shown before the main app.

    After mainloop() returns:
    - ``result`` holds the chosen .aprx path (None if skipped)
    - ``basemap_result`` holds the chosen raster basemap path (None if skipped)
    - ``launched`` is True only when the user explicitly clicked Launch
    """

    def __init__(self, arcpy_available: bool = False) -> None:
        super().__init__()
        self._arcpy_available = arcpy_available
        self.result: Optional[str] = None
        self.basemap_result: Optional[str] = None
        self.launched: bool = False

        from config import APP_VERSION
        self.title(f"ArcGIS Pro Imagery Browser v{APP_VERSION}")
        self.resizable(False, False)
        self.configure(bg=COLOR_BG)

        # Dark defaults for plain tk widgets created without explicit colors
        # (this dialog runs before the main app applies its own defaults).
        from ui.styles import COLOR_ACCENT, COLOR_ENTRY_BG, COLOR_SELECT
        self.option_add("*Entry.background", COLOR_ENTRY_BG)
        self.option_add("*Entry.foreground", COLOR_TEXT)
        self.option_add("*Entry.insertBackground", COLOR_ACCENT)
        self.option_add("*Entry.selectBackground", COLOR_SELECT)
        self.option_add("*Entry.selectForeground", COLOR_TEXT)
        self.option_add("*Entry.relief", "flat")

        # Centre on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - _WIN_W) // 2
        y = (sh - _WIN_H) // 2
        self.geometry(f"{_WIN_W}x{_WIN_H}+{x}+{y}")

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- layout --

    def _build(self) -> None:
        self._build_header()
        self._build_body()
        self._build_footer()

    def _build_header(self) -> None:
        hdr = tk.Frame(self, bg=COLOR_HEADER, padx=PAD * 3, pady=PAD * 2)
        hdr.pack(fill=tk.X)

        from config import APP_VERSION
        tk.Label(
            hdr, text=f"ArcGIS Pro Imagery Browser  v{APP_VERSION}",
            bg=COLOR_HEADER, fg=COLOR_HEADER_FG,
            font=FONT_TITLE,
        ).pack(anchor=tk.W)

        tk.Label(
            hdr, text="Scan, filter, and transfer imagery from shared drives",
            bg=COLOR_HEADER, fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(anchor=tk.W)

    def _build_body(self) -> None:
        body = tk.Frame(self, bg=COLOR_BG, padx=PAD * 3, pady=PAD * 2)
        body.pack(fill=tk.BOTH, expand=True)
        self._build_project_section(body)
        self._build_basemap_section(body)

    def _build_project_section(self, body: tk.Frame) -> None:
        badge_frame = tk.Frame(body, bg=COLOR_BG)
        badge_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, PAD))

        if self._arcpy_available:
            tk.Label(
                badge_frame, text="● ArcGIS Pro detected",
                bg=COLOR_BG, fg=COLOR_SUCCESS, font=FONT_SMALL,
            ).pack(anchor=tk.W)
        else:
            tk.Label(
                badge_frame, text="● ArcGIS Pro not detected — canvas-only mode",
                bg=COLOR_BG, fg=COLOR_WARN, font=FONT_SMALL,
            ).pack(anchor=tk.W)
            tk.Label(
                badge_frame,
                text=(
                    "To enable map integration, run this script with ArcGIS Pro's Python:\n"
                    r"  …\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
                ),
                bg=COLOR_BG, fg=COLOR_MUTED, font=FONT_SMALL,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(2, 0))

        tk.Label(
            body,
            text="ArcGIS Pro Project (.aprx)  —  optional",
            bg=COLOR_BG, fg=COLOR_TEXT,
            font=FONT_HEADER,
        ).pack(anchor=tk.W)

        if self._arcpy_available:
            hint = "Footprints will be added to the project's active map."
        else:
            hint = "Project path is saved for when arcpy becomes available; no map updates in canvas-only mode."

        tk.Label(
            body, text=hint,
            bg=COLOR_BG, fg=COLOR_MUTED,
            font=FONT_SMALL,
            wraplength=_WIN_W - PAD * 8,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, PAD_SMALL))

        row = tk.Frame(body, bg=COLOR_BG)
        row.pack(fill=tk.X, pady=PAD_SMALL)

        self._path_var = tk.StringVar()
        entry = tk.Entry(
            row, textvariable=self._path_var,
            font=FONT_NORMAL,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        tk.Button(
            row, text="Browse…",
            bg=COLOR_BTN, fg=COLOR_BTN_FG,
            font=FONT_NORMAL, relief=tk.FLAT, padx=8,
            command=self._browse,
        ).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))

        self._path_error = tk.Label(
            body, text="", bg=COLOR_BG, fg=COLOR_WARN, font=FONT_SMALL,
        )
        self._path_error.pack(anchor=tk.W)

    def _build_basemap_section(self, body: tk.Frame) -> None:
        sep = tk.Frame(body, bg=COLOR_BORDER, height=1)
        sep.pack(fill=tk.X, pady=(PAD, PAD_SMALL))

        tk.Label(
            body,
            text="Basemap raster or KML/KMZ  —  optional",
            bg=COLOR_BG, fg=COLOR_TEXT,
            font=FONT_HEADER,
        ).pack(anchor=tk.W)

        tk.Label(
            body,
            text="Georeferenced raster or KML/KMZ drawn beneath imagery footprints. Accepts .tif/.tiff, .jp2, .img, .ecw, .sid, .vrt, .png, .kml, .kmz",
            bg=COLOR_BG, fg=COLOR_MUTED,
            font=FONT_SMALL,
            wraplength=_WIN_W - PAD * 8,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, PAD_SMALL))

        basemap_row = tk.Frame(body, bg=COLOR_BG)
        basemap_row.pack(fill=tk.X, pady=PAD_SMALL)

        self._basemap_var = tk.StringVar()
        tk.Entry(
            basemap_row, textvariable=self._basemap_var,
            font=FONT_NORMAL,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        tk.Button(
            basemap_row, text="Browse…",
            bg=COLOR_BTN, fg=COLOR_BTN_FG,
            font=FONT_NORMAL, relief=tk.FLAT, padx=8,
            command=self._browse_basemap,
        ).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))

        self._basemap_error = tk.Label(
            body, text="", bg=COLOR_BG, fg=COLOR_WARN, font=FONT_SMALL,
        )
        self._basemap_error.pack(anchor=tk.W)

    def _build_footer(self) -> None:
        sep = tk.Frame(self, bg=COLOR_BORDER, height=1)
        sep.pack(fill=tk.X)

        footer = tk.Frame(self, bg=COLOR_FRAME_BG, padx=PAD * 3, pady=PAD * 2)
        footer.pack(fill=tk.X)

        tk.Button(
            footer, text="Launch",
            bg=COLOR_SUCCESS, fg=COLOR_BTN_FG,
            font=FONT_HEADER, relief=tk.FLAT, padx=16, pady=6,
            command=self._launch,
        ).pack(side=tk.LEFT)

        tk.Button(
            footer, text="Launch without project",
            bg=COLOR_FRAME_BG, fg=COLOR_MUTED,
            font=FONT_SMALL, relief=tk.FLAT, padx=8,
            command=self._launch_without_project,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(PAD, 0))

    # -- actions --

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select ArcGIS Pro Project",
            filetypes=[("ArcGIS Pro Project", "*.aprx"), ("All files", "*.*")],
        )
        if path:
            self._path_var.set(path)
            self._path_error.config(text="")

    _BASEMAP_EXTENSIONS = {".tif", ".tiff", ".jp2", ".img", ".ecw", ".sid", ".vrt", ".png", ".kml", ".kmz"}

    def _browse_basemap(self) -> None:
        path = filedialog.askopenfilename(
            title="Select georeferenced basemap raster or KML/KMZ",
            filetypes=[
                ("Basemap files", "*.tif *.tiff *.jp2 *.img *.ecw *.sid *.vrt *.png *.kml *.kmz"),
                ("KML/KMZ", "*.kml *.kmz"),
                ("Raster files", "*.tif *.tiff *.jp2 *.img *.ecw *.sid *.vrt *.png"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._basemap_var.set(path)
            self._basemap_error.config(text="")

    _MAX_BASEMAP_BYTES = MAX_BASEMAP_BYTES

    def _validate_basemap(self) -> bool:
        """Validate the basemap field; populate self.basemap_result. Returns False on error."""
        raw = self._basemap_var.get().strip()
        if not raw:
            self.basemap_result = None
            return True
        raw_path = Path(raw)
        if raw_path.is_symlink():
            self._basemap_error.config(text="Symbolic links are not supported.")
            return False
        try:
            p = raw_path.resolve()
        except (OSError, RuntimeError):
            self._basemap_error.config(text="Invalid file path.")
            return False
        if p.suffix.lower() not in self._BASEMAP_EXTENSIONS:
            self._basemap_error.config(
                text=f"Unsupported file type '{p.suffix}'. Use .tif, .jp2, .img, .png, .kml, .kmz, etc."
            )
            return False
        try:
            stat = p.stat()
        except OSError:
            self._basemap_error.config(text="File not found. Check the path and try again.")
            return False
        if not p.is_file():
            self._basemap_error.config(text="Path is not a file.")
            return False
        if stat.st_size > self._MAX_BASEMAP_BYTES:
            self._basemap_error.config(text=f"File exceeds {MAX_BASEMAP_MB} MB limit.")
            return False
        self.basemap_result = str(p)
        return True

    def _launch(self) -> None:
        raw = self._path_var.get().strip()

        if raw:
            p = Path(raw)
            if p.suffix.lower() != ".aprx":
                self._path_error.config(text="File must have a .aprx extension.")
                return
            if not p.exists():
                self._path_error.config(text="File not found. Check the path and try again.")
                return
            self.result = str(p)
        else:
            self.result = None

        if not self._validate_basemap():
            return

        self.launched = True
        self.destroy()

    def _launch_without_project(self) -> None:
        if not self._validate_basemap():
            return
        self.result = None
        self.launched = True
        self.destroy()

    def _on_close(self) -> None:
        # User closed the window — treat as cancel, don't launch
        self.launched = False
        self.destroy()
