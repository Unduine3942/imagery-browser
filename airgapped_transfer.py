from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from models import ImageryRecord

log = logging.getLogger(__name__)

# Root-level files to include when bundling the browser application.
_APP_ROOT = Path(__file__).parent
_BROWSER_ROOT_FILES = (
    "imagery_browser.py",
    "launch.bat",
    "config.py",
    "models.py",
    "scanner.py",
    "nitf.py",
    "imagery_manager.py",
    "downloader.py",
    "footprint_manager.py",
    "clipper.py",
    "airgapped_transfer.py",
)
_BROWSER_DIRS = ("ui",)
_BROWSER_OPTIONAL_DIRS = ("assets",)  # included only when present

# A self-contained PyInstaller build, if it has been produced (see build.bat).
# When present it is bundled in preference to the raw source so the target
# machine needs neither ArcGIS Pro nor a Python install.
_FROZEN_DIST = _APP_ROOT / "dist" / "ImageryBrowser"
_FROZEN_EXE = "ImageryBrowser.exe"

# Sidecar extensions keyed off the same stem as the primary file
_STEM_SIDECAR_EXTS = (
    ".prj",      # projection (BIL/BIP/BSQ, world-file rasters)
    ".hdr",      # header     (BIL/BIP/BSQ — required to open the data file)
    ".stx",      # band statistics  (BIL/BIP/BSQ)
    ".clr",      # colour map
    ".ovr",      # GDAL overview pyramids
    ".idx",      # index      (MRF)
    ".tfw",      # TIFF world file
    ".tifw",     # alternate TIFF world file suffix
    ".j2w",      # JPEG2000 world file
    ".pgw",      # PNG world file
    ".pngw",     # alternate PNG world file suffix
    ".bqw",      # BSQ world file
    ".aux",      # ERDAS auxiliary
    ".rrd",      # ERDAS reduced-resolution dataset
)


@dataclass
class ImportResult:
    records: list[ImageryRecord] = field(default_factory=list)
    missing_count: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Imported {len(self.records)} record(s)."]
        if self.missing_count:
            lines.append(f"{self.missing_count} file(s) not found in package.")
            lines.extend(f"  • {e}" for e in self.errors[:5])
        return "\n".join(lines)


@dataclass
class TransferPackage:
    dest_path: str = ""
    manifest_path: str = ""
    success_count: int = 0
    failed_count: int = 0
    browser_bundled: bool = False
    browser_kind: str = ""  # "exe" (self-contained build) or "source"
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Transferred {self.success_count} file(s) to:\n{self.dest_path}"]
        if self.browser_bundled:
            if self.browser_kind == "exe":
                lines.append(
                    "Imagery Browser included — run "
                    "imagery_browser\\ImageryBrowser.exe on the target system "
                    "(no ArcGIS Pro or Python required)."
                )
            else:
                lines.append(
                    "Imagery Browser source included — run "
                    "imagery_browser\\launch.bat on the target system."
                )
        if self.manifest_path:
            lines.append(f"Manifest: {self.manifest_path}")
        if self.failed_count:
            lines.append(f"\n{self.failed_count} file(s) failed:")
            lines.extend(f"  • {e}" for e in self.errors[:5])
        return "\n".join(lines)


