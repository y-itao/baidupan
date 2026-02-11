"""Argparse CLI: subcommand definitions and dispatch."""

import argparse
import json
import os
import sys

from . import __version__, config
from .api import BaiduPanAPI
from .auth import Authenticator, TokenStore
from .utils import format_size, format_time, setup_logging


def _make_api() -> BaiduPanAPI:
    return BaiduPanAPI()


def _abs_remote(path: str) -> str:
    """Ensure path is absolute under REMOTE_ROOT."""
    if not path.startswith("/"):
        path = "/" + path
    if not path.startswith(config.REMOTE_ROOT):
        path = config.REMOTE_ROOT + path
    return path


# ── Subcommand handlers ──────────────────────────────────────────

def cmd_auth(args):
    auth = Authenticator()
    if args.code:
        auth.auth_authorization_code(args.code)
    elif args.device:
        auth.auth_device_code()
    else:
        auth.auth_interactive()


def cmd_whoami(args):
    api = _make_api()
    info = api.user_info()
    print(f"User:    {info.get('baidu_name', 'N/A')}")
    print(f"Netdisk: {info.get('netdisk_name', 'N/A')}")
    print(f"VIP:     {info.get('vip_type', 0)}")
    print(f"UK:      {info.get('uk', 'N/A')}")


def cmd_quota(args):
    api = _make_api()
    q = api.quota()
    total = q.get("total", 0)
    used = q.get("used", 0)
    free = total - used
    print(f"Total: {format_size(total)}")
    print(f"Used:  {format_size(used)}")
    print(f"Free:  {format_size(free)}")


def cmd_ls(args):
    api = _make_api()
    remote = _abs_remote(args.path)

    if args.recursive:
        result = api.list_all(remote)
    else:
        result = api.list_files(remote)

    items = result.get("list", [])
    if not items:
        print("(empty)")
        return

    for item in items:
        is_dir = "d" if item.get("isdir") else "-"
        size = format_size(item.get("size", 0))
        mtime = format_time(item.get("server_mtime", 0))
        name = item.get("server_filename", item.get("path", ""))
        if args.recursive:
            name = item.get("path", "")[len(config.REMOTE_ROOT):]
        print(f"{is_dir}  {size:>10s}  {mtime}  {name}")


def cmd_search(args):
    api = _make_api()
    dir_path = _abs_remote(args.dir) if args.dir else None
    result = api.search(args.keyword, dir_path=dir_path, recursion=1 if args.recursive else 0)
    items = result.get("list", [])
    if not items:
        print("No results found.")
        return
    for item in items:
        is_dir = "d" if item.get("isdir") else "-"
        size = format_size(item.get("size", 0))
        path = item.get("path", "")
        print(f"{is_dir}  {size:>10s}  {path}")


def cmd_meta(args):
    api = _make_api()
    remote = _abs_remote(args.path)
    # need to find fs_id first via listing the parent
    parent = "/".join(remote.rsplit("/", 1)[:-1]) or "/"
    name = remote.rsplit("/", 1)[-1]
    result = api.list_files(parent)
    items = result.get("list", [])
    fs_id = None
    for item in items:
        if item.get("server_filename") == name or item.get("path") == remote:
            fs_id = item.get("fs_id")
            break
    if fs_id is None:
        print(f"File not found: {remote}")
        sys.exit(1)

    meta = api.file_metas([fs_id])
    for item in meta.get("list", []):
        print(json.dumps(item, indent=2, ensure_ascii=False))


def cmd_mkdir(args):
    from .fileops import mkdir
    api = _make_api()
    mkdir(api, args.path)
    print(f"Created: {_abs_remote(args.path)}")


def cmd_upload(args):
    from .uploader import upload_file, upload_dir
    api = _make_api()
    local = os.path.abspath(args.local_path)
    remote = _abs_remote(args.remote_path)

    if os.path.isdir(local):
        upload_dir(api, local, remote, workers=args.workers)
    elif os.path.isfile(local):
        fname = os.path.basename(local)
        # if remote ends with /, treat as directory
        if remote.endswith("/") or args.remote_path.endswith("/"):
            remote = remote.rstrip("/") + "/" + fname
        elif not os.path.splitext(remote)[1]:
            # remote looks like a directory
            remote = remote + "/" + fname
        upload_file(api, local, remote, workers=args.workers)
    else:
        print(f"Local path not found: {local}")
        sys.exit(1)

    print("Upload complete.")


