"""MD5 computation with disk caching.

For rapid upload, Baidu requires:
- content_md5: MD5 of the entire file
- slice_md5: MD5 of the first 256 KB
- block_list: list of MD5s for each 4 MB chunk

All three are computed in a single pass over the file.
"""

import hashlib
import json
import logging
import os

from . import config

log = logging.getLogger(__name__)


def _cache_key(filepath: str, mtime: float, size: int, chunk_size: int) -> str:
    return f"{filepath}|{mtime}|{size}|{chunk_size}"


def _load_cache() -> dict:
    if os.path.exists(config.HASH_CACHE_FILE):
        try:
            with open(config.HASH_CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(config.HASH_CACHE_FILE), exist_ok=True)
    with open(config.HASH_CACHE_FILE, "w") as f:
        json.dump(cache, f)


class FileHashes:
    """Holds all hashes needed for upload."""

    __slots__ = ("content_md5", "slice_md5", "block_list", "file_size")

    def __init__(self, content_md5: str, slice_md5: str, block_list: list[str], file_size: int):
        self.content_md5 = content_md5
        self.slice_md5 = slice_md5
        self.block_list = block_list
        self.file_size = file_size

    def to_dict(self) -> dict:
        return {
            "content_md5": self.content_md5,
            "slice_md5": self.slice_md5,
            "block_list": self.block_list,
            "file_size": self.file_size,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileHashes":
        return cls(d["content_md5"], d["slice_md5"], d["block_list"], d["file_size"])


def compute_hashes(filepath: str, use_cache: bool = True,
                   chunk_size: int = None) -> FileHashes:
    """Compute content_md5, slice_md5, and block_list in a single read pass.

    Results are cached by (filepath, mtime, size, chunk_size) to avoid recomputation.
    chunk_size controls the block_list granularity (default: config.UPLOAD_CHUNK_SIZE).
    """
    if chunk_size is None:
        chunk_size = config.UPLOAD_CHUNK_SIZE
    stat = os.stat(filepath)
    size = stat.st_size
    mtime = stat.st_mtime
    key = _cache_key(filepath, mtime, size, chunk_size)

    if use_cache:
        cache = _load_cache()
        if key in cache:
            log.debug("Hash cache hit for %s", filepath)
            return FileHashes.from_dict(cache[key])
    else:
        cache = {}

    log.debug("Computing hashes for %s (%d bytes)", filepath, size)

    content_hasher = hashlib.md5()
    slice_hasher = hashlib.md5()
    block_list: list[str] = []

    slice_limit = 256 * 1024  # first 256 KB for slice_md5
    bytes_read = 0
    block_hasher = hashlib.md5()
    block_bytes = 0

    with open(filepath, "rb") as f:
        while True:
            data = f.read(65536)  # 64 KB read buffer
            if not data:
                break

            content_hasher.update(data)

            # slice_md5: first 256 KB
            if bytes_read < slice_limit:
                end = min(len(data), slice_limit - bytes_read)
                slice_hasher.update(data[:end])

            # block_list: each 4 MB chunk
            remaining = data
            while remaining:
                can_take = min(len(remaining), chunk_size - block_bytes)
                block_hasher.update(remaining[:can_take])
                block_bytes += can_take
                remaining = remaining[can_take:]

                if block_bytes >= chunk_size:
                    block_list.append(block_hasher.hexdigest())
                    block_hasher = hashlib.md5()
                    block_bytes = 0

            bytes_read += len(data)

    # flush last partial block
    if block_bytes > 0:
        block_list.append(block_hasher.hexdigest())

    result = FileHashes(
        content_md5=content_hasher.hexdigest(),
        slice_md5=slice_hasher.hexdigest(),
        block_list=block_list,
        file_size=size,
    )

    # update cache
    cache[key] = result.to_dict()
    _save_cache(cache)

    return result
