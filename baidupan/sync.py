"""Bidirectional sync: compare / sync_up / sync_down."""

import hashlib
import logging
import os

from . import config
from .api import BaiduPanAPI
from .downloader import download_file
from .uploader import upload_file

log = logging.getLogger(__name__)


def _local_file_md5(filepath: str) -> str:
    """Compute MD5 of a local file (for comparison)."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _gather_local(local_dir: str) -> dict[str, dict]:
    """Build a dict of relative_path -> {size, mtime, md5?} for local files."""
    local_dir = os.path.abspath(local_dir)
    result = {}
    for root, _dirs, files in os.walk(local_dir):
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, local_dir).replace(os.sep, "/")
            stat = os.stat(full)
            result[rel] = {
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "local_path": full,
            }
    return result


def _gather_remote(api: BaiduPanAPI, remote_dir: str) -> dict[str, dict]:
    """Build a dict of relative_path -> {size, mtime, fs_id, md5} for remote files."""
    try:
        resp = api.list_all(remote_dir)
    except Exception as e:
        # Remote directory may not exist yet (e.g. first sync)
        log.info("Remote dir %s not listed (%s), treating as empty", remote_dir, e)
        return {}
    items = resp.get("list", [])
    result = {}
    for item in items:
        if item.get("isdir"):
            continue
        rel = item["path"][len(remote_dir):].lstrip("/")
        result[rel] = {
            "size": item["size"],
            "mtime": item.get("server_mtime", 0),
            "fs_id": item["fs_id"],
            "md5": item.get("md5", ""),
            "remote_path": item["path"],
        }
    return result


def compare(api: BaiduPanAPI, local_dir: str, remote_dir: str) -> dict:
    """Compare local and remote directories.

    Returns
    -------
    dict with keys:
        local_only: files only on local
        remote_only: files only on remote
        different: files that exist on both sides but differ
        same: files that match
    """
    remote_dir = remote_dir.rstrip("/")
    local_files = _gather_local(local_dir)
    remote_files = _gather_remote(api, remote_dir)

    local_keys = set(local_files.keys())
    remote_keys = set(remote_files.keys())

    local_only = sorted(local_keys - remote_keys)
    remote_only = sorted(remote_keys - local_keys)
    common = local_keys & remote_keys

    different = []
    same = []
    for rel in sorted(common):
        lf = local_files[rel]
        rf = remote_files[rel]
        if lf["size"] != rf["size"]:
            different.append(rel)
        else:
            same.append(rel)

    return {
        "local_only": local_only,
        "remote_only": remote_only,
        "different": different,
        "same": same,
        "_local": local_files,
        "_remote": remote_files,
    }


def sync_up(api: BaiduPanAPI, local_dir: str, remote_dir: str,
            workers: int = None, rtype: int = 3, delete_extra: bool = False):
    """Sync local directory up to remote (local is source of truth).

    Uploads new and changed files. Optionally deletes remote-only files.
    """
    if not remote_dir.startswith(config.REMOTE_ROOT):
        remote_dir = config.REMOTE_ROOT + ("/" + remote_dir.lstrip("/"))
    remote_dir = remote_dir.rstrip("/")

    diff = compare(api, local_dir, remote_dir)
    local_files = diff["_local"]

    # ensure remote root exists
    try:
        api.mkdir(remote_dir)
    except Exception:
        pass

    # upload new + changed
    to_upload = diff["local_only"] + diff["different"]
    for rel in to_upload:
        lf = local_files[rel]
        rpath = remote_dir + "/" + rel

        # ensure parent dir
        parent = "/".join(rpath.rsplit("/", 1)[:-1])
        if parent and parent != remote_dir:
            try:
                api.mkdir(parent)
            except Exception:
                pass

        upload_file(api, lf["local_path"], rpath, workers=workers, rtype=rtype)
        print(f"  Uploaded: {rel}")

    # optionally delete remote-only
    if delete_extra and diff["remote_only"]:
        remote_files = diff["_remote"]
        for rel in diff["remote_only"]:
            rf = remote_files[rel]
            api.file_manager("delete", [rf["remote_path"]])
            print(f"  Deleted remote: {rel}")

    print(f"\nSync up complete: {len(to_upload)} uploaded, "
          f"{len(diff['same'])} unchanged, "
          f"{len(diff['remote_only'])} remote-only")


def sync_down(api: BaiduPanAPI, remote_dir: str, local_dir: str,
              concurrent: bool = False, workers: int = None,
              delete_extra: bool = False):
    """Sync remote directory down to local (remote is source of truth).

    Downloads new and changed files. Optionally deletes local-only files.
    """
    if not remote_dir.startswith(config.REMOTE_ROOT):
        remote_dir = config.REMOTE_ROOT + ("/" + remote_dir.lstrip("/"))
    remote_dir = remote_dir.rstrip("/")

    diff = compare(api, local_dir, remote_dir)
    remote_files = diff["_remote"]

    os.makedirs(local_dir, exist_ok=True)

    # download new + changed
    to_download = diff["remote_only"] + diff["different"]
    for rel in to_download:
        rf = remote_files[rel]
        local_path = os.path.join(local_dir, rel)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)

        download_file(
            api,
            fs_id=rf["fs_id"],
            remote_path=rf["remote_path"],
            local_path=local_path,
            file_size=rf["size"],
            concurrent=concurrent,
            workers=workers,
        )
        print(f"  Downloaded: {rel}")

    # optionally delete local-only
    if delete_extra and diff["local_only"]:
        local_files = diff["_local"]
        for rel in diff["local_only"]:
            lf = local_files[rel]
            os.remove(lf["local_path"])
            print(f"  Deleted local: {rel}")

    print(f"\nSync down complete: {len(to_download)} downloaded, "
          f"{len(diff['same'])} unchanged, "
          f"{len(diff['local_only'])} local-only")