def cmd_download(args):
    from .downloader import download_file, download_dir
    api = _make_api()
    remote = _abs_remote(args.remote_path)
    local = os.path.abspath(args.local_path)

    # Parse segment size (supports MB suffix e.g. "2M", "8M")
    segment_size = None
    if hasattr(args, "segment_size") and args.segment_size:
        seg = args.segment_size.upper().rstrip("B")
        if seg.endswith("M"):
            segment_size = int(seg[:-1]) * 1024 * 1024
        elif seg.endswith("K"):
            segment_size = int(seg[:-1]) * 1024
        else:
            segment_size = int(seg)

    # determine if remote is file or dir by listing parent
    parent = "/".join(remote.rsplit("/", 1)[:-1]) or "/"
    name = remote.rsplit("/", 1)[-1]
    result = api.list_files(parent)
    items = result.get("list", [])
    target = None
    for item in items:
        if item.get("server_filename") == name or item.get("path") == remote:
            target = item
            break

    if target is None:
        print(f"Remote path not found: {remote}")
        sys.exit(1)

    if target.get("isdir"):
        download_dir(api, remote, local, concurrent=args.concurrent,
                     workers=args.workers, segment_size=segment_size)
    else:
        if os.path.isdir(local):
            local = os.path.join(local, target["server_filename"])
        download_file(
            api,
            fs_id=target["fs_id"],
            remote_path=remote,
            local_path=local,
            file_size=target["size"],
            concurrent=args.concurrent,
            workers=args.workers,
            segment_size=segment_size,
        )

    print("Download complete.")


def cmd_syncup(args):
    from .sync import sync_up
    api = _make_api()
    sync_up(api, args.local_dir, args.remote_dir,
            workers=args.workers, delete_extra=args.delete)


def cmd_syncdown(args):
    from .sync import sync_down
    api = _make_api()
    sync_down(api, args.remote_dir, args.local_dir,
              concurrent=args.concurrent, workers=args.workers,
              delete_extra=args.delete)


def cmd_compare(args):
    from .sync import compare
    api = _make_api()
    remote = args.remote_dir
    if not remote.startswith(config.REMOTE_ROOT):
        remote = config.REMOTE_ROOT + ("/" + remote.lstrip("/"))

    diff = compare(api, args.local_dir, remote)

    if diff["local_only"]:
        print(f"\nLocal only ({len(diff['local_only'])}):")
        for f in diff["local_only"]:
            print(f"  + {f}")

    if diff["remote_only"]:
        print(f"\nRemote only ({len(diff['remote_only'])}):")
        for f in diff["remote_only"]:
            print(f"  - {f}")

    if diff["different"]:
        print(f"\nDifferent ({len(diff['different'])}):")
        for f in diff["different"]:
            print(f"  ~ {f}")

    print(f"\nSame: {len(diff['same'])}, "
          f"Local only: {len(diff['local_only'])}, "
          f"Remote only: {len(diff['remote_only'])}, "
          f"Different: {len(diff['different'])}")


def cmd_cp(args):
    from .fileops import copy
    api = _make_api()
    copy(api, args.src, args.dst, ondup=args.ondup)
    print(f"Copied: {_abs_remote(args.src)} -> {_abs_remote(args.dst)}")


def cmd_mv(args):
    from .fileops import move
    api = _make_api()
    move(api, args.src, args.dst, ondup=args.ondup)
    print(f"Moved: {_abs_remote(args.src)} -> {_abs_remote(args.dst)}")


def cmd_rm(args):
    from .fileops import delete
    api = _make_api()
    delete(api, args.paths)
    print(f"Deleted: {args.paths}")


