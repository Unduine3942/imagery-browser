from __future__ import annotations

# -- core palette: Sentinel dark theme (matches Shared Drive Policy Manager /
#    GEOINT Data Manager) — near-black backgrounds, slate panels, cyan accents --
COLOR_HEADER    = "#101820"   # panel-toned header bars
COLOR_HEADER_FG = "#E6EEF5"   # header body text
COLOR_ACCENT    = "#00D5FF"   # cyan brand accent (titles, highlights)
COLOR_BG        = "#090E14"   # app background
COLOR_FRAME_BG  = "#101820"   # panel background
COLOR_PANEL_2   = "#13202B"   # raised panel / hover
COLOR_PANEL_3   = "#182633"   # pressed / neutral button
COLOR_SELECT    = "#1E3A4A"   # selection background
COLOR_BORDER    = "#243849"
COLOR_TEXT      = "#E6EEF5"
COLOR_MUTED     = "#8DA2B3"
COLOR_DIM       = "#526878"
COLOR_ENTRY_BG  = "#0C131B"
COLOR_BTN       = "#00D5FF"   # primary action (cyan)
COLOR_BTN_FG    = "#090E14"   # dark text on bright accent buttons
COLOR_BTN_HOVER = "#00B8DC"
COLOR_WARN      = "#FFB020"
COLOR_ERROR     = "#FF4D5E"
COLOR_SUCCESS   = "#43FF9B"
COLOR_SECTION_BG = "#13202B"  # filter panel section backgrounds

# Secondary button roles (previously hardcoded inline)
COLOR_BTN_SUCCESS    = "#43FF9B"  # Scan
COLOR_BTN_DANGER     = "#FF4D5E"  # Cancel
COLOR_BTN_NEUTRAL    = "#182633"  # Clear / Reset / Export
COLOR_BTN_NEUTRAL_FG = "#E6EEF5"
COLOR_BTN_SECONDARY  = "#4C8DFF"  # Transfer

# Tooltip (map hover)
COLOR_TOOLTIP_BG = "#182633"
COLOR_TOOLTIP_FG = "#E6EEF5"

# -- canvas --
# NOTE: deliberately NOT dark — the canvas background must blend with the
# bundled light world-basemap tiles (OSM ocean blue hides tile seams).
COLOR_CANVAS_BG     = "#a8c8e8"
COLOR_CANVAS_GRID   = "#2d2d44"
COLOR_CANVAS_LABEL  = "#aaaacc"
COLOR_SELECTED_BOX  = "#f1c40f"  # yellow — must stay visible over the light map

# -- colour maps (single source of truth lives in config) --
from config import FORMAT_COLORS as FORMAT_COLORS          # noqa: E402, F401
from config import IMAGE_TYPE_COLORS as IMAGE_TYPE_COLORS  # noqa: E402, F401
from config import ICAT_COLORS as ICAT_COLORS              # noqa: E402, F401
from config import ICAT_LABELS as ICAT_LABELS              # noqa: E402, F401

# -- fonts --
FONT_TITLE  = ("Segoe UI Semibold", 12)
FONT_HEADER = ("Segoe UI Semibold", 10)
FONT_NORMAL = ("Segoe UI", 9)
FONT_SMALL  = ("Segoe UI", 8)
FONT_MONO   = ("Consolas", 9)

# -- layout --
PAD = 6
PAD_SMALL = 3
FILTER_WIDTH = 280
PANEL_WIDTH  = 340


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"
