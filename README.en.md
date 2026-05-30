# douyinks

[中文](README.md)

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![uv](https://img.shields.io/badge/uv-managed-green)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)
![Matrix](https://img.shields.io/badge/Matrix-bot-blue)
![Chrome Extension](https://img.shields.io/badge/Chrome-extension-green)

douyinks is a Matrix-triggered Douyin and Kuaishou video downloader. It includes a command-line app, a local browser bridge daemon, and a Chrome extension for reading page and API data from logged-in browser sessions.

## Features

- Download Douyin liked videos and note/image posts from prepared link lists.
- Export Kuaishou liked videos to a resumable JSONL manifest.
- Download Kuaishou liked videos from exported JSONL manifests.
- Trigger downloads from allowed Matrix rooms with simple text commands.
- Resume batch work with progress/history files under `DOWNLOAD_ROOT`.
- Use a local Chrome extension bridge for logged-in Douyin/Kuaishou browser access.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) for dependency and virtual environment management
- Google Chrome or a Chromium-based browser for the extension bridge
- A Matrix account for bot mode
- Logged-in Douyin/Kuaishou browser sessions for platform operations that need account state

## Setup

Install dependencies, including development tools:

```bash
uv sync --extra dev
```

Copy the example environment file and fill in local values:

```bash
cp .env.example .env
```

Load the Chrome extension from `extension/` in `chrome://extensions`. Enable developer mode, choose "Load unpacked", and select the `extension` directory.

## Configuration

`douyinks` reads configuration from `.env` by default. Keep `.env` private; only `.env.example` should be committed.

| Variable | Required | Description |
| --- | --- | --- |
| `MATRIX_HOMESERVER_URL` | yes | Matrix homeserver URL. |
| `MATRIX_USERNAME` | yes | Matrix bot account username. |
| `MATRIX_PASSWORD` | yes | Matrix bot account password. |
| `MATRIX_ALLOWED_ROOM_IDS` | yes | Comma-separated Matrix room IDs allowed to trigger downloads. |
| `DOWNLOAD_ROOT` | yes | Root directory for downloaded files, progress, history, and sync state. |
| `DOUYINKS_DAEMON_HOST` | no | Local daemon host. Defaults to `127.0.0.1`. |
| `DOUYINKS_DAEMON_PORT` | no | Local daemon port. Defaults to `19826`. |
| `DOWNLOAD_DELAY_SECONDS` | no | Delay between Matrix-triggered downloads. Defaults to `3`. |
| `SYNC_SERVER_ENABLED` | no | Whether to enable the mobile pull sync server. Defaults to `false`. |
| `SYNC_SERVER_HOST` | no | Sync server host. Use `0.0.0.0` for LAN access. |
| `SYNC_SERVER_PORT` | no | Sync server port. Defaults to `19827`. |
| `SYNC_TOKEN` | no | Fixed Bearer token used by the mobile app sync API. |
| `TRANSIENT_SERVICE_IDLE_SECONDS` | no | Idle window before bot-started daemon and sync server are stopped. Defaults to `1800`. |

Example:

```env
MATRIX_HOMESERVER_URL=https://matrix.example
MATRIX_USERNAME=@douyinks:example
MATRIX_PASSWORD=replace-with-your-matrix-password
MATRIX_ALLOWED_ROOM_IDS=!roomid:example
DOWNLOAD_ROOT=/path/to/downloads
DOUYINKS_DAEMON_HOST=127.0.0.1
DOUYINKS_DAEMON_PORT=19826
DOWNLOAD_DELAY_SECONDS=3
SYNC_SERVER_ENABLED=false
SYNC_SERVER_HOST=0.0.0.0
SYNC_SERVER_PORT=19827
SYNC_TOKEN=replace-with-a-long-random-sync-token
TRANSIENT_SERVICE_IDLE_SECONDS=1800
```

## Usage

Run commands from the project directory.

Start the browser bridge daemon:

```bash
uv run douyinks daemon
```

Set the host and port explicitly:

```bash
uv run douyinks daemon --host 127.0.0.1 --port 19826
```

Check whether the daemon is running and whether the extension is connected:

```bash
uv run douyinks status
```

Download a prepared Douyin link list:

```bash
uv run douyinks download-links douyin_links.txt
```

Download only a line range from the link list:

```bash
uv run douyinks download-links douyin_links.txt 1-20
uv run douyinks download-links douyin_links.txt 21-40
```

Use a different interval or progress file when needed:

```bash
uv run douyinks download-links douyin_links.txt --delay 2 --progress-file /path/to/progress.json
```

Redownload historical files whose saved filename starts with `unknown` into a separate folder:

```bash
uv run douyinks redownload-unknown-history /path/to/downloads/download_history.json douyin 1-20 --output-dir /path/to/downloads/redownload_unknown
```

The `1-20` range is applied after filtering the history to `unknown` entries; it is not the raw JSON file line number. Files are written under a platform subfolder such as `redownload_unknown/douyin`. For `kuaishou`, the history entry must include a downloadable `play_url`; otherwise the original history alone is not enough to redownload it.

Export Kuaishou liked videos to a JSONL manifest:

```bash
uv run douyinks export-kuaishou-liked kuaishou_liked.jsonl
```

If the export stops early, run the same command again to resume. Use `--fresh` only when you want to overwrite the existing manifest and start over.

Download the Kuaishou manifest in line ranges:

```bash
uv run douyinks download-kuaishou-liked kuaishou_liked.jsonl 1-100
uv run douyinks download-kuaishou-liked kuaishou_liked.jsonl 101-200
```

Start the Matrix bot:

```bash
uv run douyinks bot
```

For daily use, keep only the Matrix bot running. When a download command arrives, the bot starts the browser bridge daemon on demand; if `SYNC_SERVER_ENABLED=true`, it also starts the mobile sync server. After the download finishes, those bot-owned services stay available for `TRANSIENT_SERVICE_IDLE_SECONDS` seconds, half an hour by default, so the mobile app can pull new files. When the idle window expires, the bot stops the daemon and sync server it started.

Use debug logging when troubleshooting:

```bash
uv run douyinks bot --log-level DEBUG
```

For troubleshooting, you can also start the browser bridge daemon, Matrix bot, and mobile sync server together:

```bash
uv run douyinks serve
```

Start the LAN sync server used by the mobile app:

```bash
uv run douyinks sync-server
```

See [Mobile Sync API](docs/mobile-sync-api.md) for the app-side API contract. The sync service requires `Authorization: Bearer <SYNC_TOKEN>`; the mobile app should use a manually entered laptop sync server address such as `http://192.168.1.23:19827`. If the LAN IP changes, send `ip` or `查询 ip` in the Matrix room to get the current address.

On first startup, the sync server treats existing successful downloads as a baseline, so historical files are not listed as pending. Only later downloads appear in the mobile pending list.

## Matrix Commands

Send one of these messages in an allowed Matrix room:

```text
download douyin like 20
download kuaishou like 20
ip
```

The count must be a positive integer and cannot exceed `200`.

Send `ip` or `查询 ip` to have the bot reply with the laptop's current LAN IP address. If `SYNC_SERVER_ENABLED=true`, the reply also includes the mobile sync URL, for example `http://192.168.1.23:19827`.

## Output and Resume Files

Downloads are saved under:

- `DOWNLOAD_ROOT/douyin/likes`
- `DOWNLOAD_ROOT/kuaishou/likes`

Runtime state is also written under `DOWNLOAD_ROOT`:

- `download_history.json` records successful downloads for deduplication.
- `matrix_sync_state.json` stores the Matrix sync token so old messages are not processed again.
- `douyin_links_progress.json` records resumable progress for Douyin link-list batches unless a custom progress file is supplied.

## Development

Run the test suite:

```bash
uv run pytest
```

Show CLI help:

```bash
uv run douyinks --help
```

The project uses `uv.lock`; keep it committed when dependency changes are intentional.

To start the project from any terminal directory, add a shell function to `~/.zshrc`:

```bash
douyinks-serve() {
  cd /path/to/douyinks && uv run douyinks bot
}
```

Open a new terminal, or run `source ~/.zshrc`, then start everything with:

```bash
douyinks-serve
```

This is better than only adding the command to PATH because `douyinks` reads `.env` from the project directory by default.
For daily use, start `bot`; it starts daemon and sync-server on demand after receiving download commands.

## Privacy and Security

- Do not commit `.env`; it contains Matrix credentials and local paths.
- Do not commit exported liked-list manifests, raw browser page snapshots, downloaded videos, progress files, or history files. These may reveal account activity, liked content, signed media URLs, local paths, or personal preferences.
- The sync server exposes downloaded files on the local network. Use a long `SYNC_TOKEN` and enable it only on trusted networks.
- The Chrome extension requests `debugger`, `tabs`, `cookies`, and `<all_urls>` permissions so it can bridge browser automation for logged-in sessions. Load it only from a trusted local checkout.
- If real credentials were ever committed, rotate them before publishing the repository.

## License

No license file is currently included. Add a license before publishing if you want others to use, modify, or redistribute the project.
