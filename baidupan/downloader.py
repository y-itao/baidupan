"""Download: chunked download + resume + concurrent segments with per-worker dlink."""

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from . import config
from .api import BaiduPanAPI
from .utils import ProgressBar

log = logging.getLogger(__name__)


# ── Download progress persistence ─────────────────────────────────

def _progress_file(remote_path: str) -> str:
    safe = remote_path.replace("/", "_").strip("_")
    return os.path.join(config.DOWNLOAD_PROGRESS_DIR, safe + ".json")


def _load_progress(remote_path: str) -> dict | None:
    path = _progress_file(remote_path)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_progress(remote_path: str, data: dict):
    os.makedirs(config.DOWNLOAD_PROGRESS_DIR, exist_ok=True)
    with open(_progress_file(remote_path), "w") as f:
        json.dump(data, f)


def _clear_progress(remote_path: str):
    path = _progress_file(remote_path)
    if os.path.exists(path):
        os.remove(path)


# ── Download logic ────────────────────────────────────────────────

def download_file(api: BaiduPanAPI, fs_id: int, remote_path: str,
                  local_path: str, file_size: int, concurrent: bool = False,
                  workers: int = None, segment_size: int = None) -> str:
    """Download a single file with resume support.

    For files larger than CONCURRENT_DOWNLOAD_THRESHOLD, automatically
    uses concurrent segmented download with per-worker dlink to
    maximize bandwidth (each worker gets its own download link).
    """
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)

    # Auto-enable concurrent for large files
    use_concurrent = concurrent or file_size > config.CONCURRENT_DOWNLOAD_THRESHOLD
    seg = segment_size or config.DOWNLOAD_SEGMENT_SIZE

    if use_concurrent and file_size > seg:
        return _download_concurrent(api, fs_id, remote_path, local_path,
                                    file_size, workers, segment_size=seg)

    return _download_simple(api, fs_id, remote_path, local_path, file_size)


