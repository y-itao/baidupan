"""Low-level API client wrapping all xpan endpoints."""

import json
import logging

import requests
from requests.adapters import HTTPAdapter

from . import config
from .auth import Authenticator, TokenStore
from .errors import APIError, AuthError, retry

log = logging.getLogger(__name__)


class BaiduPanAPI:
    """Thin wrapper around the Baidu Pan xpan REST API."""

    def __init__(self, authenticator: Authenticator = None,
                 pool_connections: int = 32, pool_maxsize: int = 64):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT

        # Large connection pool to support many concurrent workers
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=0,  # we handle retries ourselves
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.auth = authenticator or Authenticator(TokenStore(), self.session)

    @property
    def access_token(self) -> str:
        return self.auth.get_access_token()

    def _params(self, extra: dict = None) -> dict:
        p = {"access_token": self.access_token}
        if extra:
            p.update(extra)
        return p

    def _check(self, data: dict, allow_zero: bool = True) -> dict:
        errno = data.get("errno", 0)
        if errno != 0:
            raise APIError(errno, data.get("errmsg", ""), data.get("request_id", ""))
        return data

    # ── User / Quota ──────────────────────────────────────────────

    @retry(exceptions=(requests.RequestException, APIError))
    def user_info(self) -> dict:
        resp = self.session.get(config.UINFO_URL, params=self._params())
        resp.raise_for_status()
        return self._check(resp.json())

    @retry(exceptions=(requests.RequestException, APIError))
    def quota(self) -> dict:
        resp = self.session.get(config.QUOTA_URL, params=self._params({"checkfree": 1, "checkexpire": 1}))
        resp.raise_for_status()
        return self._check(resp.json())

    # ── File listing / search / meta ──────────────────────────────

    @retry(exceptions=(requests.RequestException, APIError))
    def list_files(self, dir_path: str, order: str = "name", desc: int = 0,
                   start: int = 0, limit: int = 1000) -> dict:
        resp = self.session.get(config.FILE_LIST_URL, params=self._params({
            "dir": dir_path,
            "order": order,
            "desc": desc,
            "start": start,
            "limit": limit,
        }))
        resp.raise_for_status()
        return self._check(resp.json())

    @retry(exceptions=(requests.RequestException, APIError))
    def list_all(self, dir_path: str, start: int = 0, limit: int = 1000,
                 recursion: int = 1) -> dict:
        resp = self.session.get(config.FILE_LISTALL_URL, params=self._params({
            "path": dir_path,
            "start": start,
            "limit": limit,
            "recursion": recursion,
        }))
        resp.raise_for_status()
        return self._check(resp.json())

    @retry(exceptions=(requests.RequestException, APIError))
    def search(self, key: str, dir_path: str = None, recursion: int = 1,
               page: int = 1, num: int = 500) -> dict:
        params = {"key": key, "recursion": recursion, "page": page, "num": num}
        if dir_path:
            params["dir"] = dir_path
        resp = self.session.get(config.FILE_SEARCH_URL, params=self._params(params))
        resp.raise_for_status()
        return self._check(resp.json())

    @retry(exceptions=(requests.RequestException, APIError))
    def file_metas(self, fs_ids: list[int], dlink: int = 1, thumb: int = 0) -> dict:
        resp = self.session.get(config.FILE_META_URL, params=self._params({
            "fsids": json.dumps(fs_ids),
            "dlink": dlink,
            "thumb": thumb,
        }))
        resp.raise_for_status()
        return self._check(resp.json())

    # ── File management ───────────────────────────────────────────

    @retry(exceptions=(requests.RequestException, APIError))
    def file_manager(self, opera: str, file_list: list[dict], ondup: str = "fail") -> dict:
        """Generic file management (copy/move/rename/delete).

        opera: copy | move | rename | delete
        file_list: list of dicts, format depends on opera.
        """
        resp = self.session.post(config.FILE_MANAGER_URL, params=self._params({
            "opera": opera,
        }), data={
            "async": 0,
            "filelist": json.dumps(file_list),
            "ondup": ondup,
        })
        resp.raise_for_status()
        return self._check(resp.json())

    # ── Upload (precreate / upload slice / create) ────────────────

    @retry(exceptions=(requests.RequestException, APIError))
    def precreate(self, remote_path: str, size: int, isdir: int,
                  block_list: list[str], content_md5: str = "",
                  slice_md5: str = "", rtype: int = 3) -> dict:
        resp = self.session.post(config.PRECREATE_URL, params=self._params(), data={
            "path": remote_path,
            "size": size,
            "isdir": isdir,
            "autoinit": 1,
            "rtype": rtype,
            "block_list": json.dumps(block_list),
            "content-md5": content_md5,
            "slice-md5": slice_md5,
        })
        resp.raise_for_status()
        return self._check(resp.json())

    @retry(exceptions=(requests.RequestException,))
    def upload_slice(self, upload_id: str, remote_path: str,
                     partseq: int, data: bytes) -> dict:
        resp = self.session.post(config.UPLOAD_URL, params=self._params({
            "type": "tmpfile",
            "path": remote_path,
            "uploadid": upload_id,
            "partseq": partseq,
        }), files={
            "file": ("chunk", data),
        })
        resp.raise_for_status()
        return resp.json()

    @retry(exceptions=(requests.RequestException, APIError))
    def create_file(self, remote_path: str, size: int, isdir: int,
                    upload_id: str, block_list: list[str], rtype: int = 3) -> dict:
        resp = self.session.post(config.CREATE_URL, params=self._params(), data={
            "path": remote_path,
            "size": size,
            "isdir": isdir,
            "rtype": rtype,
            "uploadid": upload_id,
            "block_list": json.dumps(block_list),
        })
        resp.raise_for_status()
        return self._check(resp.json())

    # ── Download helper ───────────────────────────────────────────

    def get_download_link(self, fs_id: int) -> str:
        """Fetch dlink for a file via filemetas."""
        meta = self.file_metas([fs_id])
        items = meta.get("list", [])
        if not items:
            raise APIError(-1, f"No metadata for fs_id={fs_id}")
        dlink = items[0].get("dlink")
        if not dlink:
            raise APIError(-1, f"No dlink for fs_id={fs_id}")
        return dlink

    @retry(exceptions=(requests.RequestException,))
    def download_stream(self, dlink: str, headers: dict = None) -> requests.Response:
        """Open a streaming response for a download link."""
        h = {"User-Agent": config.USER_AGENT}
        if headers:
            h.update(headers)
        resp = self.session.get(
            dlink,
            params={"access_token": self.access_token},
            headers=h,
            stream=True,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp

    # ── Mkdir helper ──────────────────────────────────────────────

    def mkdir(self, remote_path: str) -> dict:
        """Create a directory (using create with isdir=1, size=0)."""
        return self.create_file(
            remote_path=remote_path,
            size=0,
            isdir=1,
            upload_id="",
            block_list=[],
        )
