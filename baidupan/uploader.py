"""Upload: rapid upload (秒传) + chunked concurrent upload + resume."""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config
from .api import BaiduPanAPI
from .hasher import compute_hashes
from .utils import ProgressBar

log = logging.getLogger(__name__)


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

    Parameters
    ----------
    api : BaiduPanAPI
    local_path : str  – absolute local file path
    remote_path : str – absolute remote path (already under REMOTE_ROOT)
    workers : int – concurrent upload workers
    rtype : int – rename policy (3 = rename on conflict)

    Returns
    -------
    dict – create file API response
    """
    workers = workers or config.MAX_UPLOAD_WORKERS
    file_size = os.path.getsize(local_path)

    # compute hashes (single-pass, cached)
    hashes = compute_hashes(local_path)

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
    if progress and progress.get("upload_id") == upload_id:
        uploaded_parts = set(progress.get("uploaded_parts", []))
        log.info("Resuming upload: %d/%d slices already uploaded",
                 len(uploaded_parts), len(hashes.block_list))

    parts_to_upload = [i for i in block_list_need if i not in uploaded_parts]

    if not parts_to_upload:
        log.info("All slices already uploaded, creating file...")
    else:
        chunk_size = config.UPLOAD_CHUNK_SIZE
        total_bytes = sum(
            min(chunk_size, file_size - i * chunk_size) for i in parts_to_upload
        )

        with ProgressBar(total_bytes, desc=f"Uploading {os.path.basename(local_path)}") as pbar:
            def _upload_one(partseq: int) -> int:
                offset = partseq * chunk_size
                length = min(chunk_size, file_size - offset)
                with open(local_path, "rb") as f:
                    f.seek(offset)
                    data = f.read(length)
                api.upload_slice(upload_id, remote_path, partseq, data)
                pbar.update(length)
                return partseq

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_upload_one, seq): seq for seq in parts_to_upload}
                for future in as_completed(futures):
                    seq = future.result()  # raises on error
                    uploaded_parts.add(seq)
                    # persist progress after each slice
                    _save_progress(remote_path, {
                        "upload_id": upload_id,
                        "uploaded_parts": sorted(uploaded_parts),
                    })

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
