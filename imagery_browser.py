"""
Imagery Browser
===============
Standalone imagery browser. Runs three ways, in order of preference:

1. Self-contained build — no ArcGIS Pro, no Python needed on the target:
       dist\\ImageryBrowser\\ImageryBrowser.exe
   Produce it on a dev machine with:  build.bat

2. Any Python 3.9+ with the runtime dependencies installed:
       python -m pip install -r requirements.txt
       python imagery_browser.py

3. ArcGIS Pro's bundled Python — adds live Pro map integration:
       "...\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" imagery_browser.py

arcpy is optional. Without it the app runs in canvas-only mode: it still scans,
filters, previews, and transfers imagery; it just does not push footprints into
a live ArcGIS Pro map.

Run with  --selftest  to verify every bundled dependency imports correctly
(used by build.bat to validate a standalone build).
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

# Ensure the project root is on sys.path so all imports resolve (no-op when frozen).
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _runtime_dir() -> Path:
    """Directory of the running program: the .exe folder when frozen, else this file's."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return _ROOT


def _log_handlers() -> list[logging.Handler]:
    """Build logging handlers that are safe in a frozen windowed build.

    A windowed PyInstaller build has ``sys.stdout is None``; a bare
    ``StreamHandler(sys.stdout)`` would then raise on the first log record. So
    the console handler is added only when a real stream exists, and a file
    handler is always attempted (next to the program, falling back to temp).
    """
    handlers: list[logging.Handler] = []
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    for base in (_runtime_dir(), Path(tempfile.gettempdir())):
        try:
            handlers.append(
                logging.FileHandler(base / "imagery_browser.log", encoding="utf-8")
            )
            break
        except Exception:
            continue
    if not handlers:
        handlers.append(logging.NullHandler())
    return handlers


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers(),
)

log = logging.getLogger("imagery_browser")


# -- arcpy availability check (optional) --
_ARCPY_AVAILABLE = False
try:
    import arcpy

    info = arcpy.GetInstallInfo()
    version = info.get("Version", "")
    log.info("ArcGIS Pro detected: version %s", version)
    _ARCPY_AVAILABLE = True
    if version and version < "3.3":
        log.warning(
            "ArcGIS Pro version %s is older than 3.3.1. "
            "Some features may not work as expected.",
            version,
        )
except ImportError:
    log.info(
        "arcpy not available — running in canvas-only mode. "
        "Footprints will NOT be added to a live ArcGIS Pro map."
    )
except Exception as exc:  # arcpy present but failed to initialise
    log.warning("arcpy import error: %s — running in canvas-only mode.", exc)


def _selftest() -> int:
    """Import every dependency and report. Verifies a standalone build.

    Required modules failing → exit code 1. Optional geospatial modules are
    reported but never fail the test (the app degrades gracefully without them).
    Results are written to selftest_result.txt because a frozen windowed build
    has no console to print to.
    """
    import importlib

    required = [
        "tkinter", "PIL.Image", "PIL.ImageTk", "numpy",
        "config", "models", "nitf", "scanner", "imagery_manager",
        "footprint_manager", "downloader", "airgapped_transfer", "clipper",
        "ui.app", "ui.startup", "ui.map_canvas", "ui.tile_loader", "ui.image_viewer",
    ]
    optional = ["rasterio", "pyproj", "osgeo"]

    lines: list[str] = []
    ok = True
    for name in required:
        try:
            importlib.import_module(name)
            lines.append(f"OK    {name}")
        except Exception as exc:  # report every failure, don't stop at the first
            ok = False
            lines.append(f"FAIL  {name}: {exc}")
    for name in optional:
        try:
            importlib.import_module(name)
            lines.append(f"OK    {name} (optional)")
        except Exception as exc:
            lines.append(f"SKIP  {name} (optional, not bundled): {exc}")

    report = ("SELFTEST PASS" if ok else "SELFTEST FAIL") + "\n" + "\n".join(lines) + "\n"
    try:
        (_runtime_dir() / "selftest_result.txt").write_text(report, encoding="utf-8")
    except Exception:
        pass
    try:
        if sys.stdout is not None:
            sys.stdout.write(report)
            sys.stdout.flush()
    except Exception:
        pass
    log.info("Self-test %s", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main() -> None:
    from ui.app import ImageryBrowserApp
    from ui.startup import StartupDialog

    # Honour a CLI-supplied .aprx path (e.g. when launched from ArcGIS Pro's
    # Python window), but still show the startup dialog so the user can change it.
    cli_path: str | None = None
    for arg in sys.argv[1:]:
        candidate = Path(arg)
        if candidate.suffix.lower() == ".aprx" and candidate.exists():
            cli_path = str(candidate)
            log.info("CLI project file: %s", cli_path)
            break

    dialog = StartupDialog(arcpy_available=_ARCPY_AVAILABLE)
    if cli_path:
        dialog._path_var.set(cli_path)  # pre-populate if supplied on command line
    dialog.mainloop()

    if not dialog.launched:
        # User closed the startup window — exit cleanly
        return

    aprx_path = dialog.result
    if aprx_path:
        log.info("Using project file: %s", aprx_path)

    basemap_path = dialog.basemap_result
    if basemap_path:
        log.info("Using basemap raster: %s", basemap_path)

    app = ImageryBrowserApp(
        arcpy_available=_ARCPY_AVAILABLE,
        aprx_path=aprx_path,
        basemap_path=basemap_path,
    )
    app.mainloop()


def _run() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    try:
        main()
        return 0
    except Exception:
        import traceback

        tb = traceback.format_exc()
        log.error("Fatal startup error:\n%s", tb)
        # A frozen windowed build would otherwise die with no visible error, so
        # surface it in a dialog and point at the log file.
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Imagery Browser — startup error",
                f"{tb}\n\nA full log was written to:\n{_runtime_dir() / 'imagery_browser.log'}",
            )
            root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(_run())
