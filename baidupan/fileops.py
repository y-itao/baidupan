"""File management operations: mkdir, copy, move, rename, delete."""

import logging

from .api import BaiduPanAPI
from . import config

log = logging.getLogger(__name__)


def _abs_remote(path: str) -> str:
    """Ensure path is absolute under REMOTE_ROOT."""
    if not path.startswith("/"):
        path = "/" + path
    if not path.startswith(config.REMOTE_ROOT):
        path = config.REMOTE_ROOT + path
    return path


def mkdir(api: BaiduPanAPI, remote_path: str):
    remote_path = _abs_remote(remote_path)
    result = api.mkdir(remote_path)
    log.info("Created directory: %s", remote_path)
    return result


def copy(api: BaiduPanAPI, src: str, dst: str, ondup: str = "fail"):
    src = _abs_remote(src)
    dst = _abs_remote(dst)
    file_list = [{"path": src, "dest": "/".join(dst.rsplit("/", 1)[:-1]) or "/",
                  "newname": dst.rsplit("/", 1)[-1]}]
    result = api.file_manager("copy", file_list, ondup=ondup)
    log.info("Copied %s -> %s", src, dst)
    return result


def move(api: BaiduPanAPI, src: str, dst: str, ondup: str = "fail"):
    src = _abs_remote(src)
    dst = _abs_remote(dst)
    file_list = [{"path": src, "dest": "/".join(dst.rsplit("/", 1)[:-1]) or "/",
                  "newname": dst.rsplit("/", 1)[-1]}]
    result = api.file_manager("move", file_list, ondup=ondup)
    log.info("Moved %s -> %s", src, dst)
    return result


def rename(api: BaiduPanAPI, src: str, newname: str, ondup: str = "fail"):
    src = _abs_remote(src)
    file_list = [{"path": src, "newname": newname}]
    result = api.file_manager("rename", file_list, ondup=ondup)
    log.info("Renamed %s -> %s", src, newname)
    return result


def delete(api: BaiduPanAPI, paths: list[str]):
    paths = [_abs_remote(p) for p in paths]
    file_list = [p for p in paths]
    result = api.file_manager("delete", file_list)
    log.info("Deleted: %s", paths)
    return result
