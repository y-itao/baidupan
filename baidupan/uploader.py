"""Upload: rapid upload (秒传) + chunked concurrent upload + resume."""

import json
import logging
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from . import config
from .api import BaiduPanAPI
from .hasher import compute_hashes
from .utils import ProgressBar

log = logging.getLogger(__name__)

# Maximum number of batch retries (session refresh / connection recovery) before giving up
MAX_SESSION_REFRESHES = 20


# ── Upload progress persistence ───────────────────────────────────

def _progress_file(remote_path: str) -> str:
    safe = remote_path.replace("/", "_").strip("_")
    return os.path.join(config.UPLOAD_PROGRESS_DIR, safe + ".json")


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
    os.makedirs(config.UPLOAD_PROGRESS_DIR, exist_ok=True)
    with open(_progress_file(remote_path), "w") as f:
        json.dump(data, f)


def _clear_progress(remote_path: str):
    path = _progress_file(remote_path)
    if os.path.exists(path):
        os.remove(path)


# ── Upload logic ──────────────────────────────────────────────────

def upload_file(api: BaiduPanAPI, local_path: str, remote_path: str,
                workers: int = None, rtype: int = 3) -> dict:
    """Upload a single file with rapid-upload attempt, chunked upload, and resume.

    For large files, automatically scales chunk size to stay under Baidu's
    ~2048 partseq limit (default safe limit: 1024 slices). For example,
    a 12GB file uses 16MB chunks instead of 4MB.

    Also handles session expiry (400 errors) by re-creating the upload
    session via precreate and continuing from where it left off.
    """
    workers = workers or config.MAX_UPLOAD_WORKERS
    file_size = os.path.getsize(local_path)

    # Auto-scale chunk size for large files to stay under Baidu's ~2048 partseq limit
    chunk_size = config.UPLOAD_CHUNK_SIZE
    num_slices = math.ceil(file_size / chunk_size) if file_size > 0 else 1
    if num_slices > config.MAX_UPLOAD_SLICES:
        # Round up to nearest 4MB multiple
        unit = config.UPLOAD_CHUNK_SIZE
        chunk_size = math.ceil(file_size / config.MAX_UPLOAD_SLICES / unit) * unit
        chunk_mb = chunk_size // (1024 * 1024)
        final_slices = math.ceil(file_size / chunk_size)
        log.info("Large file (%.1f GB, %d slices at 4MB). "
                 "Auto-scaled chunk size to %d MB (%d slices).",
                 file_size / (1024**3), num_slices, chunk_mb, final_slices)
        if chunk_mb > 32:
            log.warning("Chunk size %d MB exceeds Baidu's documented 32 MB SVIP limit. "
                        "Upload may fail depending on your account tier.", chunk_mb)

    # compute hashes (single-pass, cached)
    hashes = compute_hashes(local_path, chunk_size=chunk_size)

    # ── Step 1: precreate (also attempts rapid upload) ────────────
    pre = api.precreate(
        remote_path=remote_path,
        size=file_size,
        isdir=0,
        block_list=hashes.block_list,
        content_md5=hashes.content_md5,
        slice_md5=hashes.slice_md5,
        rtype=rtype,
    )

    return_type = pre.get("return_type")

    # return_type == 2 means rapid upload succeeded
    if return_type == 2:
        log.info("Rapid upload succeeded for %s", local_path)
        _clear_progress(remote_path)
        return pre

    upload_id = pre["uploadid"]
    block_list_need = pre.get("block_list", list(range(len(hashes.block_list))))

    # ── Step 2: check resume state ────────────────────────────────
    progress = _load_progress(remote_path)
    uploaded_parts = set()
    if progress:
        saved_chunk = progress.get("chunk_size", config.UPLOAD_CHUNK_SIZE)
        if saved_chunk != chunk_size:
            log.info("Chunk size changed (%d -> %d), discarding old progress",
                     saved_chunk, chunk_size)
            _clear_progress(remote_path)
        else:
            uploaded_parts = set(progress.get("uploaded_parts", []))
            if uploaded_parts:
                log.info("Resuming upload: %d/%d slices already uploaded",
                         len(uploaded_parts), len(hashes.block_list))

    parts_remaining = [i for i in block_list_need if i not in uploaded_parts]

    if not parts_remaining:
        log.info("All slices already uploaded, creating file...")
    else:
        # Upload slices with automatic session refresh on 400 errors
        _upload_slices_with_refresh(
            api, local_path, remote_path, file_size, chunk_size,
            hashes, upload_id, parts_remaining, uploaded_parts,
            workers, rtype,
        )
        # Get the latest upload_id from progress (may have been refreshed)
        progress = _load_progress(remote_path)
        if progress and progress.get("upload_id"):
            upload_id = progress["upload_id"]

    # ── Step 3: create file ───────────────────────────────────────
    result = api.create_file(
        remote_path=remote_path,
        size=file_size,
        isdir=0,
        upload_id=upload_id,
        block_list=hashes.block_list,
        rtype=rtype,
    )
    _clear_progress(remote_path)
    log.info("Upload complete: %s -> %s", local_path, remote_path)
    return result


