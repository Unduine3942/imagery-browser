"""Route <MouseWheel> to whatever the pointer is actually over.

Tk 8.6 on Windows delivers <MouseWheel> to the widget holding keyboard focus,
not the widget under the cursor, so a plain per-widget bind does nothing until
something focuses that widget. The obvious workaround -- grab the wheel on
<Enter> and drop it on <Leave> -- breaks on any container with children,
because moving the pointer from the container onto one of its own child
widgets fires <Leave> on the container.

Instead, install a single application-level binding that looks up the widget
under the pointer and walks up its parent chain to the nearest registered
scroll target. That is stable no matter how deeply the content is nested.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

# widget path -> handler
_HANDLERS: dict[str, Callable] = {}
_ROOT_FLAG = "_wheel_router_installed"


def find_handler(widget) -> Callable | None:
    """Nearest registered handler at or above *widget*, else None."""
    seen = 0
    while widget is not None and seen < 50:   # guard against cycles
        handler = _HANDLERS.get(str(widget))
        if handler is not None:
            return handler
        widget = getattr(widget, "master", None)
        seen += 1
    return None


def register(widget: tk.Misc, handler: Callable) -> None:
    """Send wheel events to *handler* whenever the pointer is over *widget*
    or any of its descendants."""
    _HANDLERS[str(widget)] = handler
    widget.bind("<Destroy>", lambda e, p=str(widget): _HANDLERS.pop(p, None),
                add="+")

    root = widget.winfo_toplevel()
    if getattr(root, _ROOT_FLAG, False):
        return

    def dispatch(event, _root=root):
        try:
            target = _root.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, AttributeError):
            return None
        handler = find_handler(target)
        if handler is None:
            return None
        handler(event)
        return "break"

    root.bind_all("<MouseWheel>", dispatch, add="+")

    # Comboboxes and spinboxes change their value on the wheel by default, so
    # scrolling over one silently edits a filter instead of scrolling the panel
    # it sits in. Replace that class binding with one that scrolls the
    # surrounding panel and stops there.
    def value_widget_wheel(event):
        handler = find_handler(getattr(event, "widget", None))
        if handler is not None:
            handler(event)
        return "break"

    for cls in ("TCombobox", "TSpinbox", "Spinbox"):
        root.bind_class(cls, "<MouseWheel>", value_widget_wheel)

    setattr(root, _ROOT_FLAG, True)