# ── Parser construction ──────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="baidupan",
        description="Baidu Pan CLI tool (xpan API)",
    )
    parser.add_argument("-V", "--version", action="version", version=f"baidupan {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # auth
    p = sub.add_parser("auth", help="Authenticate with Baidu Pan")
    p.add_argument("--code", help="Directly provide authorization code")
    p.add_argument("--device", action="store_true", help="Use Device Code flow instead")
    p.set_defaults(func=cmd_auth)

    # whoami
    p = sub.add_parser("whoami", help="Show user info")
    p.set_defaults(func=cmd_whoami)

    # quota
    p = sub.add_parser("quota", help="Show storage quota")
    p.set_defaults(func=cmd_quota)

    # ls / list
    for name in ("ls", "list"):
        p = sub.add_parser(name, help="List remote directory")
        p.add_argument("path", nargs="?", default="/", help="Remote path")
        p.add_argument("-r", "--recursive", action="store_true")
        p.set_defaults(func=cmd_ls)

    # search
    p = sub.add_parser("search", help="Search files by keyword")
    p.add_argument("keyword", help="Search keyword")
    p.add_argument("-d", "--dir", help="Limit search to directory")
    p.add_argument("-r", "--recursive", action="store_true", default=True)
    p.set_defaults(func=cmd_search)

    # meta
    p = sub.add_parser("meta", help="Show file metadata")
    p.add_argument("path", help="Remote file path")
    p.set_defaults(func=cmd_meta)

    # mkdir
    p = sub.add_parser("mkdir", help="Create remote directory")
    p.add_argument("path", help="Remote directory path")
    p.set_defaults(func=cmd_mkdir)

    # upload
    p = sub.add_parser("upload", help="Upload file or directory")
    p.add_argument("local_path", help="Local file/directory path")
    p.add_argument("remote_path", help="Remote destination path")
    p.add_argument("-w", "--workers", type=int, default=config.MAX_UPLOAD_WORKERS,
                   help=f"Upload worker threads (default: {config.MAX_UPLOAD_WORKERS})")
    p.set_defaults(func=cmd_upload)

    # download
    p = sub.add_parser("download", help="Download file or directory")
    p.add_argument("remote_path", help="Remote file/directory path")
    p.add_argument("local_path", help="Local destination path")
    p.add_argument("-w", "--workers", type=int, default=config.MAX_DOWNLOAD_WORKERS,
                   help=f"Download worker threads (default: {config.MAX_DOWNLOAD_WORKERS})")
    p.add_argument("-c", "--concurrent", action="store_true",
                   help="Use concurrent segment download for large files")
    p.add_argument("-s", "--segment-size", default=None,
                   help="Segment size per worker (e.g. 2M, 4M, 8M). Default: 4M")
    p.set_defaults(func=cmd_download)

    # syncup
    p = sub.add_parser("syncup", help="Sync local directory to remote")
    p.add_argument("local_dir", help="Local directory")
    p.add_argument("remote_dir", help="Remote directory")
    p.add_argument("-w", "--workers", type=int, default=config.MAX_UPLOAD_WORKERS)
    p.add_argument("--delete", action="store_true",
                   help="Delete remote files not present locally")
    p.set_defaults(func=cmd_syncup)

    # syncdown
    p = sub.add_parser("syncdown", help="Sync remote directory to local")
    p.add_argument("remote_dir", help="Remote directory")
    p.add_argument("local_dir", help="Local directory")
    p.add_argument("-w", "--workers", type=int, default=config.MAX_DOWNLOAD_WORKERS)
    p.add_argument("-c", "--concurrent", action="store_true")
    p.add_argument("--delete", action="store_true",
                   help="Delete local files not present remotely")
    p.set_defaults(func=cmd_syncdown)

    # compare
    p = sub.add_parser("compare", help="Compare local and remote directories")
    p.add_argument("local_dir", help="Local directory")
    p.add_argument("remote_dir", help="Remote directory")
    p.set_defaults(func=cmd_compare)

    # cp / copy
    for name in ("cp", "copy"):
        p = sub.add_parser(name, help="Copy remote file")
        p.add_argument("src", help="Source path")
        p.add_argument("dst", help="Destination path")
        p.add_argument("--ondup", default="fail", choices=["fail", "overwrite", "newcopy"])
        p.set_defaults(func=cmd_cp)

    # mv / move
    for name in ("mv", "move"):
        p = sub.add_parser(name, help="Move/rename remote file")
        p.add_argument("src", help="Source path")
        p.add_argument("dst", help="Destination path")
        p.add_argument("--ondup", default="fail", choices=["fail", "overwrite", "newcopy"])
        p.set_defaults(func=cmd_mv)

    # rm / delete
    for name in ("rm", "delete"):
        p = sub.add_parser(name, help="Delete remote files")
        p.add_argument("paths", nargs="+", help="Remote paths to delete")
        p.set_defaults(func=cmd_rm)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=getattr(args, "verbose", False))

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if getattr(args, "verbose", False):
            import traceback
            traceback.print_exc()
        sys.exit(1)