def _upload_slices_with_refresh(api, local_path, remote_path, file_size,
                                chunk_size, hashes, upload_id,
                                parts_remaining, uploaded_parts,
                                workers, rtype):
    """Upload slices, automatically refreshing the upload session on 400 errors.

    When the Baidu API returns 400 for upload_slice (session expired),
    this function re-precreates to get a new uploadid and continues
    uploading the remaining slices.
    """
    current_upload_id = upload_id
    progress_lock = threading.Lock()
    session_refreshes = 0

    total_bytes = sum(
        min(chunk_size, file_size - i * chunk_size) for i in parts_remaining
    )

    with ProgressBar(file_size, desc=f"Uploading {os.path.basename(local_path)}") as pbar:
        # Show already-uploaded progress
        already_bytes = sum(
            min(chunk_size, file_size - i * chunk_size)
            for i in uploaded_parts
        )
        if already_bytes > 0:
            pbar.update(already_bytes)

        while parts_remaining:
            failed_parts = []
            batch_success = True

            def _upload_one(partseq: int) -> int:
                offset = partseq * chunk_size
                length = min(chunk_size, file_size - offset)
                with open(local_path, "rb") as f:
                    f.seek(offset)
                    data = f.read(length)
                api.upload_slice(current_upload_id, remote_path, partseq, data)
                pbar.update(length)
                return partseq

            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(_upload_one, seq): seq
                        for seq in parts_remaining
                    }
                    for future in as_completed(futures):
                        try:
                            seq = future.result()
                            with progress_lock:
                                uploaded_parts.add(seq)
                                _save_progress(remote_path, {
                                    "upload_id": current_upload_id,
                                    "uploaded_parts": sorted(uploaded_parts),
                                    "chunk_size": chunk_size,
                                })
                        except requests.HTTPError as e:
                            seq = futures[future]
                            status = e.response.status_code if e.response is not None else 0
                            if status == 400:
                                failed_parts.append(seq)
                                batch_success = False
                            else:
                                raise
                        except (requests.ConnectionError, requests.Timeout,
                                ConnectionError, OSError) as e:
                            seq = futures[future]
                            log.warning("Slice %d failed with connection error: %s", seq, e)
                            failed_parts.append(seq)
                            batch_success = False
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 400:
                    batch_success = False
                else:
                    raise
            except (requests.ConnectionError, requests.Timeout,
                    ConnectionError, OSError) as e:
                log.warning("Batch failed with connection error: %s", e)
                batch_success = False

            if batch_success:
                break  # all done

            # Determine which parts still need uploading
            parts_remaining = [
                i for i in range(len(hashes.block_list))
                if i not in uploaded_parts
            ]

            # Check if any parts were 400 errors (session expired)
            has_400 = any(
                isinstance(e, requests.HTTPError) and
                getattr(e, 'response', None) is not None and
                e.response.status_code == 400
                for e in []  # 400s are tracked via failed_parts from HTTPError handler
            )

            # Refresh session on 400 errors; just retry on connection errors
            session_refreshes += 1
            if session_refreshes > MAX_SESSION_REFRESHES:
                _save_progress(remote_path, {
                    "upload_id": current_upload_id,
                    "uploaded_parts": sorted(uploaded_parts),
                    "chunk_size": chunk_size,
                })
                raise RuntimeError(
                    f"Upload failed after {MAX_SESSION_REFRESHES} retries, giving up. "
                    f"Progress saved ({len(uploaded_parts)}/{len(hashes.block_list)} slices). "
                    f"Re-run the command to resume."
                )

            log.warning(
                "%d slices failed. Retrying... (%d/%d slices done, %d remaining)",
                len(failed_parts), len(uploaded_parts),
                len(hashes.block_list), len(parts_remaining),
            )

            # Re-precreate to get a fresh upload session
            try:
                pre = api.precreate(
                    remote_path=remote_path,
                    size=file_size,
                    isdir=0,
                    block_list=hashes.block_list,
                    content_md5=hashes.content_md5,
                    slice_md5=hashes.slice_md5,
                    rtype=rtype,
                )
                current_upload_id = pre["uploadid"]
                log.info("New upload session obtained, continuing upload...")
            except (requests.RequestException, Exception) as e:
                log.warning("Failed to refresh session: %s, reusing old session", e)


def upload_dir(api: BaiduPanAPI, local_dir: str, remote_dir: str,
               workers: int = None, rtype: int = 3):
    """Recursively upload a directory."""
    local_dir = os.path.abspath(local_dir)
    results = []

    for root, dirs, files in os.walk(local_dir):
        rel = os.path.relpath(root, local_dir)
        if rel == ".":
            cur_remote = remote_dir
        else:
            cur_remote = remote_dir + "/" + rel.replace(os.sep, "/")

        # create remote directory
        try:
            api.mkdir(cur_remote)
        except Exception:
            pass  # may already exist

        for fname in files:
            local_path = os.path.join(root, fname)
            rpath = cur_remote + "/" + fname
            result = upload_file(api, local_path, rpath, workers=workers, rtype=rtype)
            results.append(result)

    return results
