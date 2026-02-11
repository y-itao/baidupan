"""Tests for baidupan.uploader."""

import json
import os
from unittest.mock import MagicMock, patch, call

import pytest

from baidupan import config
from baidupan.hasher import FileHashes
from baidupan.uploader import (
    _clear_progress,
    _load_progress,
    _progress_file,
    _save_progress,
    upload_dir,
    upload_file,
)


@pytest.fixture
def mock_api():
    api = MagicMock()
    api.precreate.return_value = {
        "errno": 0,
        "return_type": 1,
        "uploadid": "upload_123",
        "block_list": [0],
    }
    api.upload_slice.return_value = {"md5": "slicemd5"}
    api.create_file.return_value = {"errno": 0, "path": "/apps/bypy/test.txt"}
    api.mkdir.return_value = {"errno": 0}
    return api


class TestProgressPersistence:
    def test_progress_file_path(self):
        path = _progress_file("/apps/bypy/test.txt")
        assert path.endswith("apps_bypy_test.txt.json")

    def test_save_and_load(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "UPLOAD_PROGRESS_DIR", str(tmp_path))
        _save_progress("/test", {"upload_id": "u1", "uploaded_parts": [0, 1]})
        loaded = _load_progress("/test")
        assert loaded["upload_id"] == "u1"
        assert loaded["uploaded_parts"] == [0, 1]

    def test_load_nonexistent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "UPLOAD_PROGRESS_DIR", str(tmp_path))
        assert _load_progress("/nonexistent") is None

    def test_clear(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "UPLOAD_PROGRESS_DIR", str(tmp_path))
        _save_progress("/test", {"data": 1})
        _clear_progress("/test")
        assert _load_progress("/test") is None


class TestUploadFile:
    @patch("baidupan.uploader.compute_hashes")
    @patch("baidupan.uploader._clear_progress")
    @patch("baidupan.uploader._save_progress")
    @patch("baidupan.uploader._load_progress", return_value=None)
    def test_rapid_upload(self, mock_lp, mock_sp, mock_cp, mock_hash, mock_api, tmp_path):
        """Test that rapid upload (return_type=2) skips slice upload."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        mock_hash.return_value = FileHashes("cmd5", "smd5", ["bmd5"], len("hello world"))
        mock_api.precreate.return_value = {"errno": 0, "return_type": 2}

        result = upload_file(mock_api, str(test_file), "/apps/bypy/test.txt")

        mock_api.upload_slice.assert_not_called()
        mock_api.create_file.assert_not_called()
        assert result["return_type"] == 2

    @patch("baidupan.uploader.compute_hashes")
    @patch("baidupan.uploader._clear_progress")
    @patch("baidupan.uploader._save_progress")
    @patch("baidupan.uploader._load_progress", return_value=None)
    def test_normal_upload(self, mock_lp, mock_sp, mock_cp, mock_hash, mock_api, tmp_path):
        """Test normal chunked upload flow."""
        test_file = tmp_path / "test.txt"
        data = b"x" * 1000
        test_file.write_bytes(data)

        mock_hash.return_value = FileHashes("cmd5", "smd5", ["bmd5"], len(data))

        result = upload_file(mock_api, str(test_file), "/apps/bypy/test.txt", workers=1)

        mock_api.precreate.assert_called_once()
        mock_api.upload_slice.assert_called_once()
        mock_api.create_file.assert_called_once()

    @patch("baidupan.uploader.compute_hashes")
    @patch("baidupan.uploader._clear_progress")
    @patch("baidupan.uploader._save_progress")
    @patch("baidupan.uploader._load_progress")
    def test_resume_upload(self, mock_lp, mock_sp, mock_cp, mock_hash, mock_api, tmp_path):
        """Test that already-uploaded slices are skipped."""
        test_file = tmp_path / "test.txt"
        data = b"x" * (5 * 1024 * 1024)  # 5MB = 2 blocks
        test_file.write_bytes(data)

        mock_hash.return_value = FileHashes("cmd5", "smd5", ["b0", "b1"], len(data))

        # Simulate first block already uploaded
        mock_lp.return_value = {"upload_id": "upload_123", "uploaded_parts": [0]}

        # precreate says both blocks needed
        mock_api.precreate.return_value = {
            "errno": 0,
            "return_type": 1,
            "uploadid": "upload_123",
            "block_list": [0, 1],
        }

        result = upload_file(mock_api, str(test_file), "/apps/bypy/test.txt", workers=1)

        # Only slice 1 should be uploaded (slice 0 was resumed)
        assert mock_api.upload_slice.call_count == 1
        call_args = mock_api.upload_slice.call_args
        assert call_args[0][2] == 1  # partseq=1


class TestUploadDir:
    @patch("baidupan.uploader.upload_file")
    def test_upload_dir(self, mock_upload_file, mock_api, tmp_path):
        """Test recursive directory upload."""
        # Create a directory structure
        (tmp_path / "sub").mkdir()
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "sub" / "file2.txt").write_text("world")

        mock_upload_file.return_value = {"errno": 0}

        results = upload_dir(mock_api, str(tmp_path), "/apps/bypy/testdir")

        assert mock_upload_file.call_count == 2
        assert len(results) == 2
        # mkdir should be called for root and sub
        assert mock_api.mkdir.call_count >= 1
