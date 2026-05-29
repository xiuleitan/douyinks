# douyinks

Matrix-triggered Douyin and Kuaishou video downloader.

## Setup

1. Install dependencies:

   ```bash
   uv sync --extra dev
   ```

2. Copy `.env.example` to `.env`:

   ```bash
   cp .env.example .env
   ```

   Fill in the Matrix account, allowed room ID, and download directory:

   ```env
   MATRIX_HOMESERVER_URL=https://matrix.example
   MATRIX_USERNAME=@douyinks:example
   MATRIX_PASSWORD=change-me
   MATRIX_ALLOWED_ROOM_IDS=!roomid:example
   DOWNLOAD_ROOT=/path/to/downloads
   DOUYINKS_DAEMON_HOST=127.0.0.1
   DOUYINKS_DAEMON_PORT=19826
   DOWNLOAD_DELAY_SECONDS=3
   ```

3. Load the Chrome extension from `extension/` in `chrome://extensions`.

## Command Line

Run commands from the project directory.

Start the browser bridge daemon:

```bash
uv run douyinks daemon
```

You can also set the host and port explicitly:

```bash
uv run douyinks daemon --host 127.0.0.1 --port 19826
```

Check whether the daemon is running and whether the extension is connected:

```bash
uv run douyinks status
```

Download a prepared Douyin link list, one item per second:

```bash
uv run douyinks download-links douyin_links.txt
```

Download only a line range from the link list:

```bash
uv run douyinks download-links douyin_links.txt 1-20
uv run douyinks download-links douyin_links.txt 21-40
```

The link-list downloader reads video and note links such as
`//www.douyin.com/video/7624909172987022642` or `/note/7640692176427439780`.
It saves files to `DOWNLOAD_ROOT/douyin/likes`, uses the same naming rules as
the Matrix command, and records resumable progress in
`DOWNLOAD_ROOT/douyin_links_progress.json`. Re-running the command skips links
already marked as successful or skipped, and retries links previously marked as
failed. The optional range uses 1-based inclusive file line numbers, while blank
lines, comments, and duplicate links are still ignored.

Use a different interval or progress file when needed:

```bash
uv run douyinks download-links douyin_links.txt --delay 2 --progress-file /path/to/progress.json
```

Export all Kuaishou liked videos to a JSONL manifest:

```bash
uv run douyinks export-kuaishou-liked kuaishou_liked.jsonl
```

If the command stops early, run the same command again. It resumes from the
existing JSONL file, waits 4 seconds between liked-feed pages by default, and
skips duplicate `photo_id` values. Use `--fresh` only when you want to overwrite
the manifest and start from the beginning.

Then download the manifest in line ranges:

```bash
uv run douyinks download-kuaishou-liked kuaishou_liked.jsonl 1-100
uv run douyinks download-kuaishou-liked kuaishou_liked.jsonl 101-200
```

The export command calls Kuaishou's liked feed API through the logged-in browser
session and follows `pcursor` until there are no more pages. Each JSONL row
includes `photo_id`, author metadata, timestamp, and the selected `play_url`.

Start the Matrix bot:

```bash
uv run douyinks bot
```

Use debug logging when troubleshooting:

```bash
uv run douyinks bot --log-level DEBUG
```

The bot will start the daemon automatically if it is not already running, but
starting `douyinks daemon` yourself is useful when checking extension connection
status before running downloads.

## Commands

Send one of these messages in an allowed Matrix room:

```text
download douyin like 20
download kuaishou like 20
```

Videos are saved under `DOWNLOAD_ROOT/douyin/likes` or `DOWNLOAD_ROOT/kuaishou/likes`.
Douyin image posts are saved in the same directory as flat image files named like
`author_createTime_awemeId_001.jpg`, `author_createTime_awemeId_002.webp`, etc.
Douyin note posts with child videos are also saved flat in the same directory, for example
`author_createTime_awemeId_001.mp4`, `author_createTime_awemeId_002.mp4`.

Successful downloads are recorded in `DOWNLOAD_ROOT/download_history.json`. On later runs,
Douyinks skips videos already recorded there when the recorded file still exists, and also
skips files whose generated name already exists in the target directory.

Matrix sync state is recorded in `DOWNLOAD_ROOT/matrix_sync_state.json`. This prevents old
room messages from being processed again after the bot restarts.
