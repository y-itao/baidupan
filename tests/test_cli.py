"""Tests for baidupan.cli."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from baidupan import config
from baidupan.cli import build_parser, _abs_remote


class TestAbsRemote:
    def test_relative(self):
        assert _abs_remote("test") == "/apps/bypy/test"

    def test_slash(self):
        assert _abs_remote("/test") == "/apps/bypy/test"

    def test_already_full(self):
        assert _abs_remote("/apps/bypy/x") == "/apps/bypy/x"


class TestBuildParser:
    def test_version(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_no_command(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_auth_default(self):
        parser = build_parser()
        args = parser.parse_args(["auth"])
        assert args.command == "auth"
        assert args.code is None

    def test_auth_with_code(self):
        parser = build_parser()
        args = parser.parse_args(["auth", "--code", "abc123"])
        assert args.code == "abc123"

    def test_whoami(self):
        parser = build_parser()
        args = parser.parse_args(["whoami"])
        assert args.command == "whoami"

    def test_quota(self):
        parser = build_parser()
        args = parser.parse_args(["quota"])
        assert args.command == "quota"

    def test_ls_default(self):
        parser = build_parser()
        args = parser.parse_args(["ls"])
        assert args.path == "/"
        assert not args.recursive

    def test_ls_with_path(self):
        parser = build_parser()
        args = parser.parse_args(["ls", "/mydir", "-r"])
        assert args.path == "/mydir"
        assert args.recursive

    def test_list_alias(self):
        parser = build_parser()
        args = parser.parse_args(["list", "/test"])
        assert args.command == "list"
        assert args.path == "/test"

    def test_search(self):
        parser = build_parser()
        args = parser.parse_args(["search", "keyword"])
        assert args.keyword == "keyword"

    def test_search_with_dir(self):
        parser = build_parser()
        args = parser.parse_args(["search", "keyword", "-d", "/mydir"])
        assert args.dir == "/mydir"

    def test_meta(self):
        parser = build_parser()
        args = parser.parse_args(["meta", "/file.txt"])
        assert args.path == "/file.txt"

    def test_mkdir(self):
        parser = build_parser()
        args = parser.parse_args(["mkdir", "/newdir"])
        assert args.path == "/newdir"

    def test_upload(self):
        parser = build_parser()
        args = parser.parse_args(["upload", "/local/file.txt", "/remote/"])
        assert args.local_path == "/local/file.txt"
        assert args.remote_path == "/remote/"
        assert args.workers == config.MAX_UPLOAD_WORKERS

    def test_upload_custom_workers(self):
        parser = build_parser()
        args = parser.parse_args(["upload", "a", "b", "-w", "16"])
        assert args.workers == 16

    def test_download(self):
        parser = build_parser()
        args = parser.parse_args(["download", "/remote/file.txt", "/local/"])
        assert args.remote_path == "/remote/file.txt"
        assert args.local_path == "/local/"
        assert not args.concurrent

    def test_download_concurrent(self):
        parser = build_parser()
        args = parser.parse_args(["download", "a", "b", "-c", "-w", "8"])
        assert args.concurrent
        assert args.workers == 8

    def test_syncup(self):
        parser = build_parser()
        args = parser.parse_args(["syncup", "/local", "/remote"])
        assert args.local_dir == "/local"
        assert args.remote_dir == "/remote"
        assert not args.delete

    def test_syncup_delete(self):
        parser = build_parser()
        args = parser.parse_args(["syncup", "/l", "/r", "--delete"])
        assert args.delete

    def test_syncdown(self):
        parser = build_parser()
        args = parser.parse_args(["syncdown", "/remote", "/local"])
        assert args.remote_dir == "/remote"
        assert args.local_dir == "/local"

    def test_compare(self):
        parser = build_parser()
        args = parser.parse_args(["compare", "/local", "/remote"])
        assert args.local_dir == "/local"
        assert args.remote_dir == "/remote"

    def test_cp(self):
        parser = build_parser()
        args = parser.parse_args(["cp", "/a.txt", "/b.txt"])
        assert args.src == "/a.txt"
        assert args.dst == "/b.txt"
        assert args.ondup == "fail"

    def test_copy_alias(self):
        parser = build_parser()
        args = parser.parse_args(["copy", "/a", "/b", "--ondup", "overwrite"])
        assert args.ondup == "overwrite"

    def test_mv(self):
        parser = build_parser()
        args = parser.parse_args(["mv", "/a", "/b"])
        assert args.src == "/a"

    def test_move_alias(self):
        parser = build_parser()
        args = parser.parse_args(["move", "/a", "/b"])
        assert args.command == "move"

    def test_rm(self):
        parser = build_parser()
        args = parser.parse_args(["rm", "/a", "/b"])
        assert args.paths == ["/a", "/b"]

    def test_delete_alias(self):
        parser = build_parser()
        args = parser.parse_args(["delete", "/x"])
        assert args.paths == ["/x"]


class TestCmdHandlers:
    @patch("baidupan.cli._make_api")
    def test_cmd_whoami(self, mock_make, capsys):
        from baidupan.cli import cmd_whoami
        mock_api = MagicMock()
        mock_api.user_info.return_value = {
            "baidu_name": "testuser",
            "netdisk_name": "testnet",
            "vip_type": 2,
            "uk": 12345,
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        cmd_whoami(args)

        output = capsys.readouterr().out
        assert "testuser" in output
        assert "testnet" in output

    @patch("baidupan.cli._make_api")
    def test_cmd_quota(self, mock_make, capsys):
        from baidupan.cli import cmd_quota
        mock_api = MagicMock()
        mock_api.quota.return_value = {
            "total": 2199023255552,
            "used": 1099511627776,
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        cmd_quota(args)

        output = capsys.readouterr().out
        assert "2.0 TB" in output
        assert "1.0 TB" in output

    @patch("baidupan.cli._make_api")
    def test_cmd_ls_empty(self, mock_make, capsys):
        from baidupan.cli import cmd_ls
        mock_api = MagicMock()
        mock_api.list_files.return_value = {"errno": 0, "list": []}
        mock_make.return_value = mock_api

        args = MagicMock()
        args.path = "/"
        args.recursive = False
        cmd_ls(args)

        output = capsys.readouterr().out
        assert "(empty)" in output

    @patch("baidupan.cli._make_api")
    def test_cmd_ls_with_files(self, mock_make, capsys):
        from baidupan.cli import cmd_ls
        mock_api = MagicMock()
        mock_api.list_files.return_value = {
            "errno": 0,
            "list": [
                {"server_filename": "test.txt", "isdir": 0, "size": 1024, "server_mtime": 1700000000},
                {"server_filename": "dir", "isdir": 1, "size": 0, "server_mtime": 1700000000},
            ],
        }
        mock_make.return_value = mock_api

        args = MagicMock()
        args.path = "/"
        args.recursive = False
        cmd_ls(args)

        output = capsys.readouterr().out
        assert "test.txt" in output
        assert "dir" in output
        assert "-" in output  # file marker
        assert "d" in output  # dir marker

    @patch("baidupan.cli._make_api")
    def test_cmd_search_no_results(self, mock_make, capsys):
        from baidupan.cli import cmd_search
        mock_api = MagicMock()
        mock_api.search.return_value = {"errno": 0, "list": []}
        mock_make.return_value = mock_api

        args = MagicMock()
        args.keyword = "nonexist"
        args.dir = None
        args.recursive = True
        cmd_search(args)

        output = capsys.readouterr().out
        assert "No results found" in output

    @patch("baidupan.cli._make_api")
    def test_cmd_mkdir(self, mock_make, capsys):
        from baidupan.cli import cmd_mkdir
        mock_api = MagicMock()
        mock_make.return_value = mock_api

        from baidupan import fileops
        with patch.object(fileops, "mkdir") as mock_mkdir:
            args = MagicMock()
            args.path = "/newdir"
            cmd_mkdir(args)

        output = capsys.readouterr().out
        assert "Created" in output

    @patch("baidupan.cli._make_api")
    def test_cmd_rm(self, mock_make, capsys):
        from baidupan.cli import cmd_rm
        mock_api = MagicMock()
        mock_make.return_value = mock_api

        from baidupan import fileops
        with patch.object(fileops, "delete") as mock_del:
            args = MagicMock()
            args.paths = ["/old.txt"]
            cmd_rm(args)

        output = capsys.readouterr().out
        assert "Deleted" in output