class AirgappedTransfer:
    """Package selected imagery records for physical transfer to an air-gapped system.

    Copies imagery files (plus all companion sidecar files) into dest_dir and
    writes a manifest.json so the receiving system can import records without
    rescanning.
    """

    def package(self, records: list[ImageryRecord], dest_dir: str) -> TransferPackage:
        if not records:
            return TransferPackage()

        dest = Path(dest_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        result = TransferPackage(dest_path=str(dest))
        copied_records: list[ImageryRecord] = []

        for record in records:
            src_raw = Path(record.filepath)
            if src_raw.is_symlink():
                result.failed_count += 1
                result.errors.append(f"{record.filename}: symbolic links are not supported")
                continue
            src = src_raw.resolve()
            if not src.is_file():
                result.failed_count += 1
                result.errors.append(f"{record.filename}: source is not a regular file")
                continue
            dst = (dest / record.filename).resolve()
            if not str(dst).startswith(str(dest)):
                result.failed_count += 1
                result.errors.append(f"{record.filename}: destination path escapes transfer directory")
                continue
            renamed = dst.exists()
            if renamed:
                dst = (dest / f"{record.id[:8]}_{record.filename}").resolve()
            try:
                shutil.copy2(str(src), str(dst))
                result.success_count += 1
                copied_records.append(record)
            except Exception as exc:
                result.failed_count += 1
                result.errors.append(f"{record.filename}: {exc}")
                continue  # skip companions when primary copy failed

            prefix = f"{record.id[:8]}_" if renamed else ""
            for companion in _companion_files(src):
                companion_dst = (dest / (prefix + companion.name)).resolve()
                if not str(companion_dst).startswith(str(dest)):
                    result.errors.append(f"{companion.name} (sidecar): destination path escapes transfer directory")
                    continue
                if companion_dst.exists():
                    companion_dst = (dest / f"{record.id[:8]}_{companion.name}").resolve()
                try:
                    shutil.copy2(str(companion), str(companion_dst))
                except Exception as exc:
                    result.errors.append(f"{companion.name} (sidecar): {exc}")

        browser_dir, browser_kind = _bundle_browser(dest)
        result.browser_bundled = browser_dir is not None
        result.browser_kind = browser_kind

        manifest_path = dest / "manifest.json"
        manifest = {
            "created_at": datetime.now().isoformat(),
            "record_count": len(copied_records),
            "records": [_to_portable_dict(r, dest) for r in copied_records],
            "browser_included": result.browser_bundled,
            "browser_path": browser_dir.name if browser_dir else None,
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        result.manifest_path = str(manifest_path)
        return result


class AirgappedImporter:
    """Import records from a manifest.json written by AirgappedTransfer.package().

    Resolves relative filepaths against the package directory so records point
    to the locally-copied files rather than the original source machine paths.
    """

    def import_from_manifest(self, manifest_path: str) -> ImportResult:
        manifest_p = Path(manifest_path).resolve()
        if not manifest_p.exists():
            return ImportResult(errors=[f"Manifest not found: {manifest_path}"])
        try:
            data = json.loads(manifest_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return ImportResult(errors=[f"Cannot read manifest: {exc}"])

        pkg_dir = manifest_p.parent
        result = ImportResult()
        for raw in data.get("records", []):
            try:
                record = ImageryRecord.from_dict(raw)
            except Exception as exc:
                result.missing_count += 1
                result.errors.append(f"Bad record in manifest: {exc}")
                continue

            fp = Path(record.filepath)
            if not fp.is_absolute():
                fp = (pkg_dir / fp).resolve()
            if not fp.is_file():
                result.missing_count += 1
                result.errors.append(f"{record.filename}: file not found in package")
                continue

            d = record.to_dict()
            d["filepath"] = str(fp)
            result.records.append(ImageryRecord.from_dict(d))

        return result


def _bundle_browser(dest: Path) -> tuple[Path | None, str]:
    """Copy the imagery browser application into *dest/imagery_browser/*.

    Prefers a self-contained PyInstaller build (dist/ImageryBrowser) so the
    target needs neither ArcGIS Pro nor a Python install. Falls back to copying
    the raw source files (run via launch.bat) when no frozen build is present.

    Returns ``(browser_dir, kind)`` where *kind* is ``"exe"``, ``"source"``,
    or ``""`` when nothing could be bundled.
    """
    browser_dest = dest / "imagery_browser"
    try:
        # Preferred: a frozen, fully self-contained build.
        if _FROZEN_DIST.is_dir() and (_FROZEN_DIST / _FROZEN_EXE).exists():
            if browser_dest.exists():
                shutil.rmtree(str(browser_dest))
            shutil.copytree(str(_FROZEN_DIST), str(browser_dest))
            return browser_dest, "exe"

        # Fallback: raw source files (require Python/ArcGIS Pro on the target).
        browser_dest.mkdir(parents=True, exist_ok=True)
        copied_any = False

        for name in _BROWSER_ROOT_FILES:
            src = _APP_ROOT / name
            if src.exists():
                shutil.copy2(str(src), str(browser_dest / name))
                copied_any = True
            else:
                log.debug("Browser bundle: skipping missing file %s", src)

        for dirname in _BROWSER_DIRS:
            src_dir = _APP_ROOT / dirname
            if src_dir.exists():
                dst_dir = browser_dest / dirname
                if dst_dir.exists():
                    shutil.rmtree(str(dst_dir))
                shutil.copytree(str(src_dir), str(dst_dir))
                copied_any = True

        for dirname in _BROWSER_OPTIONAL_DIRS:
            src_dir = _APP_ROOT / dirname
            if src_dir.exists():
                dst_dir = browser_dest / dirname
                if dst_dir.exists():
                    shutil.rmtree(str(dst_dir))
                shutil.copytree(str(src_dir), str(dst_dir))

        return (browser_dest, "source") if copied_any else (None, "")
    except Exception as exc:
        log.warning("Could not bundle imagery browser: %s", exc)
        return None, ""


def _companion_files(filepath: Path) -> list[Path]:
    """Return sidecar files that exist alongside *filepath* and should be bundled."""
    parent = filepath.parent
    companions = []

    for ext in _STEM_SIDECAR_EXTS:
        candidate = parent / (filepath.stem + ext)
        if candidate.exists() and candidate != filepath:
            companions.append(candidate)

    # GDAL/ArcGIS auxiliary XML lives as <full_filename>.aux.xml
    aux_xml = parent / (filepath.name + ".aux.xml")
    if aux_xml.exists():
        companions.append(aux_xml)

    return companions


def _to_portable_dict(record: ImageryRecord, dest: Path) -> dict:
    d = record.to_dict()
    # Make filepath relative so the package is portable across machines
    try:
        d["filepath"] = Path(record.filepath).name
    except Exception:
        pass
    return d
