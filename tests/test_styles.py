"""
Unit tests for ui/styles.py

Tests cover:
- format_bytes() conversion for B, KB, MB, GB
- format_bytes() rounding and precision
- COLOR_* constants availability
- FORMAT_COLORS mapping
"""
import pytest
from ui.styles import format_bytes, FORMAT_COLORS


class TestFormatBytes:
    """Tests for format_bytes() function."""

    def test_format_bytes_zero(self):
        """format_bytes() should format 0 bytes as '0 B'."""
        assert format_bytes(0) == "0 B"

    def test_format_bytes_single_byte(self):
        """format_bytes() should format 1 byte as '1 B'."""
        assert format_bytes(1) == "1 B"

    def test_format_bytes_under_1kb(self):
        """format_bytes() should return 'B' for values < 1024."""
        assert format_bytes(512) == "512 B"
        assert format_bytes(1023) == "1023 B"

    def test_format_bytes_exactly_1kb(self):
        """format_bytes() at 1024 bytes should switch to KB."""
        result = format_bytes(1024)
        assert "KB" in result
        assert "1.0" in result

    def test_format_bytes_kilobytes_range(self):
        """format_bytes() should format KB range with one decimal place."""
        assert "1.5 KB" == format_bytes(1024 + 512)  # 1.5 KB
        assert "10.0 KB" == format_bytes(10 * 1024)  # 10 KB
        assert "99.9 KB" == format_bytes(int(99.9 * 1024))  # ~99.9 KB

    def test_format_bytes_just_under_1mb(self):
        """format_bytes() should stay in KB range just under 1 MB."""
        result = format_bytes(1024 * 1024 - 1)
        assert "KB" in result

    def test_format_bytes_exactly_1mb(self):
        """format_bytes() at 1 MB should switch to MB."""
        result = format_bytes(1024 * 1024)
        assert "MB" in result
        assert "1.0" in result

    def test_format_bytes_megabytes_range(self):
        """format_bytes() should format MB range with one decimal place."""
        assert "1.5 MB" == format_bytes(int(1.5 * 1024 * 1024))
        assert "10.0 MB" == format_bytes(10 * 1024 * 1024)
        assert "99.9 MB" == format_bytes(int(99.9 * 1024 * 1024))

    def test_format_bytes_just_under_1gb(self):
        """format_bytes() should stay in MB range just under 1 GB."""
        result = format_bytes(1024 * 1024 * 1024 - 1)
        assert "MB" in result

    def test_format_bytes_exactly_1gb(self):
        """format_bytes() at 1 GB should switch to GB."""
        result = format_bytes(1024 * 1024 * 1024)
        assert "GB" in result
        assert "1.0" in result

    def test_format_bytes_gigabytes_range(self):
        """format_bytes() should format GB range with two decimal places."""
        assert "1.50 GB" == format_bytes(int(1.5 * 1024 * 1024 * 1024))
        assert "10.00 GB" == format_bytes(10 * 1024 * 1024 * 1024)
        assert "99.99 GB" == format_bytes(int(99.99 * 1024 * 1024 * 1024))

    def test_format_bytes_large_gigabytes(self):
        """format_bytes() should format large GB values."""
        assert "1000.00 GB" == format_bytes(1000 * 1024 * 1024 * 1024)

    def test_format_bytes_100mb(self):
        """format_bytes() should correctly format 100 MB."""
        result = format_bytes(100 * 1024 * 1024)
        assert "100.0 MB" == result

    def test_format_bytes_256mb(self):
        """format_bytes() should correctly format 256 MB."""
        result = format_bytes(256 * 1024 * 1024)
        assert "256.0 MB" == result

    def test_format_bytes_1gb_5mb(self):
        """format_bytes() should correctly format 1 GB 5 MB."""
        result = format_bytes(int(1.005 * 1024 * 1024 * 1024))
        assert "GB" in result
        assert "1.00" in result

    def test_format_bytes_returns_string(self):
        """format_bytes() should always return a string."""
        assert isinstance(format_bytes(0), str)
        assert isinstance(format_bytes(1024), str)
        assert isinstance(format_bytes(1024 * 1024), str)
        assert isinstance(format_bytes(1024 * 1024 * 1024), str)


class TestFormatColorsConstants:
    """Tests for FORMAT_COLORS constant."""

    def test_format_colors_is_dict(self):
        """FORMAT_COLORS should be a dictionary."""
        assert isinstance(FORMAT_COLORS, dict)

    def test_format_colors_has_geotiff(self):
        """FORMAT_COLORS should have GeoTIFF entry."""
        assert "GeoTIFF" in FORMAT_COLORS
        assert isinstance(FORMAT_COLORS["GeoTIFF"], str)

    def test_format_colors_has_nitf(self):
        """FORMAT_COLORS should have NITF entry."""
        assert "NITF" in FORMAT_COLORS
        assert isinstance(FORMAT_COLORS["NITF"], str)

    def test_format_colors_has_jpeg2000(self):
        """FORMAT_COLORS should have JPEG2000 entry."""
        assert "JPEG2000" in FORMAT_COLORS
        assert isinstance(FORMAT_COLORS["JPEG2000"], str)

    def test_format_colors_has_sid(self):
        """FORMAT_COLORS should have SID entry."""
        assert "SID" in FORMAT_COLORS
        assert isinstance(FORMAT_COLORS["SID"], str)

    def test_format_colors_has_ecw(self):
        """FORMAT_COLORS should have ECW entry."""
        assert "ECW" in FORMAT_COLORS
        assert isinstance(FORMAT_COLORS["ECW"], str)

    def test_format_colors_has_img(self):
        """FORMAT_COLORS should have IMG entry."""
        assert "IMG" in FORMAT_COLORS
        assert isinstance(FORMAT_COLORS["IMG"], str)

    def test_format_colors_has_unknown(self):
        """FORMAT_COLORS should have Unknown entry."""
        assert "Unknown" in FORMAT_COLORS
        assert isinstance(FORMAT_COLORS["Unknown"], str)

    def test_format_colors_values_are_hex(self):
        """FORMAT_COLORS values should be hex color strings."""
        for fmt, color in FORMAT_COLORS.items():
            assert color.startswith("#"), f"{fmt} color should start with #"
            assert len(color) == 7, f"{fmt} color should be #RRGGBB format"
            # Verify it's valid hex
            try:
                int(color[1:], 16)
            except ValueError:
                pytest.fail(f"{fmt} color {color} is not valid hex")

    def test_format_colors_consistency(self):
        """FORMAT_COLORS should match config.FORMAT_COLORS values."""
        try:
            from config import FORMAT_COLORS as config_colors
            # Styles should have all the same colors as config
            for fmt in config_colors:
                assert fmt in FORMAT_COLORS
                assert FORMAT_COLORS[fmt] == config_colors[fmt]
        except ImportError:
            pytest.skip("config module not available")
