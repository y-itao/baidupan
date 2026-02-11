# baidupan

A fast Baidu Pan (百度网盘) CLI tool built on the official xpan API. Compatible with [bypy](https://github.com/houtianze/bypy) remote paths (`/apps/bypy`).

## Features

- **16 commands**: auth, whoami, quota, ls, search, meta, mkdir, upload, download, syncup, syncdown, compare, cp, mv, rm
- **Rapid upload (秒传)**: zero-transfer via content-md5 + slice-md5 matching
- **Concurrent chunked upload**: multi-threaded with configurable workers
- **Concurrent segmented download**: per-worker dlink for independent CDN bandwidth, bypassing per-connection speed limits
- **Resume support**: upload and download progress persisted to disk, auto-resume on restart
- **Incremental sync**: compare-then-transfer, only changed files are synced
- **Hash caching**: `(filepath, mtime, size) -> hashes` cached to disk, avoids re-computation

## Installation

```bash
# Basic install
pip install .

# With progress bar (recommended)
pip install ".[progress]"
```

Requires **Python >= 3.10** and `requests`. `tqdm` is optional for progress bars.

### Install from GitHub

```bash
pip install git+https://github.com/y-itao/baidupan.git
# or with progress bar
pip install "baidupan[progress] @ git+https://github.com/y-itao/baidupan.git"
```

## Quick Start

```bash
# 1. Authenticate (opens browser for authorization)
baidupan auth

# 2. Check connection
baidupan whoami
baidupan quota

# 3. Upload
baidupan upload ./local_file.txt /remote_dir/
baidupan upload ./local_dir /remote_dir

# 4. Download
baidupan download /remote_file.txt ./
baidupan download /remote_dir ./local_dir

# 5. Sync
baidupan syncup ./local_dir /remote_dir
baidupan syncdown /remote_dir ./local_dir
```

## Commands

| Command | Description |
|---------|-------------|
| `auth` | OAuth2 authentication (browser or device code) |
| `whoami` | Show user info |
| `quota` | Show storage quota |
| `ls` / `list` | List remote directory (`-r` for recursive) |
| `search` | Search files by keyword |
| `meta` | Show file metadata (size, md5, etc.) |
| `mkdir` | Create remote directory |
| `upload` | Upload file or directory |
| `download` | Download file or directory |
| `syncup` | Sync local directory to remote |
| `syncdown` | Sync remote directory to local |
| `compare` | Compare local and remote directories |
| `cp` / `copy` | Copy remote file |
| `mv` / `move` | Move or rename remote file |
| `rm` / `delete` | Delete remote files |

## Performance Tuning

### Upload

```bash
# Default: 8 workers, 4MB chunks
baidupan upload ./bigfile /remote/ -w 16
```

### Download

The downloader automatically uses concurrent segmented download for files > 1MB. Each worker gets its own download link for independent CDN bandwidth.

```bash
# Default: 32 workers, 4MB segments
baidupan download /remote/bigfile ./ -w 48

# Adjust segment size
baidupan download /remote/bigfile ./ -w 48 -s 2M
```

**Benchmark results (500MB file):**

| Workers | Download Speed |
|---------|---------------|
| 8 | ~5 MB/s |
| 16 | ~8 MB/s |
| 32 | ~12 MB/s |
| 48 | ~15 MB/s |

Upload typically reaches 25-35 MB/s with 8-16 workers.

> Actual speeds depend on your network bandwidth and Baidu account tier (SVIP gets higher per-connection limits).

## Authentication

baidupan supports two OAuth2 flows:

```bash
# Interactive (default): opens browser URL, paste authorization code back
baidupan auth

# Device Code flow: displays a code to enter at baidu.com
baidupan auth --device

# Direct code input
baidupan auth --code YOUR_AUTH_CODE
```

Tokens are stored at:
- **macOS**: `~/Library/Application Support/baidupan/token.json`
- **Linux**: `~/.config/baidupan/token.json`

Tokens auto-refresh when expired.

## Configuration

All defaults are in `baidupan/config.py`. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `REMOTE_ROOT` | `/apps/bypy` | Remote root directory (bypy compatible) |
| `UPLOAD_CHUNK_SIZE` | 4 MB | Upload slice size |
| `DOWNLOAD_SEGMENT_SIZE` | 4 MB | Download segment size |
| `MAX_UPLOAD_WORKERS` | 8 | Default upload threads |
| `MAX_DOWNLOAD_WORKERS` | 32 | Default download threads |
| `MAX_RETRIES` | 3 | API retry attempts |

Override via environment variables:
```bash
export BAIDUPAN_APP_KEY="your_app_key"
export BAIDUPAN_SECRET_KEY="your_secret_key"
```

## Project Structure

```
baidupan/
├── __init__.py       # Version
├── __main__.py       # python -m baidupan entry
├── cli.py            # Argparse CLI with all subcommands
├── config.py         # Constants, API endpoints, defaults
├── auth.py           # OAuth2 (Authorization Code + Device Code + Refresh)
├── api.py            # Low-level xpan API client
├── hasher.py         # Single-pass MD5 computation + disk cache
├── uploader.py       # Rapid upload + concurrent chunked upload + resume
├── downloader.py     # Concurrent segmented download + resume
├── sync.py           # Bidirectional sync (compare / sync_up / sync_down)
├── fileops.py        # File management (mkdir/copy/move/delete)
├── errors.py         # Exception hierarchy + retry decorator
└── utils.py          # Progress bar, formatting, logging
```

## Development

```bash
pip install -e ".[progress]"
pip install -r requirements-dev.txt
pytest tests/
```

## License

MIT
