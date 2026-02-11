"""Tests for baidupan.utils."""

import io
import logging
import sys
from unittest.mock import patch

from baidupan.utils import ProgressBar, format_size, format_time, setup_logging


class TestFormatSize:
    def test_bytes(self):
        assert format_size(0) == "0.0 B"
        assert format_size(512) == "512.0 B"
        assert format_size(1023) == "1023.0 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1048576) == "1.0 MB"

    def test_gigabytes(self):
        assert format_size(1073741824) == "1.0 GB"

    def test_terabytes(self):
        assert format_size(1099511627776) == "1.0 TB"

    def test_petabytes(self):
        assert format_size(1125899906842624) == "1.0 PB"


class TestFormatTime:
    def test_epoch(self):
        result = format_time(0)
        # should produce a valid date string
        assert len(result) == 19  # YYYY-MM-DD HH:MM:SS

    def test_specific_timestamp(self):
        # 2024-01-01 00:00:00 UTC = 1704067200
        result = format_time(1704067200)
        assert "2024" in result
        assert "-" in result


class TestSetupLogging:
    def test_verbose_mode(self):
        setup_logging(verbose=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_normal_mode(self):
        setup_logging(verbose=False)
        root = logging.getLogger()
        assert root.level == logging.INFO


class TestProgressBar:
    @patch("baidupan.utils.HAS_TQDM", False)
    def test_fallback_progress(self):
        """Test simple fallback when tqdm is not available."""
        bar = ProgressBar.__new__(ProgressBar)
        bar.total = 100
        bar.desc = "test"
        bar.n = 0
        bar._bar = None
        bar._last_pct = -1

        with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            bar.update(50)
            bar.update(50)
            bar.close()
        output = mock_err.getvalue()
        assert "100%" in output

    @patch("baidupan.utils.HAS_TQDM", False)
    def test_context_manager(self):
        bar = ProgressBar.__new__(ProgressBar)
        bar.total = 100
        bar.desc = "ctx"
        bar.n = 0
        bar._bar = None
        bar._last_pct = -1

        with patch("sys.stderr", new_callable=io.StringIO):
            with bar as b:
                b.update(100)
            # should not raise
