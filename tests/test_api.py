"""Tests for baidupan.api."""

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from baidupan.api import BaiduPanAPI
from baidupan.errors import APIError


@pytest.fixture
def api():
    """Create a BaiduPanAPI with mocked authenticator."""
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "test_token"
    a = BaiduPanAPI(authenticator=mock_auth)
    a.session = MagicMock()
    return a


def _json_resp(data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


class TestBaiduPanAPI:
    def test_params_includes_token(self, api):
        p = api._params()
        assert p["access_token"] == "test_token"

    def test_params_with_extra(self, api):
        p = api._params({"foo": "bar"})
        assert p["foo"] == "bar"
        assert p["access_token"] == "test_token"

    def test_check_success(self, api):
        data = {"errno": 0, "list": []}
        assert api._check(data) == data

    def test_check_error(self, api):
        data = {"errno": 31023, "errmsg": "file not exist", "request_id": "r1"}
        with pytest.raises(APIError) as exc_info:
            api._check(data)
        assert exc_info.value.errno == 31023

    def test_user_info(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "baidu_name": "testuser",
            "netdisk_name": "testnet",
        })
        result = api.user_info()
        assert result["baidu_name"] == "testuser"

    def test_quota(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "total": 2199023255552,
            "used": 1099511627776,
        })
        result = api.quota()
        assert result["total"] == 2199023255552

    def test_list_files(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "list": [{"server_filename": "test.txt", "size": 100}],
        })
        result = api.list_files("/apps/bypy")
        assert len(result["list"]) == 1

    def test_list_all(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "list": [{"path": "/apps/bypy/a.txt"}, {"path": "/apps/bypy/b.txt"}],
        })
        result = api.list_all("/apps/bypy")
        assert len(result["list"]) == 2

    def test_search(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "list": [{"path": "/apps/bypy/found.txt"}],
        })
        result = api.search("found")
        assert len(result["list"]) == 1

    def test_search_with_dir(self, api):
        api.session.get.return_value = _json_resp({"errno": 0, "list": []})
        api.search("key", dir_path="/apps/bypy/sub")
        call_args = api.session.get.call_args
        assert "dir" in call_args[1]["params"] or "dir" in call_args.kwargs.get("params", {})

    def test_file_metas(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "list": [{"fs_id": 123, "dlink": "https://dl.example.com/file"}],
        })
        result = api.file_metas([123])
        assert result["list"][0]["dlink"] == "https://dl.example.com/file"

    def test_file_manager_delete(self, api):
        api.session.post.return_value = _json_resp({"errno": 0})
        result = api.file_manager("delete", ["/apps/bypy/old.txt"])
        assert result["errno"] == 0

    def test_file_manager_copy(self, api):
        api.session.post.return_value = _json_resp({"errno": 0})
        result = api.file_manager("copy", [{"path": "/a", "dest": "/b", "newname": "c"}])
        assert result["errno"] == 0

    def test_precreate(self, api):
        api.session.post.return_value = _json_resp({
            "errno": 0,
            "return_type": 1,
            "uploadid": "up123",
            "block_list": [0, 1],
        })
        result = api.precreate("/apps/bypy/f.txt", 1000, 0, ["md5a"], "cmd5", "smd5")
        assert result["uploadid"] == "up123"

    def test_precreate_rapid(self, api):
        api.session.post.return_value = _json_resp({
            "errno": 0,
            "return_type": 2,
        })
        result = api.precreate("/apps/bypy/f.txt", 1000, 0, ["md5a"], "cmd5", "smd5")
        assert result["return_type"] == 2

    def test_upload_slice(self, api):
        api.session.post.return_value = _json_resp({"md5": "slicemd5"})
        result = api.upload_slice("up123", "/apps/bypy/f.txt", 0, b"data")
        assert result["md5"] == "slicemd5"

    def test_create_file(self, api):
        api.session.post.return_value = _json_resp({
            "errno": 0,
            "path": "/apps/bypy/f.txt",
            "size": 1000,
        })
        result = api.create_file("/apps/bypy/f.txt", 1000, 0, "up123", ["md5a"])
        assert result["path"] == "/apps/bypy/f.txt"

    def test_get_download_link(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "list": [{"fs_id": 111, "dlink": "https://d.pcs.baidu.com/dl/xxx"}],
        })
        dlink = api.get_download_link(111)
        assert "d.pcs.baidu.com" in dlink

    def test_get_download_link_no_items(self, api):
        api.session.get.return_value = _json_resp({"errno": 0, "list": []})
        with pytest.raises(APIError):
            api.get_download_link(999)

    def test_get_download_link_no_dlink(self, api):
        api.session.get.return_value = _json_resp({
            "errno": 0,
            "list": [{"fs_id": 111}],
        })
        with pytest.raises(APIError):
            api.get_download_link(111)

    def test_download_stream(self, api):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        api.session.get.return_value = mock_resp
        resp = api.download_stream("https://dl.example.com/file")
        assert resp == mock_resp

    def test_mkdir(self, api):
        api.session.post.return_value = _json_resp({
            "errno": 0,
            "path": "/apps/bypy/newdir",
        })
        result = api.mkdir("/apps/bypy/newdir")
        assert result["path"] == "/apps/bypy/newdir"

    def test_api_error_propagation(self, api):
        api.session.get.return_value = _json_resp({"errno": 42, "errmsg": "bad"})
        with pytest.raises(APIError) as exc_info:
            api.user_info()
        assert exc_info.value.errno == 42
