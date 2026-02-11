"""Tests for baidupan.fileops."""

from unittest.mock import MagicMock, call

from baidupan import config
from baidupan.fileops import _abs_remote, copy, delete, mkdir, move, rename


class TestAbsRemote:
    def test_relative(self):
        assert _abs_remote("foo/bar") == "/apps/bypy/foo/bar"

    def test_slash_prefix(self):
        assert _abs_remote("/foo/bar") == "/apps/bypy/foo/bar"

    def test_already_absolute(self):
        assert _abs_remote("/apps/bypy/test") == "/apps/bypy/test"

    def test_root(self):
        assert _abs_remote("/") == "/apps/bypy/"


class TestMkdir:
    def test_mkdir(self):
        api = MagicMock()
        api.mkdir.return_value = {"errno": 0}
        result = mkdir(api, "newdir")
        api.mkdir.assert_called_once_with("/apps/bypy/newdir")


class TestCopy:
    def test_copy(self):
        api = MagicMock()
        api.file_manager.return_value = {"errno": 0}
        copy(api, "/a.txt", "/b.txt")
        args = api.file_manager.call_args
        assert args[0][0] == "copy"
        file_list = args[0][1]
        assert file_list[0]["path"] == "/apps/bypy/a.txt"


class TestMove:
    def test_move(self):
        api = MagicMock()
        api.file_manager.return_value = {"errno": 0}
        move(api, "/a.txt", "/dir/b.txt")
        args = api.file_manager.call_args
        assert args[0][0] == "move"


class TestRename:
    def test_rename(self):
        api = MagicMock()
        api.file_manager.return_value = {"errno": 0}
        rename(api, "/old.txt", "new.txt")
        args = api.file_manager.call_args
        assert args[0][0] == "rename"
        file_list = args[0][1]
        assert file_list[0]["newname"] == "new.txt"


class TestDelete:
    def test_delete_single(self):
        api = MagicMock()
        api.file_manager.return_value = {"errno": 0}
        delete(api, ["/test.txt"])
        args = api.file_manager.call_args
        assert args[0][0] == "delete"
        assert "/apps/bypy/test.txt" in args[0][1]

    def test_delete_multiple(self):
        api = MagicMock()
        api.file_manager.return_value = {"errno": 0}
        delete(api, ["/a.txt", "/b.txt"])
        args = api.file_manager.call_args
        assert len(args[0][1]) == 2
