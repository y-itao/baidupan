"""Tests for baidupan.hasher."""

import hashlib
import json
import os
import tempfile

import pytest

from baidupan import config
from baidupan.hasher import FileHashes, compute_hashes


@pytest.fixture
def small_file(tmp_path):
    """Create a small file (< 256KB, single block)."""
    p = tmp_path / "small.bin"
    data = b"hello world" * 100  # 1100 bytes
    p.write_bytes(data)
    return str(p), data


@pytest.fixture
def medium_file(tmp_path):
    """Create a file > 256KB but < 4MB (single block, has slice)."""
    p = tmp_path / "medium.bin"
    data = os.urandom(300 * 1024)  # 300 KB
    p.write_bytes(data)
    return str(p), data


@pytest.fixture
def large_file(tmp_path):
    """Create a file > 4MB (multiple blocks)."""
    p = tmp_path / "large.bin"
    data = os.urandom(5 * 1024 * 1024)  # 5 MB
    p.write_bytes(data)
    return str(p), data


class TestFileHashes:
    def test_to_dict_from_dict(self):
        fh = FileHashes("aaa", "bbb", ["ccc", "ddd"], 12345)
        d = fh.to_dict()
        assert d == {
            "content_md5": "aaa",
            "slice_md5": "bbb",
            "block_list": ["ccc", "ddd"],
            "file_size": 12345,
        }
        fh2 = FileHashes.from_dict(d)
        assert fh2.content_md5 == "aaa"
        assert fh2.slice_md5 == "bbb"
        assert fh2.block_list == ["ccc", "ddd"]
        assert fh2.file_size == 12345


class TestComputeHashes:
    def test_small_file(self, small_file, monkeypatch, tmp_path):
        filepath, data = small_file
        cache_file = str(tmp_path / "hash_cache.json")
        monkeypatch.setattr(config, "HASH_CACHE_FILE", cache_file)

        h = compute_hashes(filepath, use_cache=False)

        # content_md5 = MD5 of entire file
        assert h.content_md5 == hashlib.md5(data).hexdigest()

        # slice_md5 = MD5 of first 256KB (which is the whole file here)
        assert h.slice_md5 == hashlib.md5(data[:256*1024]).hexdigest()

        # For a file < 4MB, there is exactly 1 block
        assert len(h.block_list) == 1
        assert h.block_list[0] == hashlib.md5(data).hexdigest()

        assert h.file_size == len(data)

    def test_medium_file(self, medium_file, monkeypatch, tmp_path):
        filepath, data = medium_file
        cache_file = str(tmp_path / "hash_cache.json")
        monkeypatch.setattr(config, "HASH_CACHE_FILE", cache_file)

        h = compute_hashes(filepath, use_cache=False)

        assert h.content_md5 == hashlib.md5(data).hexdigest()
        assert h.slice_md5 == hashlib.md5(data[:256*1024]).hexdigest()
        assert len(h.block_list) == 1
        assert h.file_size == len(data)

    def test_large_file_multiple_blocks(self, large_file, monkeypatch, tmp_path):
        filepath, data = large_file
        cache_file = str(tmp_path / "hash_cache.json")
        monkeypatch.setattr(config, "HASH_CACHE_FILE", cache_file)

        h = compute_hashes(filepath, use_cache=False)

        assert h.content_md5 == hashlib.md5(data).hexdigest()
        assert h.slice_md5 == hashlib.md5(data[:256*1024]).hexdigest()

        # 5MB / 4MB = 2 blocks (4MB + 1MB)
        chunk_size = config.UPLOAD_CHUNK_SIZE
        assert len(h.block_list) == 2
        assert h.block_list[0] == hashlib.md5(data[:chunk_size]).hexdigest()
        assert h.block_list[1] == hashlib.md5(data[chunk_size:]).hexdigest()

        assert h.file_size == len(data)

    def test_cache_hit(self, small_file, monkeypatch, tmp_path):
        filepath, data = small_file
        cache_file = str(tmp_path / "hash_cache.json")
        monkeypatch.setattr(config, "HASH_CACHE_FILE", cache_file)

        # first call populates cache
        h1 = compute_hashes(filepath, use_cache=True)

        # second call should hit cache
        h2 = compute_hashes(filepath, use_cache=True)

        assert h1.content_md5 == h2.content_md5
        assert h1.slice_md5 == h2.slice_md5
        assert h1.block_list == h2.block_list

        # verify cache file exists
        assert os.path.exists(cache_file)
        with open(cache_file) as f:
            cache = json.load(f)
        assert len(cache) == 1

    def test_empty_file(self, tmp_path, monkeypatch):
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        cache_file = str(tmp_path / "hash_cache.json")
        monkeypatch.setattr(config, "HASH_CACHE_FILE", cache_file)

        h = compute_hashes(str(p), use_cache=False)
        assert h.content_md5 == hashlib.md5(b"").hexdigest()
        assert h.slice_md5 == hashlib.md5(b"").hexdigest()
        assert h.block_list == [hashlib.md5(b"").hexdigest()]  # one empty block for Baidu API compatibility
        assert h.file_size == 0
