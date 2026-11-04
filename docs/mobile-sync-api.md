# Mobile Sync API

This document describes the MVP API that a mobile app can use to pull newly downloaded media from the laptop running `douyinks`.

## Connection

The MVP uses a manual base URL. In the mobile app settings, ask the user to enter the laptop sync server address, for example:

```text
http://192.168.1.23:19827
```

Recommended app connection strategy:

1. Save the last successful base URL.
2. Try that URL on app startup.
3. If it fails, ask the user to update the manual address.

Find the current LAN address on the Mac with:

```bash
douyinks sync-status
```

The phone and Mac need to be on the same LAN. Downloads are initiated from the Mac's command line; phone file synchronization works independently of download command submission.

## Authentication

All sync data endpoints require:

```http
Authorization: Bearer <SYNC_TOKEN>
```

Do not put the token in URLs. Store it in the phone's secure storage.

`GET /sync/health` is intentionally unauthenticated and returns only minimal service metadata.

## Endpoints

On the first-ever sync server start, `DOWNLOAD_ROOT/sync_state.json` records a `baseline_at` timestamp. Successful downloads predating that baseline are not queued automatically.

When restoring or restarting the service, an existing `sync_state.json` is reused with its original baseline and phone acknowledgments. Existing records are preserved. Files downloaded after that baseline, including while the service was unavailable, are returned as pending when they still exist and have not been acknowledged. Removing the ledger would discard acknowledgment history and create a new baseline; keep the existing ledger when recovering the service.

### `GET /sync/health`

Check whether the sync service is reachable.

Response:

```json
{
  "ok": true,
  "service": "douyinks-sync",
  "version": 1
}
```

### `GET /sync/pending`

Return files that have been downloaded on the laptop but not acknowledged by the phone.

Headers:

```http
Authorization: Bearer <SYNC_TOKEN>
```

Response:

```json
{
  "files": [
    {
      "id": "douyin:7640000000000000000",
      "platform": "douyin",
      "video_id": "7640000000000000000",
      "filename": "author_20260530_7640000000000000000.mp4",
      "media_type": "video",
      "size": 12345678,
      "downloaded_at": "2026-05-30T12:00:00+00:00",
      "download_url": "/sync/files/douyin%3A7640000000000000000"
    }
  ]
}
```

`media_type` is one of `video`, `image`, or `file`.

An album or mixed post produces one entry per image or video, sharing the same `video_id` but using distinct file `id` values. The original file retains its legacy ID, such as `douyin:7640000000000000000`; additional files use IDs such as `douyin:7640000000000000000:author_123_7640000000000000000_002.webp`. Treat IDs as opaque values and use the supplied `download_url`. Acknowledgments apply only to the exact IDs submitted, so receiving one image does not acknowledge the rest of an album.

Successfully saved files from a partially failed album are also eligible for sync. Retrying the download fills in missing files while keeping previously issued IDs and acknowledgments.

### `GET /sync/files/{file_id}`

Download one file. Use the `download_url` returned by `/sync/pending`; do not build file paths on the phone.

Headers:

```http
Authorization: Bearer <SYNC_TOKEN>
```

Response: raw file bytes with the best available `Content-Type`.

### `POST /sync/ack`

Mark files as received by the phone after the app has saved them successfully.

Headers:

```http
Authorization: Bearer <SYNC_TOKEN>
Content-Type: application/json
```

Request:

```json
{
  "device_id": "my-phone",
  "file_ids": [
    "douyin:7640000000000000000"
  ]
}
```

Response:

```json
{
  "ok": true,
  "synced": 1
}
```

The endpoint is idempotent. Re-sending the same ack is safe.

## Error Handling

- `401`: missing or invalid token. Ask the user to update the token.
- `404`: file ID is unknown or the laptop-side file no longer exists.
- `400`: malformed JSON or invalid ack payload.

If a download fails on the phone, do not send `ack`; the file will remain pending for the next sync attempt.

## Laptop Configuration

Configure the Mac's project `.env`:

```env
SYNC_SERVER_ENABLED=true
SYNC_SERVER_HOST=0.0.0.0
SYNC_SERVER_PORT=19827
SYNC_TOKEN=replace-with-the-token-used-by-the-phone
```

Run the local background service:

```bash
douyinks
```

When enabled, this starts both the browser bridge and the phone sync server, and keeps both running until `Ctrl+C`. Use a second terminal for downloads:

```bash
douyinks douyin download 300
douyinks kuaishou download 300
```

To inspect the address and saved sync records:

```bash
douyinks sync-status
```

For standalone operation or troubleshooting, start only the phone sync server:

```bash
douyinks sync-server
```

`douyinks daemon` starts only the browser bridge. The standalone sync command requires `SYNC_TOKEN` and works even when automatic startup is disabled.

## Recovery records

- `DOWNLOAD_ROOT/download_history.json`: download records and media file locations. Album records include a `files` list with an independent ID, path, timestamp, and success status for each saved file; the post status remains `partial` until all requested files have downloaded.
- `DOWNLOAD_ROOT/sync_state.json`: the original baseline, phone acknowledgments, and device IDs.

Restoring the service code preserves these files. API reads leave the ledger unchanged; only acknowledgments from the phone update sync status. Files absent from their recorded location cannot be downloaded through the sync API.

At startup, the service indexes previously unrecorded images and indexed album files in `DOWNLOAD_ROOT/douyin/likes` whose names follow the downloader's `author_timestamp_videoID[_index]` format. It preserves existing records and uses each newly indexed file's modification time, so the original baseline still determines eligibility. Unrelated names and symbolic links are ignored. This also recovers later images from albums whose legacy history recorded only the first file.
