"""Exception hierarchy and retry decorator."""

import functools
import time
import logging

from . import config

log = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────

class BaiduPanError(Exception):
    """Base exception for all baidupan errors."""


class AuthError(BaiduPanError):
    """Authentication / token errors."""


class APIError(BaiduPanError):
    """Remote API returned an error."""

    def __init__(self, errno, msg="", request_id=""):
        self.errno = errno
        self.msg = msg
        self.request_id = request_id
        super().__init__(f"API error {errno}: {msg}")


class QuotaExceededError(BaiduPanError):
    """Storage quota exceeded."""


class FileNotFoundError_(BaiduPanError):
    """Remote file/dir not found."""


class UploadError(BaiduPanError):
    """Upload failure."""


class DownloadError(BaiduPanError):
    """Download failure."""


# ── Retry decorator ──────────────────────────────────────────────

def retry(max_retries=None, backoff=None, exceptions=(Exception,)):
    """Decorator that retries a function on transient failures.

    Parameters
    ----------
    max_retries : int, optional
        Maximum number of retry attempts. Defaults to config.MAX_RETRIES.
    backoff : float, optional
        Base backoff in seconds. Defaults to config.RETRY_BACKOFF.
    exceptions : tuple of Exception types
        Which exceptions should trigger a retry.
    """
    if max_retries is None:
        max_retries = config.MAX_RETRIES
    if backoff is None:
        backoff = config.RETRY_BACKOFF

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff * attempt
                        log.warning(
                            "Retry %d/%d for %s after error: %s (waiting %.1fs)",
                            attempt, max_retries, func.__name__, exc, wait,
                        )
                        time.sleep(wait)
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
