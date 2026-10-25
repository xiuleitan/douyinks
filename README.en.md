# douyinks

[中文](README.md)

![macOS](https://img.shields.io/badge/macOS-local-blue)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![uv](https://img.shields.io/badge/uv-managed-green)
![Chrome Extension](https://img.shields.io/badge/Chrome-extension-green)

Download liked Douyin and Kuaishou content from a local Mac terminal. Run `douyinks` in one terminal to start the browser bridge, then run download commands in another. Files are saved directly to the Mac.

## Install

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Chrome or a compatible Chromium browser.

From the project directory:

```bash
uv tool install --editable .
```

Ensure `~/.local/bin` is on PATH. If uv reports otherwise, run `uv tool update-shell` and open a new terminal. You can then use the single `douyinks` entry point from any directory. Remove any old shell function that redirects `douyinks` to `douyinks bot`, then reopen the terminal.

At `chrome://extensions`, enable developer mode and load the project's `extension/` directory as an unpacked extension. Keep Chrome open and log into the platforms you want to use.

## Daily use

List every available command and common examples at any time:

```bash
douyinks help
```

Inspect the arguments and options for a specific command:

```bash
douyinks help douyin download
```

Start the local background service in the first terminal and leave it running:

```bash
douyinks
```

The bridge listens on `127.0.0.1:19826` until you press `Ctrl+C`. Download tasks run in the second terminal and print their results there. Keep both terminals and Chrome open during downloads.

In the second terminal, check the connection:

```bash
douyinks status
```

Download Douyin liked content:

```bash
douyinks douyin download 300
```

This opens your liked list and scrolls automatically. To select a later section, specify the first position; this example downloads entries 60–100:

```bash
douyinks douyin download 41 --start 60
```

For Kuaishou, first open a logged-in Kuaishou page in Chrome, then start listening:

```bash
douyinks kuaishou capture start
```

Refresh the Kuaishou page, open your liked tab, and scroll to load videos. Check the number of unique captured videos:

```bash
douyinks kuaishou count
```

Once enough videos have loaded and pending responses have completed:

```bash
douyinks kuaishou download 300
```

`count` reports the current capture count, not your account's entire liked count. Download reads the capture cache by default. Reloading the extension or closing the captured tab may require starting capture and loading the list again. Restart capture only when you want to collect the list again.

Direct API collection remains available:

```bash
douyinks kuaishou download 300 --source like
```

Each count-based task accepts **1–500** entries. `300` selects up to 300 liked entries for processing. Existing downloads are skipped; short lists, unavailable content, or failures may result in fewer new files. Douyin image or mixed posts can produce multiple media files. Run platform download commands sequentially.

## Progress and summaries

Progress and the final summary appear in the **terminal running the download command**. The first terminal running `douyinks` hosts the browser bridge. An HTTP 200 bridge log does not mean a video has finished downloading.

Downloads show the processed count and success, failure, and skip counts. The final summary includes the requested and available counts, results, elapsed time, and output directory. HTTP request logs are hidden by default; use `--log-level DEBUG` when troubleshooting.

Each completed count-based task saves its latest result, including tasks with failed videos. Read it later with:

```bash
douyinks kuaishou summary
douyinks douyin summary
```

Results are stored in `DOWNLOAD_ROOT/kuaishou_last_download.json` and `DOWNLOAD_ROOT/douyin_last_download.json`. The summary describes the latest completed task and includes its completion time. Watch the download terminal for an ongoing task's progress. Tasks already running before an update retain their original behavior; progress and saved summaries apply to newly started tasks.

## Configuration

Editable installs read `.env` from the project root regardless of the terminal's working directory. Configuration is optional. Existing download paths remain in use. For a new environment:

```bash
cp .env.example .env
```

Edit an existing `.env` directly to preserve its download directory. Non-editable installs use `~/.config/douyinks/.env`. Override the configuration path with `DOUYINKS_ENV_FILE=/absolute/path/to/.env`, using the same configuration in both terminals. Process environment variables take precedence over file values.

| Variable | Default | Description |
| --- | --- | --- |
| `DOWNLOAD_ROOT` | `~/Downloads/douyinks` | Download, history, and batch progress directory. Supports `~`; relative paths are resolved against the configuration directory. |
| `DOUYINKS_DAEMON_HOST` | `127.0.0.1` | Local bridge host. |
| `DOUYINKS_DAEMON_PORT` | `19826` | Local bridge port, also used by the extension by default. |
| `DOWNLOAD_DELAY_SECONDS` | `3` | Delay between media items in count-based downloads. |

The extension connects to `localhost:19826`. Keep the default address and port for normal use. A custom port also requires updating `extension/background.js` and reloading the extension. You can explicitly start the service with `douyinks daemon --host 127.0.0.1 --port 19826`.

Output paths:

- `DOWNLOAD_ROOT/douyin/likes`
- `DOWNLOAD_ROOT/kuaishou/likes`
- `DOWNLOAD_ROOT/download_history.json`: successful download history for deduplication.

## Other local download commands

Commands that access browser pages require a running bridge and connected extension.

```bash
# Douyin link-list download, optionally restricted to a line range
douyinks download-links douyin_links.txt
douyinks download-links douyin_links.txt 1-20

# Export Kuaishou liked videos; repeat to resume an interrupted export
douyinks export-kuaishou-liked kuaishou_liked.jsonl

# Download a range from a Kuaishou manifest
douyinks download-kuaishou-liked kuaishou_liked.jsonl 1-100

# Redownload unknown-prefixed history entries into a separate directory
douyinks redownload-unknown-history /path/to/download_history.json douyin 1-20 --output-dir /path/to/redownload
```

Douyin link-list progress defaults to `DOWNLOAD_ROOT/douyin_links_progress.json`; override it with `--progress-file`. History redownload ranges refer to the filtered unknown records. Kuaishou history entries require a `play_url`.

The existing local commands `douyinks start-kuaishou-liked-capture` and `douyinks download-kuaishou-captured 300` are retained. All commands use the `douyinks` prefix.

## Development and troubleshooting

```bash
uv sync --extra dev
uv run pytest
node --test tests/extension/cdp.test.mjs
```

Without a global installation, use `uv run douyinks`, `uv run douyinks douyin download 300`, or `uv run douyinks kuaishou count` from the project directory.

```bash
douyinks --help
douyinks douyin download --help
douyinks kuaishou --help
douyinks --log-level DEBUG
douyinks douyin download 20 --log-level DEBUG
```

When the service is unavailable, downloads ask you to start `douyinks` in another terminal. If the extension is disconnected, check Chrome and the extension. Failures in count-based downloads print an error and return a nonzero exit status.
