from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from airgapped_transfer import AirgappedTransfer
from footprint_manager import FootprintManager
from imagery_manager import ImageryManager
from models import ImageryScanResult
from scanner import scan_imagery_folder
from ui.filter_panel import FilterPanel
from ui.map_canvas import FootprintCanvas
from ui.imagery_panel import ImageryPanel
from ui.details_panel import DetailsPanel
from ui.styles import (
    COLOR_BG, COLOR_FRAME_BG, COLOR_HEADER, COLOR_HEADER_FG,
    COLOR_BTN, COLOR_BTN_FG, COLOR_MUTED, COLOR_WARN,
    FONT_TITLE, FONT_NORMAL, FONT_SMALL, PAD, PAD_SMALL,
    FILTER_WIDTH, PANEL_WIDTH,
    COLOR_SELECT, COLOR_BORDER,
    COLOR_ACCENT, COLOR_TEXT, COLOR_ENTRY_BG, COLOR_PANEL_2, COLOR_PANEL_3,
    COLOR_BTN_SUCCESS, COLOR_BTN_DANGER, COLOR_BTN_NEUTRAL,
    COLOR_BTN_NEUTRAL_FG, COLOR_BTN_SECONDARY,
)

log = logging.getLogger(__name__)


class ImageryBrowserApp(tk.Tk):
    def __init__(
        self,
        arcpy_available: bool = True,
        aprx_path: Optional[str] = None,
        basemap_path: Optional[str] = None,
    ):
        super().__init__()
        self._arcpy_available = arcpy_available
        self._basemap_path = basemap_path
        self._manager = ImageryManager()
        self._footprint_mgr = FootprintManager(aprx_path)
        self._scan_running = False
        self._stop_event: Optional[threading.Event] = None
        self._last_warnings: list[str] = []
        self._arcgis_query_pending: Optional[str] = None  # after() id for debounced query

        from config import APP_VERSION
        self.title(f"ArcGIS Pro Imagery Browser v{APP_VERSION}")
        self.geometry("1280x800")
        self.minsize(900, 600)
        self.configure(bg=COLOR_BG)
        self._apply_ttk_style()

        self._build_toolbar()
        self._build_main_panes()
        self._build_statusbar()

        if not arcpy_available:
            self._set_status(
                "arcpy not detected — running in canvas-only mode (no Pro map updates)",
                color=COLOR_WARN,
            )

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- ttk style --

    def _apply_ttk_style(self) -> None:
        """Apply Segoe UI consistently to all ttk widgets so they match tk widgets."""
        style = ttk.Style(self)
        style.theme_use("clam")

        # Base font for all ttk widgets
        font_normal = FONT_NORMAL  # ("Segoe UI", 9)
        font_small = FONT_SMALL    # ("Segoe UI", 8)

        # Treeview — rows, headings, and selected state
        style.configure("Treeview",
                        font=font_normal,
                        background=COLOR_FRAME_BG,
                        fieldbackground=COLOR_FRAME_BG,
                        foreground=COLOR_TEXT,
                        bordercolor=COLOR_BORDER,
                        rowheight=22,
                        borderwidth=0)
        style.configure("Treeview.Heading",
                        font=font_small,
                        background=COLOR_PANEL_2,
                        foreground=COLOR_MUTED,
                        bordercolor=COLOR_BORDER,
                        relief="flat")
        style.map("Treeview",
                  background=[("selected", COLOR_SELECT)],
                  foreground=[("selected", COLOR_ACCENT)])
        style.map("Treeview.Heading",
                  background=[("active", COLOR_PANEL_3)])

        # Combobox
        style.configure("TCombobox",
                        font=font_normal,
                        fieldbackground=COLOR_ENTRY_BG,
                        background=COLOR_PANEL_2,
                        foreground=COLOR_TEXT,
                        bordercolor=COLOR_BORDER,
                        arrowcolor=COLOR_MUTED,
                        selectbackground=COLOR_SELECT,
                        selectforeground=COLOR_TEXT,
                        arrowsize=14)
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLOR_ENTRY_BG)],
                  foreground=[("readonly", COLOR_TEXT)])
        self.option_add("*TCombobox*Listbox.font", font_normal)
        self.option_add("*TCombobox*Listbox.background", COLOR_ENTRY_BG)
        self.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", COLOR_SELECT)
        self.option_add("*TCombobox*Listbox.selectForeground", COLOR_ACCENT)

        # Scrollbar
        style.configure("TScrollbar",
                        background=COLOR_PANEL_2,
                        troughcolor=COLOR_BG,
                        arrowcolor=COLOR_MUTED,
                        bordercolor=COLOR_BG,
                        arrowsize=13)
        style.map("TScrollbar", background=[("active", COLOR_PANEL_3)])

        # Progressbar
        style.configure("TProgressbar",
                        background=COLOR_ACCENT,
                        troughcolor=COLOR_PANEL_2)

        # Option-database defaults for plain tk widgets (Entry/Checkbutton/
        # Scale/Label/Button) so panels stay dark without per-widget styling.
        # Explicit widget options always override these.
        self.option_add("*Entry.background", COLOR_ENTRY_BG)
        self.option_add("*Entry.foreground", COLOR_TEXT)
        self.option_add("*Entry.insertBackground", COLOR_ACCENT)
        self.option_add("*Entry.selectBackground", COLOR_SELECT)
        self.option_add("*Entry.selectForeground", COLOR_TEXT)
        self.option_add("*Entry.relief", "flat")
        self.option_add("*Checkbutton.foreground", COLOR_TEXT)
        self.option_add("*Checkbutton.activeForeground", COLOR_TEXT)
        self.option_add("*Checkbutton.selectColor", COLOR_ENTRY_BG)
        self.option_add("*Scale.foreground", COLOR_TEXT)
        self.option_add("*Scale.troughColor", COLOR_ENTRY_BG)
        self.option_add("*Label.foreground", COLOR_TEXT)
        self.option_add("*Button.background", COLOR_PANEL_3)
        self.option_add("*Button.foreground", COLOR_TEXT)
        self.option_add("*Button.activeBackground", COLOR_SELECT)
        self.option_add("*Button.activeForeground", COLOR_ACCENT)
        self.option_add("*Listbox.background", COLOR_ENTRY_BG)
        self.option_add("*Listbox.foreground", COLOR_TEXT)

    # -- toolbar --

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self, bg=COLOR_HEADER, padx=PAD, pady=PAD_SMALL)
        bar.pack(fill=tk.X)

        from config import APP_VERSION
        title_box = tk.Frame(bar, bg=COLOR_HEADER)
        title_box.pack(side=tk.LEFT, padx=(0, PAD))
        tk.Label(title_box, text="IMAGERY BROWSER", bg=COLOR_HEADER,
                 fg=COLOR_ACCENT, font=FONT_TITLE).pack(side=tk.LEFT)
        tk.Label(title_box, text=f" v{APP_VERSION}", bg=COLOR_HEADER,
                 fg=COLOR_MUTED, font=FONT_SMALL).pack(side=tk.LEFT, anchor=tk.S,
                                                       pady=(0, 3))

        tk.Button(bar, text="Browse…", bg=COLOR_BTN, fg=COLOR_BTN_FG,
                  font=FONT_NORMAL, relief=tk.FLAT, padx=8,
                  activebackground=COLOR_PANEL_3, activeforeground=COLOR_ACCENT,
                  command=self._browse_folder).pack(side=tk.LEFT)

        self._path_var = tk.StringVar()
        path_entry = tk.Entry(bar, textvariable=self._path_var, font=FONT_NORMAL,
                              width=55, bg=COLOR_ENTRY_BG, fg=COLOR_TEXT,
                              insertbackground=COLOR_ACCENT, relief=tk.FLAT,
                              highlightthickness=1, highlightbackground=COLOR_BORDER,
                              highlightcolor=COLOR_ACCENT)
        path_entry.pack(side=tk.LEFT, padx=PAD_SMALL)

        self._recursive_var = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="Recursive", variable=self._recursive_var,
                       bg=COLOR_HEADER, fg=COLOR_HEADER_FG, font=FONT_SMALL,
                       selectcolor=COLOR_HEADER, activebackground=COLOR_HEADER,
                       activeforeground=COLOR_HEADER_FG).pack(side=tk.LEFT, padx=PAD_SMALL)

        self._btn_scan = tk.Button(bar, text="Scan", bg=COLOR_BTN_SUCCESS,
                                   fg=COLOR_BTN_FG,
                                   font=FONT_NORMAL, relief=tk.FLAT, padx=10,
                                   command=self._start_scan)
        self._btn_scan.pack(side=tk.LEFT, padx=PAD_SMALL)

        self._btn_cancel = tk.Button(bar, text="Cancel", bg=COLOR_BTN_DANGER,
                                     fg=COLOR_BTN_FG,
                                     font=FONT_NORMAL, relief=tk.FLAT, padx=8,
                                     command=self._cancel_scan)
        self._btn_cancel.pack(side=tk.LEFT, padx=(0, PAD_SMALL))
        self._btn_cancel.pack_forget()

        self._btn_clear = tk.Button(bar, text="Clear", bg=COLOR_BTN_NEUTRAL,
                                    fg=COLOR_BTN_NEUTRAL_FG,
                                    font=FONT_NORMAL, relief=tk.FLAT, padx=8,
                                    command=self._clear_all)
        self._btn_clear.pack(side=tk.LEFT)

        tk.Button(bar, text="Transfer…", bg=COLOR_BTN_SECONDARY, fg=COLOR_BTN_FG,
                  font=FONT_NORMAL, relief=tk.FLAT, padx=8,
                  command=self._transfer).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))

    # -- main panes --

    def _build_main_panes(self) -> None:
        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=COLOR_BG,
                              sashwidth=5, sashrelief=tk.RAISED)
        pane.pack(fill=tk.BOTH, expand=True)

        self._filter_panel = FilterPanel(
            pane,
            on_change=self._apply_filters,
            on_navigate=lambda lat, lon: self._canvas.navigate_to(lat, lon),
            width=FILTER_WIDTH,
        )
        pane.add(self._filter_panel, minsize=200, width=FILTER_WIDTH, sticky=tk.NSEW)

        self._canvas = FootprintCanvas(pane, basemap_path=self._basemap_path, width=400)
        pane.add(self._canvas, minsize=300, sticky=tk.NSEW)

        # Right column: imagery list on top, metadata inspector below.
        right = tk.PanedWindow(pane, orient=tk.VERTICAL, bg=COLOR_BG,
                               sashwidth=5, sashrelief=tk.RAISED)
        self._imagery_panel = ImageryPanel(
            right,
            on_selection_change=self._on_selection_change,
            on_open_record=self._open_image_viewer,
            on_zoom_to_record=self._zoom_to_record,
        )
        right.add(self._imagery_panel, minsize=200, stretch="always", sticky=tk.NSEW)

        self._details_panel = DetailsPanel(right)
        right.add(self._details_panel, minsize=150, stretch="never", sticky=tk.NSEW)

        pane.add(right, minsize=260, width=PANEL_WIDTH, sticky=tk.NSEW)

    # -- statusbar --

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=COLOR_BG, relief=tk.SUNKEN, bd=1)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_var = tk.StringVar(value="Ready. Browse to a shared drive folder and click Scan.")
        self._status_label = tk.Label(bar, textvariable=self._status_var,
                                      bg=COLOR_BG, fg=COLOR_MUTED,
                                      font=FONT_SMALL, anchor=tk.W, padx=PAD)
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._btn_warnings = tk.Button(
            bar, text="View warnings",
            bg=COLOR_BG, fg=COLOR_WARN,
            font=FONT_SMALL, relief=tk.FLAT, padx=6,
            command=self._show_warnings_dialog,
        )
        self._btn_warnings.pack(side=tk.RIGHT, padx=PAD)
        self._btn_warnings.pack_forget()

        self._progress = ttk.Progressbar(bar, mode="indeterminate", length=150)
        self._progress.pack(side=tk.RIGHT, padx=PAD, pady=1)
        self._progress.pack_forget()  # hidden initially

    # -- scan --

    def _browse_folder(self) -> None:
        path = filedialog.askdirectory(title="Select imagery folder on shared drive")
        if path:
            self._path_var.set(path)

    def _start_scan(self) -> None:
        folder = self._path_var.get().strip()
        if not folder:
            messagebox.showwarning("No Folder", "Please enter or browse to a folder path.")
            return
        if self._scan_running:
            return

        self._scan_running = True
        self._stop_event = threading.Event()
        self._btn_scan.config(state=tk.DISABLED)
        self._btn_cancel.pack(side=tk.LEFT, padx=(0, PAD_SMALL))
        self._set_status("Scanning… please wait.")
        self._progress.pack(side=tk.RIGHT, padx=PAD, pady=1)
        self._progress.start(10)

        recursive = self._recursive_var.get()
        threading.Thread(
            target=self._scan_worker,
            args=(folder, recursive, self._stop_event),
            daemon=True,
        ).start()

    def _cancel_scan(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        self._btn_cancel.config(state=tk.DISABLED)

    def _scan_worker(self, folder: str, recursive: bool, stop_event: threading.Event) -> None:
        try:
            result = scan_imagery_folder(folder, recursive=recursive, stop_event=stop_event)
        except Exception as exc:
            result = ImageryScanResult(warnings=[f"Unexpected error: {exc}"])

        def _apply_safely() -> None:
            try:
                self._apply_scan_result(result)
            except Exception as exc:
                log.error("Failed to apply scan result: %s", exc)
                self._scan_running = False
                self._btn_scan.config(state=tk.NORMAL)
                self._progress.stop()
                self._progress.pack_forget()
                self._set_status(f"Unexpected display error: {exc}", color=COLOR_WARN)

        self.after(0, _apply_safely)

    def _apply_scan_result(self, result: ImageryScanResult) -> None:
        self._scan_running = False
        self._stop_event = None
        self._btn_scan.config(state=tk.NORMAL)
        self._btn_cancel.pack_forget()
        self._btn_cancel.config(state=tk.NORMAL)
        self._progress.stop()
        self._progress.pack_forget()

        self._manager.load(result.records)

        self._filter_panel.set_sensor_platforms(self._manager.all_sensor_platforms())
        self._filter_panel.set_image_types(self._manager.all_image_types())
        self._filter_panel.set_image_categories(self._manager.all_image_categories())
        self._filter_panel.set_max_size(self._manager.max_file_size_mb())

        self._apply_filters()

        self._last_warnings = list(result.warnings)
        if self._last_warnings:
            self._btn_warnings.pack(side=tk.RIGHT, padx=PAD)
        else:
            self._btn_warnings.pack_forget()

        if result.cancelled:
            self._set_status(
                f"Scan cancelled — {result.processed_count} file(s) loaded.",
                color=COLOR_WARN,
            )
        elif result.warnings:
            warn_text = "; ".join(result.warnings[:3])
            if len(result.warnings) > 3:
                warn_text += f" (+{len(result.warnings) - 3} more)"
            self._set_status(
                f"Scan complete: {result.processed_count} files, "
                f"{result.failed_count} skipped. Warnings: {warn_text}",
                color=COLOR_WARN,
            )
        else:
            self._set_status(
                f"Scan complete: {result.processed_count} imagery file(s) found."
            )

        if self._arcpy_available and result.records:
            self._footprint_mgr.clear_footprints()
            ok = self._footprint_mgr.add_records_to_map(result.records)
            if not ok:
                self._set_status(
                    "Footprints could not be added to ArcGIS Pro map "
                    "(no active map or no valid extents).",
                    color=COLOR_WARN,
                )

    # -- filtering --

    def _apply_filters(self) -> None:
        filters = self._filter_panel.get_filters()
        records = self._manager.search(filters)
        records = self._manager.sort_records(
            records, filters.get("sort_key", "scene_name"), filters.get("sort_reverse", False)
        )
        self._imagery_panel.refresh(records)
        self._canvas.draw_footprints(records)
        if self._arcpy_available:
            visible_ids = [r.id for r in records]
            self._schedule_arcgis_query(visible_ids)

    def _schedule_arcgis_query(self, visible_ids: list[str]) -> None:
        """Debounce ArcGIS Pro definition-query updates (300 ms) so rapid filter
        changes don't each block the main thread with an arcpy call."""
        if self._arcgis_query_pending is not None:
            try:
                self.after_cancel(self._arcgis_query_pending)
            except tk.TclError:
                pass
        self._arcgis_query_pending = self.after(
            300, lambda ids=visible_ids: self._run_arcgis_query(ids)
        )

    def _run_arcgis_query(self, visible_ids: list[str]) -> None:
        self._arcgis_query_pending = None
        self._footprint_mgr.update_filter_query(visible_ids)

    # -- selection --

    def _on_selection_change(self, selected_ids: set[str]) -> None:
        self._canvas.highlight_selected(selected_ids)
        records = self._imagery_panel.selected_records()
        self._details_panel.show(records[-1] if records else None)
        if self._arcpy_available:
            # Don't change definition query on select — just highlight in canvas
            pass

    def _zoom_to_record(self, record) -> None:
        """Centre the map canvas on a record's footprint, zoomed to fit it."""
        cx = (record.extent_minx + record.extent_maxx) / 2.0
        cy = (record.extent_miny + record.extent_maxy) / 2.0
        span = max(
            record.extent_maxx - record.extent_minx,
            record.extent_maxy - record.extent_miny,
        )
        # Frame the footprint with ~50% margin; clamp to sane zoom levels.
        zoom = min(max(span * 1.5, 0.05), 60.0)
        self._canvas.navigate_to(cy, cx, zoom_deg=zoom)

    def _open_image_viewer(self, record) -> None:
        """Open a record in the image viewer to draw/export clips and snapshots."""
        from ui.image_viewer import ImageViewerWindow

        if not Path(record.filepath).is_file():
            messagebox.showwarning(
                "File not found",
                f"The source file is not accessible:\n{record.filepath}",
            )
            return
        try:
            ImageViewerWindow(self, record)
        except Exception as exc:  # noqa: BLE001 - never let the viewer crash the app
            log.exception("Failed to open image viewer")
            messagebox.showerror("Image Viewer", f"Could not open the image:\n{exc}")

    # -- clear --

    def _clear_all(self) -> None:
        self._manager.load([])
        self._imagery_panel.refresh([])
        self._details_panel.show(None)
        self._canvas.draw_footprints([])
        if self._arcpy_available:
            self._footprint_mgr.clear_footprints()
        self._set_status("Cleared.")

    # -- airgapped transfer --

    def _transfer(self) -> None:
        records = self._imagery_panel.selected_records()
        if not records:
            # Fall back to all currently-filtered records
            records = self._manager.search(self._filter_panel.get_filters())
        if not records:
            messagebox.showwarning("Nothing to Transfer",
                                   "No records are loaded. Run a scan first.")
            return

        dest = filedialog.askdirectory(title="Select transfer destination (USB drive, etc.)")
        if not dest:
            return

        self._set_status(f"Packaging {len(records)} record(s)…")
        self.update_idletasks()

        try:
            result = AirgappedTransfer().package(records, dest)
        except Exception as exc:
            log.error("Airgapped transfer failed: %s", exc)
            messagebox.showerror("Transfer Failed", str(exc))
            self._set_status("Transfer failed.", color=COLOR_WARN)
            return

        if result.failed_count:
            messagebox.showwarning("Transfer Complete with Errors", result.summary())
            self._set_status(
                f"Transfer: {result.success_count} copied, {result.failed_count} failed.",
                color=COLOR_WARN,
            )
        else:
            messagebox.showinfo("Transfer Complete", result.summary())
            self._set_status(
                f"Transfer complete: {result.success_count} file(s) packaged."
            )

    # -- helpers --

    def _show_warnings_dialog(self) -> None:
        if not self._last_warnings:
            return
        dlg = tk.Toplevel(self)
        dlg.title(f"Scan Warnings ({len(self._last_warnings)})")
        dlg.geometry("600x400")
        dlg.transient(self)

        from tkinter import scrolledtext
        from ui.styles import FONT_MONO
        txt = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, font=FONT_MONO, state=tk.NORMAL)
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        txt.insert(tk.END, "\n".join(self._last_warnings))
        txt.config(state=tk.DISABLED)

        tk.Button(dlg, text="Close", command=dlg.destroy,
                  relief=tk.FLAT, padx=12, pady=4).pack(pady=(0, 8))

    def _set_status(self, msg: str, color: str = "#666666") -> None:
        self._status_var.set(msg)
        self._status_label.config(fg=color)

    def _on_close(self) -> None:
        if self._arcpy_available:
            try:
                self._footprint_mgr.clear_footprints()
            except Exception as exc:
                log.warning("Error clearing footprints during shutdown: %s", exc)
        self.destroy()
