"""Tests for concurrent download path in baidupan.downloader."""

import os
from unittest.mock import MagicMock, patch

import pytest

from baidupan import config
from baidupan.downloader import download_file, _download_concurrent


@pytest.fixture
def mock_api():
    api = MagicMock()
    api.get_download_link.return_value = "https://d.pcs.baidu.com/dl/test"

    def make_resp(data_chunks):
        resp = MagicMock()
        resp.iter_content.return_value = data_chunks
        resp.raise_for_status = MagicMock()
        return resp

    # Return different data for each call
    api.download_stream.side_effect = lambda dlink, headers=None: make_resp([b"x" * 1024])
    return api


class TestConcurrentDownload:
    def test_falls_back_to_simple_for_small_files(self, mock_api, tmp_path):
        """Files smaller than DOWNLOAD_SEGMENT_SIZE use simple download."""
        local_path = str(tmp_path / "small.bin")
        # file_size <= DOWNLOAD_SEGMENT_SIZE => simple path
        small_size = config.DOWNLOAD_SEGMENT_SIZE

        # Reset side_effect to return proper data
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"x" * small_size]
        mock_resp.raise_for_status = MagicMock()
        mock_api.download_stream.side_effect = None
        mock_api.download_stream.return_value = mock_resp

        download_file(
            mock_api, fs_id=1, remote_path="/test",
            local_path=local_path, file_size=small_size, concurrent=True,
        )

        # Should have called download_stream once (simple path), not multiple times
        assert mock_api.download_stream.call_count == 1

    def test_concurrent_download_creates_file(self, mock_api, tmp_path, monkeypatch):
        """Concurrent download pre-allocates and writes segments."""
        # Use small segment size for testing
        monkeypatch.setattr(config, "DOWNLOAD_SEGMENT_SIZE", 1024)
        monkeypatch.setattr(config, "DOWNLOAD_PROGRESS_DIR", str(tmp_path / "progress"))

        local_path = str(tmp_path / "concurrent.bin")
        file_size = 3000  # 3 segments of 1024 bytes

        # Mock download_stream to return correct amount of data for each segment
        def mock_stream(dlink, headers=None):
            resp = MagicMock()
            # Parse Range header to determine segment size
            if headers and "Range" in headers:
                range_hdr = headers["Range"]
                parts = range_hdr.replace("bytes=", "").split("-")
                start, end = int(parts[0]), int(parts[1])
                size = end - start + 1
            else:
                size = file_size
            resp.iter_content.return_value = [b"\x00" * size]
            resp.raise_for_status = MagicMock()
            return resp

        mock_api.download_stream.side_effect = mock_stream

        download_file(
            mock_api, fs_id=1, remote_path="/apps/bypy/big.bin",
            local_path=local_path, file_size=file_size,
            concurrent=True, workers=2,
        )

        assert os.path.exists(local_path)
        assert os.path.getsize(local_path) == file_size

    def test_concurrent_download_resumes(self, mock_api, tmp_path, monkeypatch):
        """Concurrent download skips completed segments."""
        monkeypatch.setattr(config, "DOWNLOAD_SEGMENT_SIZE", 1024)
        progress_dir = str(tmp_path / "progress")
        monkeypatch.setattr(config, "DOWNLOAD_PROGRESS_DIR", progress_dir)

        local_path = str(tmp_path / "resume.bin")
        file_size = 3000  # 3 segments (> 2*1024), so concurrent path is used

        # Pre-create the tmp file
        tmp_file = local_path + ".baidupan.tmp"
        with open(tmp_file, "wb") as f:
            f.seek(file_size - 1)
            f.write(b"\0")

        # Save progress showing segments 0 and 1 are done
        import json
        os.makedirs(progress_dir, exist_ok=True)
        progress_file = os.path.join(
            progress_dir,
            "apps_bypy_resume.bin.json",
        )
        with open(progress_file, "w") as f:
            json.dump({"completed_segments": [0, 1]}, f)

        def mock_stream(dlink, headers=None):
            resp = MagicMock()
            if headers and "Range" in headers:
                parts = headers["Range"].replace("bytes=", "").split("-")
                start, end = int(parts[0]), int(parts[1])
                size = end - start + 1
            else:
                size = 1024
            resp.iter_content.return_value = [b"\x00" * size]
            resp.raise_for_status = MagicMock()
            return resp

        mock_api.download_stream.side_effect = mock_stream

        download_file(
            mock_api, fs_id=1, remote_path="/apps/bypy/resume.bin",
            local_path=local_path, file_size=file_size,
            concurrent=True, workers=1,
        )

        assert os.path.exists(local_path)
        # Only segment 2 should have been downloaded (segments 0,1 were resumed)
        # With worker-based model: 1 worker, 1 dlink call, 1 segment download
        assert mock_api.download_stream.call_count == 1
        assert mock_api.get_download_link.call_count == 1

    def test_worker_based_dlink_reduces_api_calls(self, mock_api, tmp_path, monkeypatch):
        """Workers share dlinks: N workers = N dlink calls, not N segments."""
        monkeypatch.setattr(config, "DOWNLOAD_SEGMENT_SIZE", 1024)
        monkeypatch.setattr(config, "DOWNLOAD_PROGRESS_DIR", str(tmp_path / "progress"))

        local_path = str(tmp_path / "many_segments.bin")
        file_size = 8000  # 8 segments of 1024 bytes

        def mock_stream(dlink, headers=None):
            resp = MagicMock()
            if headers and "Range" in headers:
                parts = headers["Range"].replace("bytes=", "").split("-")
                start, end = int(parts[0]), int(parts[1])
                size = end - start + 1
            else:
                size = file_size
            resp.iter_content.return_value = [b"\x00" * size]
            resp.raise_for_status = MagicMock()
            return resp

        mock_api.download_stream.side_effect = mock_stream

        download_file(
            mock_api, fs_id=1, remote_path="/apps/bypy/many.bin",
            local_path=local_path, file_size=file_size,
            concurrent=True, workers=2,
        )

        assert os.path.exists(local_path)
        assert os.path.getsize(local_path) == file_size
        # 2 workers = 2 dlink calls (not 8)
        assert mock_api.get_download_link.call_count == 2
        # 8 segments total = 8 download_stream calls
        assert mock_api.download_stream.call_count == 8
