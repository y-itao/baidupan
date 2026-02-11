"""Tests for baidupan.errors."""

import time
from unittest.mock import patch

import pytest

from baidupan.errors import (
    APIError,
    AuthError,
    BaiduPanError,
    DownloadError,
    FileNotFoundError_,
    QuotaExceededError,
    UploadError,
    retry,
)


class TestExceptionHierarchy:
    def test_base(self):
        assert issubclass(AuthError, BaiduPanError)
        assert issubclass(APIError, BaiduPanError)
        assert issubclass(QuotaExceededError, BaiduPanError)
        assert issubclass(FileNotFoundError_, BaiduPanError)
        assert issubclass(UploadError, BaiduPanError)
        assert issubclass(DownloadError, BaiduPanError)

    def test_api_error_attrs(self):
        e = APIError(31023, "file does not exist", "req-123")
        assert e.errno == 31023
        assert e.msg == "file does not exist"
        assert e.request_id == "req-123"
        assert "31023" in str(e)
        assert "file does not exist" in str(e)

    def test_api_error_defaults(self):
        e = APIError(42)
        assert e.msg == ""
        assert e.request_id == ""


class TestRetryDecorator:
    @patch("baidupan.errors.time.sleep")
    def test_success_no_retry(self, mock_sleep):
        call_count = 0

        @retry(max_retries=3, backoff=0.01, exceptions=(ValueError,))
        def ok():
            nonlocal call_count
            call_count += 1
            return "done"

        assert ok() == "done"
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("baidupan.errors.time.sleep")
    def test_retry_then_succeed(self, mock_sleep):
        call_count = 0

        @retry(max_retries=3, backoff=0.01, exceptions=(ValueError,))
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("boom")
            return "ok"

        assert flaky() == "ok"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("baidupan.errors.time.sleep")
    def test_retry_exhausted(self, mock_sleep):
        @retry(max_retries=2, backoff=0.01, exceptions=(RuntimeError,))
        def always_fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError, match="fail"):
            always_fail()
        assert mock_sleep.call_count == 1  # only sleeps between retries, not after last

    @patch("baidupan.errors.time.sleep")
    def test_no_retry_on_unhandled_exception(self, mock_sleep):
        @retry(max_retries=3, backoff=0.01, exceptions=(ValueError,))
        def wrong_exc():
            raise TypeError("not matched")

        with pytest.raises(TypeError):
            wrong_exc()
        mock_sleep.assert_not_called()

    @patch("baidupan.errors.time.sleep")
    def test_backoff_increases(self, mock_sleep):
        @retry(max_retries=4, backoff=1.0, exceptions=(ValueError,))
        def always_fail():
            raise ValueError("x")

        with pytest.raises(ValueError):
            always_fail()

        # backoff = 1.0 * attempt: sleeps at 1.0, 2.0, 3.0
        calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert calls == [1.0, 2.0, 3.0]
