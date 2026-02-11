"""Tests for baidupan.config."""

from baidupan import config


def test_app_key_defaults():
    assert config.APP_KEY == "q8WE4EpCsau1oS0MplgMKNBn"
    assert config.SECRET_KEY == "PA4MhwB5RE7DacKtoP2i8ikCnNzAqYTD"


def test_remote_root():
    assert config.REMOTE_ROOT == "/apps/bypy"


def test_oauth_urls():
    assert "openapi.baidu.com" in config.OAUTH_DEVICE_CODE_URL
    assert "openapi.baidu.com" in config.OAUTH_TOKEN_URL


def test_api_urls():
    assert config.UINFO_URL.startswith("https://pan.baidu.com/")
    assert config.QUOTA_URL.startswith("https://pan.baidu.com/")
    assert config.FILE_LIST_URL.startswith("https://pan.baidu.com/")
    assert config.FILE_LISTALL_URL.startswith("https://pan.baidu.com/")
    assert config.FILE_SEARCH_URL.startswith("https://pan.baidu.com/")
    assert config.FILE_META_URL.startswith("https://pan.baidu.com/")
    assert config.FILE_MANAGER_URL.startswith("https://pan.baidu.com/")
    assert config.PRECREATE_URL.startswith("https://pan.baidu.com/")
    assert config.CREATE_URL.startswith("https://pan.baidu.com/")
    assert config.UPLOAD_URL.startswith("https://d.pcs.baidu.com/")


def test_size_constants():
    assert config.UPLOAD_CHUNK_SIZE == 4 * 1024 * 1024
    assert config.RAPID_UPLOAD_THRESHOLD == 256 * 1024
    assert config.DOWNLOAD_CHUNK_SIZE == 4 * 1024 * 1024
    assert config.DOWNLOAD_SEGMENT_SIZE == 4 * 1024 * 1024


def test_worker_defaults():
    assert config.MAX_UPLOAD_WORKERS == 8
    assert config.MAX_DOWNLOAD_WORKERS == 32


def test_retry_defaults():
    assert config.MAX_RETRIES == 3
    assert config.RETRY_BACKOFF == 2


def test_paths_exist():
    assert config.CONFIG_DIR.endswith("baidupan")
    assert config.TOKEN_FILE.endswith("token.json")
    assert config.HASH_CACHE_FILE.endswith("hash_cache.json")
    assert "upload_progress" in config.UPLOAD_PROGRESS_DIR
    assert "download_progress" in config.DOWNLOAD_PROGRESS_DIR
