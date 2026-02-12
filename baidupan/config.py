"""Constants, API endpoints, and default configuration."""

import os
import platform

# ── App credentials (bypy-compatible) ──────────────────────────────
APP_KEY = os.environ.get("BAIDUPAN_APP_KEY", "q8WE4EpCsau1oS0MplgMKNBn")
SECRET_KEY = os.environ.get("BAIDUPAN_SECRET_KEY", "PA4MhwB5RE7DacKtoP2i8ikCnNzAqYTD")

# ── Remote root (bypy-compatible) ─────────────────────────────────
REMOTE_ROOT = "/apps/bypy"

# ── OAuth endpoints ───────────────────────────────────────────────
OAUTH_AUTHORIZE_URL = "https://openapi.baidu.com/oauth/2.0/authorize"
OAUTH_DEVICE_CODE_URL = "https://openapi.baidu.com/oauth/2.0/device/code"
OAUTH_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"

# ── Pan API endpoints ─────────────────────────────────────────────
API_BASE = "https://pan.baidu.com"
PCS_BASE = "https://d.pcs.baidu.com"

UINFO_URL = f"{API_BASE}/rest/2.0/xpan/nas?method=uinfo"
QUOTA_URL = f"{API_BASE}/api/quota"
FILE_LIST_URL = f"{API_BASE}/rest/2.0/xpan/file?method=list"
FILE_LISTALL_URL = f"{API_BASE}/rest/2.0/xpan/multimedia?method=listall"
FILE_SEARCH_URL = f"{API_BASE}/rest/2.0/xpan/file?method=search"
FILE_META_URL = f"{API_BASE}/rest/2.0/xpan/multimedia?method=filemetas"
FILE_MANAGER_URL = f"{API_BASE}/rest/2.0/xpan/file?method=filemanager"
PRECREATE_URL = f"{API_BASE}/rest/2.0/xpan/file?method=precreate"
CREATE_URL = f"{API_BASE}/rest/2.0/xpan/file?method=create"
UPLOAD_URL = f"{PCS_BASE}/rest/2.0/pcs/superfile2?method=upload"

# ── Upload / Download defaults ────────────────────────────────────
UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024       # 4 MB per slice (default)
MAX_UPLOAD_SLICES = 2000                  # Near Baidu hard limit (~2048 partseq)
RAPID_UPLOAD_THRESHOLD = 256 * 1024       # 256 KB minimum for rapid upload
DOWNLOAD_CHUNK_SIZE = 4 * 1024 * 1024     # 4 MB read buffer
DOWNLOAD_SEGMENT_SIZE = 4 * 1024 * 1024   # 4 MB per concurrent segment
MAX_UPLOAD_WORKERS = 8
MAX_DOWNLOAD_WORKERS = 32
CONCURRENT_DOWNLOAD_THRESHOLD = 1 * 1024 * 1024  # auto-concurrent for files > 1 MB

# ── Retry defaults ────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, multiplied by attempt number

# ── Paths ─────────────────────────────────────────────────────────
if platform.system() == "Darwin":
    _config_home = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
else:
    _config_home = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))

CONFIG_DIR = os.path.join(_config_home, "baidupan")
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")
HASH_CACHE_FILE = os.path.join(CONFIG_DIR, "hash_cache.json")
UPLOAD_PROGRESS_DIR = os.path.join(CONFIG_DIR, "upload_progress")
DOWNLOAD_PROGRESS_DIR = os.path.join(CONFIG_DIR, "download_progress")

# ── User-Agent ────────────────────────────────────────────────────
USER_AGENT = "pan.baidu.com"
