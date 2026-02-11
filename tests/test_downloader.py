"""Tests for baidupan.downloader."""

import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from baidupan import config
from baidupan.downloader import (
    _clear_progress,
    _load_progress,
    _progress_file,
    _save_progress,
    download_by_meta,
    download_dir,
    download_file,
)


@pytest.fixture
def mock_api():
    api = MagicMock()
    api.get_download_link.return_value = "https://d.pcs.baidu.com/dl/test"

    # Create a mock response that yields data
    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = [b"hello", b" world"]
    mock_resp.raise_for_status = MagicMock()
    api.download_stream.return_value = mock_resp

    return api


class TestProgressPersistence:
    def test_progress_file_path(self):
        path = _progress_file("/apps/bypy/test.txt")
        assert path.endswith("apps_bypy_test.txt.json")

    def test_save_and_load(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DOWNLOAD_PROGRESS_DIR", str(tmp_path))
        _save_progress("/test", {"completed_segments": [0, 1]})
        loaded = _load_progress("/test")
        assert loaded["completed_segments"] == [0, 1]

    def test_load_nonexistent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DOWNLOAD_PROGRESS_DIR", str(tmp_path))
        assert _load_progress("/missing") is None

    def test_clear(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DOWNLOAD_PROGRESS_DIR", str(tmp_path))
        _save_progress("/test", {"data": 1})
        _clear_progress("/test")
        assert _load_progress("/test") is None


class TestDownloadFile:
    def test_simple_download(self, mock_api, tmp_path):
        local_path = str(tmp_path / "out.txt")

        result = download_file(
            mock_api, fs_id=123, remote_path="/apps/bypy/test.txt",
            local_path=local_path, file_size=11,
        )

        assert result == local_path
        assert os.path.exists(local_path)
        with open(local_path, "rb") as f:
            assert f.read() == b"hello world"

    def test_tmp_file_cleaned_up(self, mock_api, tmp_path):
        local_path = str(tmp_path / "out.txt")
        tmp_file = local_path + ".baidupan.tmp"

        download_file(
            mock_api, fs_id=123, remote_path="/apps/bypy/test.txt",
            local_path=local_path, file_size=11,
        )

        assert not os.path.exists(tmp_file)
        assert os.path.exists(local_path)

    def test_resume_from_partial(self, mock_api, tmp_path):
        local_path = str(tmp_path / "out.txt")
        tmp_file = local_path + ".baidupan.tmp"

        # Create a partial download
        with open(tmp_file, "wb") as f:
            f.write(b"hello")

        # Mock the remaining download
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b" world"]
        mock_resp.raise_for_status = MagicMock()
        mock_api.download_stream.return_value = mock_resp

        result = download_file(
            mock_api, fs_id=123, remote_path="/apps/bypy/test.txt",
            local_path=local_path, file_size=11,
        )

        assert os.path.exists(local_path)
        with open(local_path, "rb") as f:
            content = f.read()
        assert content == b"hello world"

        # Check Range header was sent
        call_args = mock_api.download_stream.call_args
        assert "Range" in call_args[1].get("headers", call_args[0][1] if len(call_args[0]) > 1 else {})

    def test_already_complete_tmp(self, mock_api, tmp_path):
        """If tmp file is >= expected size, rename directly."""
        local_path = str(tmp_path / "out.txt")
        tmp_file = local_path + ".baidupan.tmp"

        with open(tmp_file, "wb") as f:
            f.write(b"hello world")

        result = download_file(
            mock_api, fs_id=123, remote_path="/apps/bypy/test.txt",
            local_path=local_path, file_size=11,
        )

        assert os.path.exists(local_path)
        # Should NOT have called download_stream (already complete)
        mock_api.download_stream.assert_not_called()

    def test_creates_parent_dirs(self, mock_api, tmp_path):
        local_path = str(tmp_path / "sub" / "dir" / "out.txt")

        download_file(
            mock_api, fs_id=123, remote_path="/apps/bypy/test.txt",
            local_path=local_path, file_size=11,
        )

        assert os.path.exists(local_path)


class TestDownloadByMeta:
    def test_download_by_meta(self, mock_api, tmp_path):
        local_path = str(tmp_path / "out.txt")
        meta = {
            "fs_id": 456,
            "path": "/apps/bypy/meta.txt",
            "size": 11,
        }

        with patch("baidupan.downloader.download_file") as mock_dl:
            mock_dl.return_value = local_path
            result = download_by_meta(mock_api, meta, local_path)
            mock_dl.assert_called_once_with(
                mock_api, fs_id=456, remote_path="/apps/bypy/meta.txt",
                local_path=local_path, file_size=11,
                concurrent=False, workers=None, segment_size=None,
            )


class TestDownloadDir:
    def test_download_dir(self, mock_api, tmp_path):
        mock_api.list_all.return_value = {
            "errno": 0,
            "list": [
                {"path": "/apps/bypy/dir/a.txt", "size": 5, "fs_id": 1, "isdir": 0},
                {"path": "/apps/bypy/dir/sub/b.txt", "size": 6, "fs_id": 2, "isdir": 0},
                {"path": "/apps/bypy/dir/sub", "size": 0, "fs_id": 3, "isdir": 1},
            ],
        }

        with patch("baidupan.downloader.download_file") as mock_dl:
            mock_dl.return_value = "ok"
            result = download_dir(mock_api, "/apps/bypy/dir", str(tmp_path))

        # Only files, not dirs
        assert mock_dl.call_count == 2
        assert len(result) == 2