def _download_simple(api: BaiduPanAPI, fs_id: int, remote_path: str,
                     local_path: str, file_size: int) -> str:
    """Single-threaded download with byte-range resume."""
    tmp_path = local_path + ".baidupan.tmp"
    downloaded = 0

    # check for existing partial download
    if os.path.exists(tmp_path):
        downloaded = os.path.getsize(tmp_path)
        if downloaded >= file_size:
            os.rename(tmp_path, local_path)
            _clear_progress(remote_path)
            return local_path
        log.info("Resuming download from byte %d", downloaded)

    dlink = api.get_download_link(fs_id)

    headers = {}
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"

    resp = api.download_stream(dlink, headers=headers)

    with ProgressBar(file_size, desc=f"Downloading {os.path.basename(local_path)}") as pbar:
        if downloaded > 0:
            pbar.update(downloaded)

        mode = "ab" if downloaded > 0 else "wb"
        with open(tmp_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    pbar.update(len(chunk))

    os.rename(tmp_path, local_path)
    _clear_progress(remote_path)
    log.info("Downloaded: %s -> %s", remote_path, local_path)
    return local_path


def _download_stream_with_refresh(api, fs_id, dlink, headers, max_retries=5):
    """Try to download a stream, refreshing dlink on 403."""
    current_dlink = dlink
    for attempt in range(max_retries):
        try:
            return api.download_stream(current_dlink, headers=headers), current_dlink
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                if attempt < max_retries - 1:
                    wait = 1.0 * (attempt + 1)
                    log.debug("403 on download, refreshing dlink (attempt %d, wait %.1fs)",
                              attempt + 1, wait)
                    time.sleep(wait)
                    current_dlink = api.get_download_link(fs_id)
                    continue
            raise
    raise requests.HTTPError("Max retries exceeded for download stream")


def _download_concurrent(api: BaiduPanAPI, fs_id: int, remote_path: str,
                         local_path: str, file_size: int,
                         workers: int = None,
                         segment_size: int = None) -> str:
    """Multi-threaded segmented download with per-worker dlink.

    Key optimization: each worker gets ONE dlink and downloads all its
    assigned segments using that dlink. This means:
      - N workers = N dlink API calls (not N_segments calls)
      - Each worker has independent CDN bandwidth allocation
      - Workers download their segments sequentially within their connection
      - On 403, worker refreshes its dlink and retries
    """
    workers = workers or config.MAX_DOWNLOAD_WORKERS
    seg_size = segment_size or config.DOWNLOAD_SEGMENT_SIZE
    tmp_path = local_path + ".baidupan.tmp"

    # compute segments
    segments = []
    offset = 0
    idx = 0
    while offset < file_size:
        end = min(offset + seg_size - 1, file_size - 1)
        segments.append((idx, offset, end))
        offset = end + 1
        idx += 1

    # check progress
    progress = _load_progress(remote_path) or {}
    completed_segs = set(progress.get("completed_segments", []))

    # pre-allocate file
    if not os.path.exists(tmp_path):
        with open(tmp_path, "wb") as f:
            f.seek(file_size - 1)
            f.write(b"\0")

    remaining = [(i, s, e) for i, s, e in segments if i not in completed_segs]
    already_bytes = sum(e - s + 1 for i, s, e in segments if i in completed_segs)

    if not remaining:
        os.rename(tmp_path, local_path)
        _clear_progress(remote_path)
        return local_path

    # Distribute remaining segments across workers (round-robin)
    actual_workers = min(workers, len(remaining))
    worker_segments = [[] for _ in range(actual_workers)]
    for i, seg in enumerate(remaining):
        worker_segments[i % actual_workers].append(seg)

    # Lock for progress file writes
    progress_lock = threading.Lock()
    start_time = time.monotonic()

    log.info("Concurrent download: %d segments across %d workers (seg_size=%s)",
             len(remaining), actual_workers,
             f"{seg_size / 1024 / 1024:.0f}MB")

    with ProgressBar(file_size, desc=f"Downloading {os.path.basename(local_path)}") as pbar:
        if already_bytes > 0:
            pbar.update(already_bytes)

        def _worker_task(worker_id: int, assigned_segments: list) -> list:
            """Each worker gets its own dlink and downloads all assigned segments."""
            # Stagger worker starts to avoid burst of connections
            if worker_id > 0:
                time.sleep(0.1 * worker_id)

            dlink = api.get_download_link(fs_id)
            done = []
            for seg_idx, start, end in assigned_segments:
                headers = {"Range": f"bytes={start}-{end}"}
                # Use dlink refresh on 403
                resp, dlink = _download_stream_with_refresh(
                    api, fs_id, dlink, headers)
                with open(tmp_path, "r+b") as f:
                    f.seek(start)
                    for chunk in resp.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
                done.append(seg_idx)
                # Save progress after each segment
                with progress_lock:
                    completed_segs.add(seg_idx)
                    _save_progress(remote_path, {
                        "completed_segments": sorted(completed_segs),
                    })
            return done

        with ThreadPoolExecutor(max_workers=actual_workers) as pool:
            futures = {
                pool.submit(_worker_task, i, segs): i
                for i, segs in enumerate(worker_segments)
            }
            for future in as_completed(futures):
                future.result()  # raises on error

    elapsed = time.monotonic() - start_time
    dl_bytes = sum(e - s + 1 for _, s, e in remaining)
    speed = dl_bytes / elapsed if elapsed > 0 else 0
    log.info("Downloaded (concurrent): %s -> %s  %.2f MB/s",
             remote_path, local_path, speed / 1024 / 1024)

    os.rename(tmp_path, local_path)
    _clear_progress(remote_path)
    return local_path


def download_by_meta(api: BaiduPanAPI, meta: dict, local_path: str,
                     concurrent: bool = False, workers: int = None,
                     segment_size: int = None) -> str:
    """Download a file given its metadata dict (from list/search)."""
    return download_file(
        api,
        fs_id=meta["fs_id"],
        remote_path=meta["path"],
        local_path=local_path,
        file_size=meta["size"],
        concurrent=concurrent,
        workers=workers,
        segment_size=segment_size,
    )


def download_dir(api: BaiduPanAPI, remote_dir: str, local_dir: str,
                 concurrent: bool = False, workers: int = None,
                 segment_size: int = None):
    """Recursively download a remote directory."""
    result = api.list_all(remote_dir)
    items = result.get("list", [])
    downloaded = []

    for item in items:
        if item.get("isdir"):
            continue

        rel = item["path"][len(remote_dir):].lstrip("/")
        local_path = os.path.join(local_dir, rel)

        download_file(
            api,
            fs_id=item["fs_id"],
            remote_path=item["path"],
            local_path=local_path,
            file_size=item["size"],
            concurrent=concurrent,
            workers=workers,
            segment_size=segment_size,
        )
        downloaded.append(local_path)

    return downloaded
