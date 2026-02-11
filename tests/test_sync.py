"""Tests for baidupan.sync."""

import os
from unittest.mock import MagicMock, patch, call

import pytest

from baidupan import config
from baidupan.sync import _gather_local, compare, sync_down, sync_up


class TestGatherLocal:
    def test_empty_dir(self, tmp_path):
        result = _gather_local(str(tmp_path))
        assert result == {}

    def test_flat_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbbb")
        result = _gather_local(str(tmp_path))
        assert "a.txt" in result
        assert "b.txt" in result
        assert result["a.txt"]["size"] == 3
        assert result["b.txt"]["size"] == 4
        assert "local_path" in result["a.txt"]

    def test_nested_files(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.txt").write_text("ccc")
        result = _gather_local(str(tmp_path))
        assert "sub/c.txt" in result


class TestCompare:
    def _mock_api(self, remote_files):
        api = MagicMock()
        api.list_all.return_value = {"errno": 0, "list": remote_files}
        return api

    def test_all_same(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"aaa")

        api = self._mock_api([
            {"path": "/apps/bypy/test/a.txt", "size": 3, "fs_id": 1, "isdir": 0, "server_mtime": 100},
        ])

        diff = compare(api, str(tmp_path), "/apps/bypy/test")
        assert diff["same"] == ["a.txt"]
        assert diff["local_only"] == []
        assert diff["remote_only"] == []
        assert diff["different"] == []

    def test_local_only(self, tmp_path):
        (tmp_path / "local.txt").write_text("local")

        api = self._mock_api([])
        diff = compare(api, str(tmp_path), "/apps/bypy/test")
        assert diff["local_only"] == ["local.txt"]
        assert diff["remote_only"] == []

    def test_remote_only(self, tmp_path):
        api = self._mock_api([
            {"path": "/apps/bypy/test/remote.txt", "size": 5, "fs_id": 1, "isdir": 0},
        ])
        diff = compare(api, str(tmp_path), "/apps/bypy/test")
        assert diff["remote_only"] == ["remote.txt"]
        assert diff["local_only"] == []

    def test_different_size(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"aaa")  # size 3

        api = self._mock_api([
            {"path": "/apps/bypy/test/a.txt", "size": 10, "fs_id": 1, "isdir": 0},
        ])
        diff = compare(api, str(tmp_path), "/apps/bypy/test")
        assert diff["different"] == ["a.txt"]
        assert diff["same"] == []

    def test_mixed(self, tmp_path):
        (tmp_path / "same.txt").write_bytes(b"xxx")
        (tmp_path / "diff.txt").write_bytes(b"aaa")
        (tmp_path / "local.txt").write_bytes(b"l")

        api = self._mock_api([
            {"path": "/apps/bypy/test/same.txt", "size": 3, "fs_id": 1, "isdir": 0},
            {"path": "/apps/bypy/test/diff.txt", "size": 999, "fs_id": 2, "isdir": 0},
            {"path": "/apps/bypy/test/remote.txt", "size": 5, "fs_id": 3, "isdir": 0},
        ])
        diff = compare(api, str(tmp_path), "/apps/bypy/test")
        assert diff["same"] == ["same.txt"]
        assert diff["different"] == ["diff.txt"]
        assert diff["local_only"] == ["local.txt"]
        assert diff["remote_only"] == ["remote.txt"]

    def test_ignores_dirs(self, tmp_path):
        api = self._mock_api([
            {"path": "/apps/bypy/test/subdir", "size": 0, "fs_id": 1, "isdir": 1},
        ])
        diff = compare(api, str(tmp_path), "/apps/bypy/test")
        assert diff["remote_only"] == []


class TestSyncUp:
    @patch("baidupan.sync.upload_file")
    @patch("baidupan.sync.compare")
    def test_uploads_local_only_and_different(self, mock_compare, mock_upload, tmp_path):
        mock_compare.return_value = {
            "local_only": ["new.txt"],
            "remote_only": [],
            "different": ["changed.txt"],
            "same": ["same.txt"],
            "_local": {
                "new.txt": {"local_path": str(tmp_path / "new.txt"), "size": 10},
                "changed.txt": {"local_path": str(tmp_path / "changed.txt"), "size": 20},
            },
            "_remote": {},
        }

        api = MagicMock()
        sync_up(api, str(tmp_path), "/testdir")

        assert mock_upload.call_count == 2

    @patch("baidupan.sync.upload_file")
    @patch("baidupan.sync.compare")
    def test_delete_extra(self, mock_compare, mock_upload):
        mock_compare.return_value = {
            "local_only": [],
            "remote_only": ["old.txt"],
            "different": [],
            "same": [],
            "_local": {},
            "_remote": {
                "old.txt": {"remote_path": "/apps/bypy/test/old.txt", "fs_id": 1},
            },
        }

        api = MagicMock()
        sync_up(api, "/local", "/testdir", delete_extra=True)

        api.file_manager.assert_called_once_with("delete", ["/apps/bypy/test/old.txt"])

    @patch("baidupan.sync.upload_file")
    @patch("baidupan.sync.compare")
    def test_no_delete_by_default(self, mock_compare, mock_upload):
        mock_compare.return_value = {
            "local_only": [],
            "remote_only": ["extra.txt"],
            "different": [],
            "same": [],
            "_local": {},
            "_remote": {"extra.txt": {"remote_path": "/apps/bypy/test/extra.txt"}},
        }

        api = MagicMock()
        sync_up(api, "/local", "/testdir", delete_extra=False)

        api.file_manager.assert_not_called()


class TestSyncDown:
    @patch("baidupan.sync.download_file")
    @patch("baidupan.sync.compare")
    def test_downloads_remote_only_and_different(self, mock_compare, mock_download, tmp_path):
        mock_compare.return_value = {
            "local_only": [],
            "remote_only": ["new.txt"],
            "different": ["changed.txt"],
            "same": ["same.txt"],
            "_local": {},
            "_remote": {
                "new.txt": {"remote_path": "/apps/bypy/test/new.txt", "size": 10, "fs_id": 1},
                "changed.txt": {"remote_path": "/apps/bypy/test/changed.txt", "size": 20, "fs_id": 2},
            },
        }

        api = MagicMock()
        sync_down(api, "/testdir", str(tmp_path))

        assert mock_download.call_count == 2

    @patch("baidupan.sync.download_file")
    @patch("baidupan.sync.compare")
    def test_delete_local_extra(self, mock_compare, mock_download, tmp_path):
        extra_file = tmp_path / "extra.txt"
        extra_file.write_text("delete me")

        mock_compare.return_value = {
            "local_only": ["extra.txt"],
            "remote_only": [],
            "different": [],
            "same": [],
            "_local": {
                "extra.txt": {"local_path": str(extra_file), "size": 9},
            },
            "_remote": {},
        }

        api = MagicMock()
        sync_down(api, "/testdir", str(tmp_path), delete_extra=True)

        assert not extra_file.exists()
