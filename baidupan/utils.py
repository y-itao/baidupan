"""Progress bar, formatting, and logging utilities."""

import logging
import sys
import time

log = logging.getLogger(__name__)

# ── Try to import tqdm, fall back to simple progress ──────────────
try:
    from tqdm import tqdm as _tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


def setup_logging(verbose: bool = False):
    """Configure root logger."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)
    logging.getLogger().setLevel(level)


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


def format_time(ts: int) -> str:
    """Format a Unix timestamp to local time string."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


class ProgressBar:
    """Wrapper around tqdm with simple fallback."""

    def __init__(self, total: int, desc: str = "", unit: str = "B"):
        self.total = total
        self.desc = desc
        self.n = 0
        if HAS_TQDM:
            self._bar = _tqdm(
                total=total, desc=desc, unit=unit,
                unit_scale=True, unit_divisor=1024,
            )
        else:
            self._bar = None
            self._last_pct = -1

    def update(self, n: int):
        self.n += n
        if self._bar is not None:
            self._bar.update(n)
        else:
            pct = int(self.n * 100 / self.total) if self.total else 100
            if pct != self._last_pct and pct % 5 == 0:
                self._last_pct = pct
                sys.stderr.write(f"\r{self.desc}: {pct}% ({format_size(self.n)}/{format_size(self.total)})")
                sys.stderr.flush()

    def close(self):
        if self._bar is not None:
            self._bar.close()
        else:
            sys.stderr.write("\n")
            sys.stderr.flush()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
