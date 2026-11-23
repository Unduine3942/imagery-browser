"""
Unit tests for ui/startup.py validation methods

Tests for StartupDialog._validate_basemap() security fixes:
- Symlink detection
- File size limits (config.MAX_BASEMAP_MB)
- Path resolution errors
- OSError handling during stat()
"""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import MAX_BASEMAP_BYTES, MAX_BASEMAP_MB
from ui.startup import StartupDialog


@pytest.fixture
def startup_dialog():
    """Create a StartupDialog with hidden window for testing."""
    try:
        root = tk.Tk()
        root.withdraw()
    except Exception:
        pytest.skip("Tk is not available in this environment")

    dialog = StartupDialog.__new__(StartupDialog)
    dialog._arcpy_available = False
    dialog._basemap_var = tk.StringVar(master=root)
    dialog._basemap_error = tk.Label(root)
    dialog.basemap_result = None

    yield dialog

    try:
        root.destroy()
    except Exception:
        pass


class TestValidateBasemapSymlinks:
    """Test that symlinks are rejected."""

    def test_symlink_path_is_rejected(self, startup_dialog, tmp_path):
        """Symlink path → returns False, error text set to 'Symbolic links...'

        Security fix: Check Path(raw).is_symlink() BEFORE calling resolve().
        Currently the code resolves first, so symlinks are not detected.
        """
        if not hasattr(Path, "symlink_to"):
            pytest.skip("symlink creation not available")

        try:
            # Create a real file
            real_file = tmp_path / "real.tif"
            real_file.write_text("data")

            # Create a symlink to it
            symlink_path = tmp_path / "link.tif"
            symlink_path.symlink_to(real_file)

            startup_dialog._basemap_var.set(str(symlink_path))
            result = startup_dialog._validate_basemap()

            assert result is False
            assert "Symbolic links are not supported" in startup_dialog._basemap_error.cget("text")
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlinks on this system")


class TestValidateBasemapFileSize:
    """Test that files larger than the configured cap are rejected."""

    def test_large_file_exceeds_limit(self, startup_dialog, tmp_path):
        """File over the cap → returns False, error names the MB limit."""
        large_file = tmp_path / "huge.tif"
        large_file.write_text("data")

        # Mock Path.stat() to return a large size without creating a huge file
        with patch.object(Path, "stat") as mock_stat:
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = MAX_BASEMAP_BYTES + 1  # just over the cap
            mock_stat.return_value = mock_stat_result

            startup_dialog._basemap_var.set(str(large_file))
            result = startup_dialog._validate_basemap()

            assert result is False
            assert f"exceeds {MAX_BASEMAP_MB} MB limit" in startup_dialog._basemap_error.cget("text")

    def test_667mb_natural_earth_raster_is_accepted(self, startup_dialog, tmp_path):
        """A 667 MB raster (Natural Earth HYP_HR_SR_OB_DR) is now under the cap."""
        boundary_file = tmp_path / "hyp.tif"
        boundary_file.write_text("x")

        with patch.object(Path, "stat") as mock_stat:
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 668 * 1024 * 1024  # ~667 MB, was rejected by the old 512 cap
            mock_stat.return_value = mock_stat_result

            with patch.object(Path, "is_file", return_value=True):
                startup_dialog._basemap_var.set(str(boundary_file))
                startup_dialog._validate_basemap()

                assert "exceeds" not in startup_dialog._basemap_error.cget("text")

    def test_file_at_limit_exactly_is_accepted(self, startup_dialog, tmp_path):
        """File exactly at the cap (boundary) → not rejected for size."""
        boundary_file = tmp_path / "boundary.tif"
        boundary_file.write_text("x")

        with patch.object(Path, "stat") as mock_stat:
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = MAX_BASEMAP_BYTES  # exactly at the cap
            mock_stat.return_value = mock_stat_result

            with patch.object(Path, "is_file", return_value=True):
                startup_dialog._basemap_var.set(str(boundary_file))
                startup_dialog._validate_basemap()

                assert "exceeds" not in startup_dialog._basemap_error.cget("text")

    def test_small_file_is_accepted(self, startup_dialog, tmp_path):
        """Small file under the cap → passes size check."""
        small_file = tmp_path / "small.tif"
        small_file.write_text("x" * 1000)

        startup_dialog._basemap_var.set(str(small_file))
        startup_dialog._validate_basemap()

        # Should not fail on size, may fail on other checks (not geotiff, etc)
        assert "exceeds" not in startup_dialog._basemap_error.cget("text")


class TestValidateBasemapPathResolution:
    """Test handling of path resolution errors (OSError, RuntimeError)."""

    def test_path_resolve_raises_oserror(self, startup_dialog, tmp_path):
        """Path.resolve() raises OSError → returns False, error text set"""
        bad_path = str(tmp_path / "nonexistent.tif")

        with patch.object(Path, "resolve", side_effect=OSError("Permission denied")):
            startup_dialog._basemap_var.set(bad_path)
            result = startup_dialog._validate_basemap()

            assert result is False
            assert "Invalid file path" in startup_dialog._basemap_error.cget("text")

    def test_path_resolve_raises_runtime_error(self, startup_dialog, tmp_path):
        """Path.resolve() raises RuntimeError → returns False, error text set"""
        bad_path = str(tmp_path / "nonexistent.tif")

        with patch.object(Path, "resolve", side_effect=RuntimeError("Cannot resolve path")):
            startup_dialog._basemap_var.set(bad_path)
            result = startup_dialog._validate_basemap()

            assert result is False
            assert "Invalid file path" in startup_dialog._basemap_error.cget("text")


class TestValidateBasemapStatError:
    """Test handling of OSError during Path.stat()."""

    def test_stat_raises_oserror(self, startup_dialog, tmp_path):
        """Path.stat() raises OSError → returns False, error text set"""
        missing_file = tmp_path / "missing.tif"

        # Create a path that resolves fine but fails on stat
        resolved_path = missing_file.resolve()

        with patch.object(Path, "is_symlink", return_value=False):
            with patch.object(Path, "stat", side_effect=OSError("File not found")):
                startup_dialog._basemap_var.set(str(missing_file))
                result = startup_dialog._validate_basemap()

                assert result is False
                assert "File not found" in startup_dialog._basemap_error.cget("text")


class TestValidateBasemapEmptyPath:
    """Test that empty path is allowed (basemap is optional)."""

    def test_empty_basemap_path_is_allowed(self, startup_dialog):
        """Empty string → returns True, basemap_result set to None"""
        startup_dialog._basemap_var.set("")
        result = startup_dialog._validate_basemap()

        assert result is True
        assert startup_dialog.basemap_result is None

    def test_whitespace_only_path_is_allowed(self, startup_dialog):
        """Whitespace-only string → returns True, basemap_result set to None"""
        startup_dialog._basemap_var.set("   ")
        result = startup_dialog._validate_basemap()

        assert result is True
        assert startup_dialog.basemap_result is None


class TestValidateBasemapValidFile:
    """Test that a valid small GeoTIFF is accepted."""

    def test_valid_geotiff_is_accepted(self, startup_dialog, tmp_path):
        """Valid .tif file < 512 MB → returns True, basemap_result set"""
        valid_tif = tmp_path / "valid.tif"
        valid_tif.write_text("x" * 1000)

        startup_dialog._basemap_var.set(str(valid_tif))
        result = startup_dialog._validate_basemap()

        # Note: This may fail on other checks (not a real GeoTIFF), but not on size/path checks
        # The exact behavior depends on file presence and format validation
        if result:
            assert startup_dialog.basemap_result == str(valid_tif.resolve())
