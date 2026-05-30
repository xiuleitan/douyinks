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

The laptop-side Matrix bot can report the current LAN address. Send `ip` or `查询 ip` in an allowed Matrix room; if sync is enabled, the reply includes a ready-to-use mobile sync URL such as:

```text
当前局域网 IP: 192.168.1.23
手机同步地址: http://192.168.1.23:19827
```

## Authentication

All sync data endpoints require:

```http
Authorization: Bearer <SYNC_TOKEN>
```

Do not put the token in URLs. Store it in the phone's secure storage.

`GET /sync/health` is intentionally unauthenticated and returns only minimal service metadata.

## Endpoints

On the first sync server start, `DOWNLOAD_ROOT/sync_state.json` records only a `baseline_at` timestamp. Existing successful downloads in `download_history.json` are not copied into the sync queue and are not returned by `/sync/pending`. Only files downloaded after that baseline are listed as pending. To intentionally resync old files, stop the server and remove `DOWNLOAD_ROOT/sync_state.json`.

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

Add these values to `.env`:

```env
SYNC_SERVER_ENABLED=true
SYNC_SERVER_HOST=0.0.0.0
SYNC_SERVER_PORT=19827
SYNC_TOKEN=replace-with-a-long-random-sync-token
TRANSIENT_SERVICE_IDLE_SECONDS=1800
```

For daily use, keep only the Matrix bot running. After a download command arrives, the bot starts the browser bridge daemon and, when `SYNC_SERVER_ENABLED=true`, the sync server on demand. The services stay available for `TRANSIENT_SERVICE_IDLE_SECONDS` seconds after the download finishes, then stop automatically.

Start the bot:

```bash
uv run douyinks bot
```

For troubleshooting, the sync server can still be started directly:

```bash
uv run douyinks sync-server
```
