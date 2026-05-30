import json
from pathlib import Path

import httpx
import pytest
from aiohttp import web

from douyinks.config import Settings
from douyinks.history import DownloadHistory
from douyinks.sync_server import create_sync_app
from douyinks.sync_transfer import SyncTransferState


def make_settings(tmp_path, token="test-sync-token") -> Settings:
    return Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!a:example",
            "DOWNLOAD_ROOT": str(tmp_path),
            "SYNC_TOKEN": token,
        }
    )


def record_download(tmp_path, platform="douyin", video_id="999", filename="author_999.mp4"):
    file_path = tmp_path / platform / "likes" / filename
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"video-bytes")
    history = DownloadHistory(tmp_path / "download_history.json")
    history.record_success(platform, video_id, file_path, filename)
    return file_path


def test_sync_state_lists_pending_downloads_and_marks_acknowledged(tmp_path):
    settings = make_settings(tmp_path)
    file_path = record_download(tmp_path)
    state = SyncTransferState(settings.sync_state_path)

    pending = state.pending_from_history(settings.download_history_path)

    assert pending == [
        {
            "id": "douyin:999",
            "platform": "douyin",
            "video_id": "999",
            "filename": "author_999.mp4",
            "media_type": "video",
            "size": len(b"video-bytes"),
            "downloaded_at": pending[0]["downloaded_at"],
        }
    ]

    state.mark_synced(["douyin:999"], device_id="phone-1")

    assert state.pending_from_history(settings.download_history_path) == []
    saved = json.loads(Path(settings.sync_state_path).read_text(encoding="utf-8"))
    assert saved["files"]["douyin:999"]["sync_status"] == "synced"
    assert saved["files"]["douyin:999"]["synced_devices"] == ["phone-1"]
    assert file_path.exists()


@pytest.mark.asyncio
async def test_sync_http_api_baselines_existing_downloads_and_lists_new_files(tmp_path):
    settings = make_settings(tmp_path)
    record_download(tmp_path, platform="douyin", video_id="old", filename="old.mp4")
    app = create_sync_app(settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            unauthorized = await client.get("/sync/pending")
            assert unauthorized.status_code == 401

            headers = {"Authorization": "Bearer test-sync-token"}
            initial = await client.get("/sync/pending", headers=headers)
            assert initial.status_code == 200
            assert initial.json()["files"] == []
            initial_state = json.loads(Path(settings.sync_state_path).read_text(encoding="utf-8"))
            assert initial_state["files"] == {}
            assert "baseline_at" in initial_state

            record_download(tmp_path, platform="kuaishou", video_id="abc", filename="clip.mp4")
            pending = await client.get("/sync/pending", headers=headers)
            assert pending.status_code == 200
            payload = pending.json()
            assert payload["files"][0]["id"] == "kuaishou:abc"
            assert payload["files"][0]["download_url"] == "/sync/files/kuaishou%3Aabc"

            file_response = await client.get("/sync/files/kuaishou%3Aabc", headers=headers)
            assert file_response.status_code == 200
            assert file_response.content == b"video-bytes"
            assert file_response.headers["content-type"] == "video/mp4"

            ack = await client.post(
                "/sync/ack",
                headers=headers,
                json={"device_id": "phone-1", "file_ids": ["kuaishou:abc"]},
            )
            assert ack.status_code == 200
            assert ack.json() == {"ok": True, "synced": 1}

            after_ack = await client.get("/sync/pending", headers=headers)
            assert after_ack.json()["files"] == []
    finally:
        await runner.cleanup()
