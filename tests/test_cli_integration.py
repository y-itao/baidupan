"""Integration-level tests for CLI command handlers."""

import json
import os
import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from baidupan.cli import (
    build_parser,
    cmd_auth,
    cmd_compare,
    cmd_cp,
    cmd_download,
    cmd_ls,
    cmd_meta,
    cmd_mv,
    cmd_rm,
    cmd_search,
    cmd_syncdown,
    cmd_syncup,
    cmd_upload,
    main,
)


class TestCmdAuth:
    @patch("baidupan.cli.Authenticator")
    def test_device_code_flow(self, mock_cls):
        args = MagicMock()
        args.code = None
        cmd_auth(args)
        mock_cls().auth_device_code.assert_called_once()

    @patch("baidupan.cli.Authenticator")
    def test_authorization_code_flow(self, mock_cls):
        args = MagicMock()
        args.code = "mycode"
        cmd_auth(args)
        mock_cls().auth_authorization_code.assert_called_once_with("mycode")


class TestCmdLs:
    @patch("baidupan.cli._make_api")
    def test_recursive(self, mock_make, capsys):
        mock_api = MagicMock()
        mock_api.list_all.return_value = {
            "errno": 0,
            "list": [
                {"path": "/apps/bypy/sub/a.txt", "isdir": 0, "size": 100, "server_mtime": 1700000000},
            ],
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        args.path = "/"
        args.recursive = True
        cmd_ls(args)

        mock_api.list_all.assert_called_once()
        output = capsys.readouterr().out
        assert "/sub/a.txt" in output


class TestCmdSearch:
    @patch("baidupan.cli._make_api")
    def test_with_results(self, mock_make, capsys):
        mock_api = MagicMock()
        mock_api.search.return_value = {
            "errno": 0,
            "list": [
                {"path": "/apps/bypy/found.txt", "isdir": 0, "size": 50},
            ],
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        args.keyword = "found"
        args.dir = None
        args.recursive = True
        cmd_search(args)

        output = capsys.readouterr().out
        assert "found.txt" in output

    @patch("baidupan.cli._make_api")
    def test_with_dir_filter(self, mock_make, capsys):
        mock_api = MagicMock()
        mock_api.search.return_value = {"errno": 0, "list": []}
        mock_make.return_value = mock_api

        args = MagicMock()
        args.keyword = "key"
        args.dir = "/subdir"
        args.recursive = False
        cmd_search(args)

        # Verify dir was passed to search
        call_kwargs = mock_api.search.call_args
        assert call_kwargs[1].get("dir_path") is not None or call_kwargs[0][1] is not None


class TestCmdMeta:
    @patch("baidupan.cli._make_api")
    def test_found(self, mock_make, capsys):
        mock_api = MagicMock()
        mock_api.list_files.return_value = {
            "errno": 0,
            "list": [
                {"server_filename": "test.txt", "path": "/apps/bypy/test.txt", "fs_id": 42},
            ],
        }
        mock_api.file_metas.return_value = {
            "errno": 0,
            "list": [{"fs_id": 42, "size": 1234, "path": "/apps/bypy/test.txt"}],
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        args.path = "/test.txt"
        cmd_meta(args)

        output = capsys.readouterr().out
        assert "42" in output
        assert "1234" in output

    @patch("baidupan.cli._make_api")
    def test_not_found(self, mock_make):
        mock_api = MagicMock()
        mock_api.list_files.return_value = {"errno": 0, "list": []}
        mock_make.return_value = mock_api

        args = MagicMock()
        args.path = "/missing.txt"
        with pytest.raises(SystemExit):
            cmd_meta(args)


class TestCmdUpload:
    @patch("baidupan.cli._make_api")
    @patch("baidupan.uploader.upload_file")
    def test_upload_file(self, mock_uf, mock_make, tmp_path, capsys):
        test_file = tmp_path / "up.txt"
        test_file.write_text("upload me")

        mock_api = MagicMock()
        mock_make.return_value = mock_api

        args = MagicMock()
        args.local_path = str(test_file)
        args.remote_path = "/"
        args.workers = 4
        cmd_upload(args)
        mock_uf.assert_called_once()

        output = capsys.readouterr().out
        assert "Upload complete" in output

    @patch("baidupan.cli._make_api")
    @patch("baidupan.uploader.upload_dir")
    def test_upload_dir(self, mock_ud, mock_make, tmp_path, capsys):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "f.txt").write_text("x")

        mock_api = MagicMock()
        mock_make.return_value = mock_api

        args = MagicMock()
        args.local_path = str(tmp_path / "sub")
        args.remote_path = "/dest"
        args.workers = 4
        cmd_upload(args)
        mock_ud.assert_called_once()

    @patch("baidupan.cli._make_api")
    def test_upload_missing(self, mock_make, tmp_path):
        mock_make.return_value = MagicMock()
        args = MagicMock()
        args.local_path = str(tmp_path / "no_such_file")
        args.remote_path = "/"
        args.workers = 4
        with pytest.raises(SystemExit):
            cmd_upload(args)


class TestCmdDownload:
    @patch("baidupan.cli._make_api")
    @patch("baidupan.downloader.download_file")
    def test_download_file(self, mock_df, mock_make, tmp_path, capsys):
        mock_api = MagicMock()
        mock_api.list_files.return_value = {
            "errno": 0,
            "list": [
                {"server_filename": "dl.txt", "path": "/apps/bypy/dl.txt",
                 "fs_id": 99, "size": 100, "isdir": 0},
            ],
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        args.remote_path = "/dl.txt"
        args.local_path = str(tmp_path / "dl.txt")
        args.concurrent = False
        args.workers = 4
        cmd_download(args)
        mock_df.assert_called_once()

        output = capsys.readouterr().out
        assert "Download complete" in output

    @patch("baidupan.cli._make_api")
    @patch("baidupan.downloader.download_dir")
    def test_download_dir(self, mock_dd, mock_make, tmp_path, capsys):
        mock_api = MagicMock()
        mock_api.list_files.return_value = {
            "errno": 0,
            "list": [
                {"server_filename": "mydir", "path": "/apps/bypy/mydir",
                 "fs_id": 88, "size": 0, "isdir": 1},
            ],
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        args.remote_path = "/mydir"
        args.local_path = str(tmp_path)
        args.concurrent = False
        args.workers = 4
        cmd_download(args)
        mock_dd.assert_called_once()

    @patch("baidupan.cli._make_api")
    @patch("baidupan.downloader.download_file")
    def test_download_to_existing_dir(self, mock_df, mock_make, tmp_path, capsys):
        mock_api = MagicMock()
        mock_api.list_files.return_value = {
            "errno": 0,
            "list": [
                {"server_filename": "f.txt", "path": "/apps/bypy/f.txt",
                 "fs_id": 77, "size": 50, "isdir": 0},
            ],
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        args.remote_path = "/f.txt"
        args.local_path = str(tmp_path)  # existing directory
        args.concurrent = False
        args.workers = 4
        cmd_download(args)
        # local_path should be joined with filename
        actual_local = mock_df.call_args[1]["local_path"]
        assert actual_local.endswith("f.txt")

    @patch("baidupan.cli._make_api")
    def test_download_not_found(self, mock_make, tmp_path):
        mock_api = MagicMock()
        mock_api.list_files.return_value = {"errno": 0, "list": []}
        mock_make.return_value = mock_api

        args = MagicMock()
        args.remote_path = "/no_such"
        args.local_path = str(tmp_path)
        args.concurrent = False
        args.workers = 4
        with pytest.raises(SystemExit):
            cmd_download(args)


class TestCmdSyncUp:
    @patch("baidupan.cli._make_api")
    @patch("baidupan.sync.sync_up")
    def test_syncup(self, mock_sync, mock_make):
        mock_make.return_value = MagicMock()
        args = MagicMock()
        args.local_dir = "/local"
        args.remote_dir = "/remote"
        args.workers = 4
        args.delete = False
        cmd_syncup(args)
        mock_sync.assert_called_once()


class TestCmdSyncDown:
    @patch("baidupan.cli._make_api")
    @patch("baidupan.sync.sync_down")
    def test_syncdown(self, mock_sync, mock_make):
        mock_make.return_value = MagicMock()
        args = MagicMock()
        args.remote_dir = "/remote"
        args.local_dir = "/local"
        args.concurrent = False
        args.workers = 4
        args.delete = False
        cmd_syncdown(args)
        mock_sync.assert_called_once()


class TestCmdCompare:
    @patch("baidupan.cli._make_api")
    @patch("baidupan.sync.compare")
    def test_compare_output(self, mock_compare, mock_make, capsys):
        mock_make.return_value = MagicMock()
        mock_compare.return_value = {
            "local_only": ["new.txt"],
            "remote_only": ["old.txt"],
            "different": ["changed.txt"],
            "same": ["same.txt"],
        }

        args = MagicMock()
        args.local_dir = "/local"
        args.remote_dir = "/remote"
        cmd_compare(args)

        output = capsys.readouterr().out
        assert "+ new.txt" in output
        assert "- old.txt" in output
        assert "~ changed.txt" in output
        assert "Same: 1" in output


class TestCmdCpMvRm:
    @patch("baidupan.cli._make_api")
    def test_cp(self, mock_make, capsys):
        mock_make.return_value = MagicMock()
        with patch("baidupan.fileops.copy") as mock_copy:
            args = MagicMock()
            args.src = "/a.txt"
            args.dst = "/b.txt"
            args.ondup = "fail"
            cmd_cp(args)
        output = capsys.readouterr().out
        assert "Copied" in output

    @patch("baidupan.cli._make_api")
    def test_mv(self, mock_make, capsys):
        mock_make.return_value = MagicMock()
        with patch("baidupan.fileops.move") as mock_move:
            args = MagicMock()
            args.src = "/a.txt"
            args.dst = "/b.txt"
            args.ondup = "fail"
            cmd_mv(args)
        output = capsys.readouterr().out
        assert "Moved" in output


class TestMain:
    @patch("baidupan.cli.build_parser")
    def test_no_command_exits(self, mock_bp):
        parser = MagicMock()
        parser.parse_args.return_value = MagicMock(command=None)
        mock_bp.return_value = parser
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    @patch("baidupan.cli.build_parser")
    def test_exception_handling(self, mock_bp, capsys):
        args = MagicMock(command="test", verbose=False)
        args.func.side_effect = RuntimeError("boom")
        parser = MagicMock()
        parser.parse_args.return_value = args
        mock_bp.return_value = parser

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "boom" in err

    @patch("baidupan.cli.build_parser")
    def test_keyboard_interrupt(self, mock_bp, capsys):
        args = MagicMock(command="test", verbose=False)
        args.func.side_effect = KeyboardInterrupt()
        parser = MagicMock()
        parser.parse_args.return_value = args
        mock_bp.return_value = parser

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 130
