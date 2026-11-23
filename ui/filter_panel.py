from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Callable, Optional

log = logging.getLogger(__name__)

from config import DATE_RANGE_OPTIONS, SORT_KEYS, SORT_LABELS
from ui import wheel
from ui.styles import (
    COLOR_BG, COLOR_FRAME_BG, COLOR_HEADER, COLOR_HEADER_FG, COLOR_BORDER,
    COLOR_BTN, COLOR_BTN_FG, COLOR_TEXT, COLOR_MUTED, COLOR_SECTION_BG,
    COLOR_ERROR, COLOR_BTN_NEUTRAL, COLOR_BTN_NEUTRAL_FG,
    ICAT_COLORS, ICAT_LABELS,
    FONT_HEADER, FONT_NORMAL, FONT_SMALL, PAD, PAD_SMALL,
)

_DEFAULT_CATEGORY_COLOR = "#7f8c8d"

# Human-readable label → internal sort key
_SORT_KEY_MAP = dict(zip(SORT_LABELS, SORT_KEYS))


class FilterPanel(tk.Frame):
    """Left sidebar: MGRS navigator, sort, date, sensor, image type, scene search, size."""

    def __init__(
        self,
        master,
        on_change: Callable[[], None],
        on_navigate: Optional[Callable[[float, float], None]] = None,
        **kwargs,
    ):
        kwargs.setdefault("bg", COLOR_FRAME_BG)
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._on_navigate = on_navigate
        self._sensors: list[str] = []
        self._sensor_vars: dict[str, tk.BooleanVar] = {}
        self._image_types: list[str] = []
        self._image_type_vars: dict[str, tk.BooleanVar] = {}
        self._image_categories: list[str] = []
        self._image_category_vars: dict[str, tk.BooleanVar] = {}
        self._max_size_mb: float = 0.0
        self._debounce_id: Optional[str] = None
        self._build()

    # -- public --

    def set_sensor_platforms(self, sensors: list[str]) -> None:
        self._sensors = list(sensors)
        self._build_sensor_checks()

    def set_image_types(self, image_types: list[str]) -> None:
        self._image_types = list(image_types)
        self._build_image_type_checks()

    def set_image_categories(self, categories: list[str]) -> None:
        self._image_categories = list(categories)
        self._build_category_checks()

    def set_max_size(self, max_mb: float) -> None:
        self._max_size_mb = max_mb
        self._size_scale.config(to=max(max_mb, 1.0))
        self._size_var.set(0.0)

    def get_filters(self) -> dict:
        filters: dict = {}

        # Sort
        label = self._sort_key_var.get()
        filters["sort_key"] = _SORT_KEY_MAP.get(label, "scene_name")
        filters["sort_reverse"] = self._sort_dir_var.get() == "desc"

        # Dates
        filters["date_range"] = self._date_range_var.get()
        filters["date_field"] = self._date_field_var.get()
        if filters["date_range"] == "Custom Range":
            filters["date_start"] = self._parse_date(self._date_start_entry.get())
            filters["date_end"] = self._parse_date(self._date_end_entry.get())

        # Sensors
        selected_sensors = [s for s, var in self._sensor_vars.items() if var.get()]
        if selected_sensors and len(selected_sensors) < len(self._sensors):
            filters["sensors"] = selected_sensors

        # Image types
        selected_types = [t for t, var in self._image_type_vars.items() if var.get()]
        if selected_types and len(selected_types) < len(self._image_types):
            filters["image_types"] = selected_types

        # Image categories (NITF ICAT)
        selected_cats = [c for c, var in self._image_category_vars.items() if var.get()]
        if selected_cats and len(selected_cats) < len(self._image_categories):
            filters["categories"] = selected_cats

        # Scene search
        filters["scene_search"] = self._scene_search_var.get().strip()

        # Size
        filters["min_size_mb"] = self._size_var.get()

        return filters

    # -- build --

    def _build(self) -> None:
        hdr = tk.Frame(self, bg=COLOR_HEADER, padx=PAD, pady=PAD_SMALL)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Filters & Sorting", bg=COLOR_HEADER,
                 fg=COLOR_HEADER_FG, font=FONT_HEADER).pack(side=tk.LEFT)

        scroll_frame = _ScrollableFrame(self)
        scroll_frame.pack(fill=tk.BOTH, expand=True)
        inner = scroll_frame.inner

        self._build_mgrs_section(inner)
        self._build_sort_section(inner)
        self._build_date_section(inner)
        self._sensor_section_frame = self._build_section(inner, "Sensor / Platform")
        self._image_type_section_frame = self._build_section(inner, "Image Type")
        self._category_section_frame = self._build_section(inner, "Image Category (NITF)")
        self._build_scene_search_section(inner)
        self._build_size_section(inner)

        btn_frame = tk.Frame(self, bg=COLOR_FRAME_BG, pady=PAD)
        btn_frame.pack(fill=tk.X, padx=PAD)
        tk.Button(btn_frame, text="Reset All Filters",
                  bg=COLOR_BTN_NEUTRAL, fg=COLOR_BTN_NEUTRAL_FG, font=FONT_SMALL,
                  relief=tk.FLAT, command=self._reset).pack(fill=tk.X)

    def _build_section(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=COLOR_FRAME_BG, pady=PAD_SMALL)
        outer.pack(fill=tk.X, padx=PAD)
        tk.Label(outer, text=title.upper(), bg=COLOR_FRAME_BG,
                 fg=COLOR_MUTED, font=FONT_SMALL).pack(anchor=tk.W)
        inner = tk.Frame(outer, bg=COLOR_SECTION_BG, relief=tk.FLAT,
                         highlightbackground=COLOR_BORDER, highlightthickness=1)
        inner.pack(fill=tk.X)
        return inner

    def _build_mgrs_section(self, parent) -> None:
        frame = self._build_section(parent, "MGRS Navigator")
        p = PAD_SMALL

        tk.Label(
            frame,
            text="Enter MGRS coordinate to jump to location\n(e.g. 18TWL91002350)",
            bg=COLOR_SECTION_BG, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=180, justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=p, pady=(p, 0))

        row = tk.Frame(frame, bg=COLOR_SECTION_BG)
        row.pack(fill=tk.X, padx=p, pady=p)

        self._mgrs_var = tk.StringVar()
        mgrs_entry = tk.Entry(row, textvariable=self._mgrs_var, font=FONT_SMALL)
        mgrs_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        mgrs_entry.bind("<Return>", lambda _e: self._navigate_mgrs())

        tk.Button(
            row, text="Go",
            bg=COLOR_BTN, fg=COLOR_BTN_FG,
            font=FONT_SMALL, relief=tk.FLAT, padx=6,
            command=self._navigate_mgrs,
        ).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))

        self._mgrs_error = tk.Label(
            frame, text="", bg=COLOR_SECTION_BG, fg=COLOR_ERROR, font=FONT_SMALL,
            wraplength=180, justify=tk.LEFT,
        )
        self._mgrs_error.pack(anchor=tk.W, padx=p)

    def _build_sort_section(self, parent) -> None:
        frame = self._build_section(parent, "Sort")
        p = PAD_SMALL

        key_row = tk.Frame(frame, bg=COLOR_SECTION_BG)
        key_row.pack(fill=tk.X, padx=p, pady=(p, 0))
        tk.Label(key_row, text="By:", bg=COLOR_SECTION_BG, font=FONT_SMALL).pack(side=tk.LEFT)

        self._sort_key_var = tk.StringVar(value=SORT_LABELS[0])
        sort_cb = ttk.Combobox(
            key_row, textvariable=self._sort_key_var,
            values=SORT_LABELS, state="readonly",
            font=FONT_SMALL, width=14,
        )
        sort_cb.pack(side=tk.LEFT, padx=(PAD_SMALL, 0), fill=tk.X, expand=True)
        self._sort_key_var.trace_add("write", lambda *_: self._on_change())

        dir_row = tk.Frame(frame, bg=COLOR_SECTION_BG)
        dir_row.pack(fill=tk.X, padx=p, pady=(0, p))
        self._sort_dir_var = tk.StringVar(value="asc")
        for text, val in (("Ascending", "asc"), ("Descending", "desc")):
            tk.Radiobutton(
                dir_row, text=text, variable=self._sort_dir_var, value=val,
                bg=COLOR_SECTION_BG, font=FONT_SMALL, command=self._on_change,
            ).pack(side=tk.LEFT, padx=(0, PAD_SMALL))

    def _build_date_section(self, parent) -> None:
        frame = self._build_section(parent, "Date")
        p = PAD_SMALL

        self._date_field_var = tk.StringVar(value="acquisition")
        field_row = tk.Frame(frame, bg=COLOR_SECTION_BG)
        field_row.pack(fill=tk.X, padx=p, pady=p)
        tk.Label(field_row, text="Use:", bg=COLOR_SECTION_BG, font=FONT_SMALL).pack(side=tk.LEFT)
        for text, val in (("Capture", "acquisition"), ("Ingest", "ingest")):
            tk.Radiobutton(field_row, text=text, variable=self._date_field_var,
                           value=val, bg=COLOR_SECTION_BG, font=FONT_SMALL,
                           command=self._on_change).pack(side=tk.LEFT, padx=2)

        self._date_range_var = tk.StringVar(value="Any Date")
        self._date_range_var.trace_add("write", lambda *_: self._on_date_range_change())
        ttk.Combobox(frame, textvariable=self._date_range_var,
                     values=DATE_RANGE_OPTIONS, state="readonly",
                     font=FONT_NORMAL).pack(fill=tk.X, padx=p, pady=p)

        self._date_custom_frame = tk.Frame(frame, bg=COLOR_SECTION_BG)
        for label, attr in (("From (YYYY-MM-DD):", "_date_start_entry"),
                             ("To   (YYYY-MM-DD):", "_date_end_entry")):
            row = tk.Frame(self._date_custom_frame, bg=COLOR_SECTION_BG)
            row.pack(fill=tk.X, padx=p, pady=1)
            tk.Label(row, text=label, bg=COLOR_SECTION_BG, font=FONT_SMALL).pack(anchor=tk.W)
            entry = tk.Entry(row, font=FONT_SMALL)
            entry.pack(fill=tk.X)
            setattr(self, attr, entry)
            entry.bind("<KeyRelease>", lambda _e: self._on_change_debounced())
        self._date_parse_error = tk.Label(
            self._date_custom_frame, text="", bg=COLOR_SECTION_BG,
            fg=COLOR_ERROR, font=FONT_SMALL, wraplength=180, justify=tk.LEFT,
        )
        self._date_parse_error.pack(anchor=tk.W, padx=p)

    def _build_sensor_checks(self) -> None:
        for w in self._sensor_section_frame.winfo_children():
            w.destroy()
        self._sensor_vars.clear()
        p = PAD_SMALL
        ctrl = tk.Frame(self._sensor_section_frame, bg=COLOR_SECTION_BG)
        ctrl.pack(fill=tk.X, padx=p, pady=p)
        tk.Button(ctrl, text="All",  font=FONT_SMALL, relief=tk.FLAT,
                  command=self._select_all_sensors).pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="None", font=FONT_SMALL, relief=tk.FLAT,
                  command=self._clear_sensors).pack(side=tk.LEFT)
        for sensor in self._sensors:
            var = tk.BooleanVar(value=True)
            var.trace_add("write", lambda *_: self._on_change_debounced())
            self._sensor_vars[sensor] = var
            tk.Checkbutton(self._sensor_section_frame, text=sensor,
                           variable=var, bg=COLOR_SECTION_BG, font=FONT_NORMAL,
                           anchor=tk.W).pack(fill=tk.X, padx=p)

    def _build_image_type_checks(self) -> None:
        for w in self._image_type_section_frame.winfo_children():
            w.destroy()
        self._image_type_vars.clear()
        p = PAD_SMALL
        ctrl = tk.Frame(self._image_type_section_frame, bg=COLOR_SECTION_BG)
        ctrl.pack(fill=tk.X, padx=p, pady=p)
        tk.Button(ctrl, text="All",  font=FONT_SMALL, relief=tk.FLAT,
                  command=self._select_all_image_types).pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="None", font=FONT_SMALL, relief=tk.FLAT,
                  command=self._clear_image_types).pack(side=tk.LEFT)
        for img_type in self._image_types:
            var = tk.BooleanVar(value=True)
            var.trace_add("write", lambda *_: self._on_change_debounced())
            self._image_type_vars[img_type] = var
            tk.Checkbutton(self._image_type_section_frame, text=img_type,
                           variable=var, bg=COLOR_SECTION_BG, font=FONT_NORMAL,
                           anchor=tk.W).pack(fill=tk.X, padx=p)

    def _build_category_checks(self) -> None:
        for w in self._category_section_frame.winfo_children():
            w.destroy()
        self._image_category_vars.clear()
        p = PAD_SMALL
        if not self._image_categories:
            tk.Label(self._category_section_frame, text="No NITF categories in results",
                     bg=COLOR_SECTION_BG, fg=COLOR_MUTED, font=FONT_SMALL,
                     anchor=tk.W).pack(fill=tk.X, padx=p, pady=p)
            return
        ctrl = tk.Frame(self._category_section_frame, bg=COLOR_SECTION_BG)
        ctrl.pack(fill=tk.X, padx=p, pady=p)
        tk.Button(ctrl, text="All", font=FONT_SMALL, relief=tk.FLAT,
                  command=self._select_all_categories).pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="None", font=FONT_SMALL, relief=tk.FLAT,
                  command=self._clear_categories).pack(side=tk.LEFT)
        # Each row carries a color swatch — this doubles as the footprint legend.
        for cat in self._image_categories:
            var = tk.BooleanVar(value=True)
            var.trace_add("write", lambda *_: self._on_change_debounced())
            self._image_category_vars[cat] = var
            row = tk.Frame(self._category_section_frame, bg=COLOR_SECTION_BG)
            row.pack(fill=tk.X, padx=p)
            swatch = tk.Frame(row, bg=ICAT_COLORS.get(cat, _DEFAULT_CATEGORY_COLOR),
                              width=12, height=12, highlightbackground=COLOR_BORDER,
                              highlightthickness=1)
            swatch.pack(side=tk.LEFT, padx=(0, 4))
            swatch.pack_propagate(False)
            label = ICAT_LABELS.get(cat)
            text = f"{cat} — {label}" if label else cat
            tk.Checkbutton(row, text=text, variable=var, bg=COLOR_SECTION_BG,
                           font=FONT_SMALL, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_scene_search_section(self, parent) -> None:
        frame = self._build_section(parent, "Scene Name")
        p = PAD_SMALL
        self._scene_search_var = tk.StringVar()
        entry = tk.Entry(frame, textvariable=self._scene_search_var, font=FONT_SMALL)
        entry.pack(fill=tk.X, padx=p, pady=(p, 0))
        entry.bind("<KeyRelease>", lambda _e: self._on_change_debounced())
        tk.Label(frame, text="Filter by partial scene name",
                 bg=COLOR_SECTION_BG, fg=COLOR_MUTED, font=FONT_SMALL,
                 ).pack(anchor=tk.W, padx=p, pady=(1, p))

    def _build_size_section(self, parent) -> None:
        frame = self._build_section(parent, "Minimum File Size")
        p = PAD_SMALL
        self._size_var = tk.DoubleVar(value=0.0)
        self._size_label = tk.Label(frame, text="0 MB", bg=COLOR_SECTION_BG, font=FONT_SMALL)
        self._size_label.pack(anchor=tk.E, padx=p)
        self._size_scale = tk.Scale(
            frame, variable=self._size_var, from_=0, to=1,
            orient=tk.HORIZONTAL, resolution=0.1,
            bg=COLOR_SECTION_BG, highlightthickness=0,
            command=self._on_size_change,
            showvalue=False,
        )
        self._size_scale.pack(fill=tk.X, padx=p, pady=p)

    # -- event handlers --

    def _on_change_debounced(self) -> None:
        if self._debounce_id is not None:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(400, self._fire_change)

    def _fire_change(self) -> None:
        self._debounce_id = None
        if self._date_range_var.get() == "Custom Range":
            self._check_date_entries()
        self._on_change()

    def _check_date_entries(self) -> None:
        for entry in (self._date_start_entry, self._date_end_entry):
            if entry.get().strip() and self._parse_date(entry.get()) is None:
                self._date_parse_error.config(
                    text="Use YYYY-MM-DD, YYYY/MM/DD, or DD-MM-YYYY"
                )
                return
        self._date_parse_error.config(text="")

    def _navigate_mgrs(self) -> None:
        from ui.mgrs import mgrs_to_latlon
        raw = self._mgrs_var.get().strip()
        if not raw:
            return
        try:
            lat, lon = mgrs_to_latlon(raw)
            self._mgrs_error.config(text="")
            if self._on_navigate:
                self._on_navigate(lat, lon)
        except Exception as exc:
            self._mgrs_error.config(text=str(exc))

    def _on_date_range_change(self) -> None:
        if self._date_range_var.get() == "Custom Range":
            self._date_custom_frame.pack(fill=tk.X)
        else:
            self._date_custom_frame.pack_forget()
        self._on_change()

    def _on_size_change(self, value) -> None:
        self._size_label.config(text=f"{float(value):.1f} MB")
        self._on_change_debounced()

    def _select_all_sensors(self) -> None:
        for var in self._sensor_vars.values():
            var.set(True)

    def _clear_sensors(self) -> None:
        for var in self._sensor_vars.values():
            var.set(False)

    def _select_all_image_types(self) -> None:
        for var in self._image_type_vars.values():
            var.set(True)

    def _clear_image_types(self) -> None:
        for var in self._image_type_vars.values():
            var.set(False)

    def _select_all_categories(self) -> None:
        for var in self._image_category_vars.values():
            var.set(True)

    def _clear_categories(self) -> None:
        for var in self._image_category_vars.values():
            var.set(False)

    def _reset(self) -> None:
        self._mgrs_var.set("")
        self._mgrs_error.config(text="")
        self._sort_key_var.set(SORT_LABELS[0])
        self._sort_dir_var.set("asc")
        self._date_range_var.set("Any Date")
        self._date_field_var.set("acquisition")
        self._date_start_entry.delete(0, tk.END)
        self._date_end_entry.delete(0, tk.END)
        self._date_parse_error.config(text="")
        self._scene_search_var.set("")
        self._size_var.set(0.0)
        self._select_all_sensors()
        self._select_all_image_types()
        self._select_all_categories()
        self._on_change()

    @staticmethod
    def _parse_date(s: str) -> Optional[datetime]:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s.strip(), fmt)
            except ValueError:
                continue
        return None


class _ScrollableFrame(tk.Frame):
    """A tk.Frame with a vertical scrollbar."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("bg", COLOR_FRAME_BG)
        super().__init__(master, **kwargs)
        canvas = tk.Canvas(self, bg=COLOR_FRAME_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = tk.Frame(canvas, bg=COLOR_FRAME_BG)
        window = canvas.create_window((0, 0), window=self.inner, anchor=tk.NW)

        def _on_inner_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(window, width=e.width)

        self.inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        # Routed by pointer position so the filter list scrolls without having
        # to be clicked first. See ui/wheel.py.
        wheel.register(self, lambda e: canvas.yview_scroll(
            -1 * (e.delta // 120), "units"))
