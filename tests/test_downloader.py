import pytest

from douyinks.config import Settings
from douyinks.commands import DownloadCommand
from douyinks.downloader import DownloadService, build_daemon_command


def test_build_daemon_command_uses_configured_host_and_port():
    settings = Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": "/tmp/downloads",
            "DOUYINKS_DAEMON_HOST": "127.0.0.2",
            "DOUYINKS_DAEMON_PORT": "19999",
        }
    )

    command = build_daemon_command(settings)

    assert command[-4:] == ["--host", "127.0.0.2", "--port", "19999"]


@pytest.mark.asyncio
async def test_wait_for_extension_connection_retries_until_connected(monkeypatch):
    settings = Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": "/tmp/downloads",
        }
    )
    service = DownloadService(settings)
    statuses = [
        {"extensionConnected": False},
        {"extensionConnected": False},
        {"extensionConnected": True},
    ]
    sleep_calls = []

    async def fake_status():
        return statuses.pop(0)

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(service, "status", fake_status)
    monkeypatch.setattr("douyinks.downloader.asyncio.sleep", fake_sleep)

    await service.wait_for_extension_connection(timeout=3)

    assert sleep_calls == [1.0, 1.0]


@pytest.mark.asyncio
async def test_downloader_downloads_kuaishou_captured_likes(monkeypatch, tmp_path):
    settings = Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": str(tmp_path),
        }
    )
    service = DownloadService(settings)
    captured = [{"photo_id": "p1", "play_url": "https://example.test/1.mp4", "author_id": "a1"}]
    received = {}

    async def fake_read_captured(page, limit):
        received["workspace"] = page.workspace
        received["limit"] = limit
        return captured

    async def fake_download_videos(videos, output_dir, **kwargs):
        received["videos"] = videos
        received["output_dir"] = output_dir
        return {"success": 1, "failed": 0, "skipped": 0, "items": [{"filename": "p1.mp4", "success": True}]}

    monkeypatch.setattr("douyinks.platforms.kuaishou.liked.read_captured", fake_read_captured)
    monkeypatch.setattr("douyinks.platforms.kuaishou.download.download_videos", fake_download_videos)

    result = await service.run(DownloadCommand(platform="kuaishou", source="captured", count=1))

    assert received["limit"] == 1
    assert received["videos"] == captured
    assert received["output_dir"] == settings.kuaishou_likes_dir
    assert result["source"] == "captured"
    assert result["success"] == 1


@pytest.mark.asyncio
async def test_downloader_downloads_douyin_like_range(monkeypatch, tmp_path):
    settings = Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": str(tmp_path),
        }
    )
    service = DownloadService(settings)
    received = {"detail_ids": []}

    async def noop():
        return None

    async def fake_scrape_ids(page, limit):
        received["scrape_limit"] = limit
        return [f"id-{index}" for index in range(1, limit + 1)]

    async def fake_detail_run(page, aweme_id):
        received["detail_ids"].append(aweme_id)
        return [{"aweme_id": aweme_id, "download_url": f"https://example.test/{aweme_id}.mp4"}]

    async def fake_download_videos(videos, output_dir, **kwargs):
        received["videos"] = videos
        received["output_dir"] = output_dir
        received["max_count"] = kwargs["max_count"]
        return {"success": len(videos), "failed": 0, "skipped": 0, "items": []}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("douyinks.platforms.douyin.scrape_ids.run", fake_scrape_ids)
    monkeypatch.setattr("douyinks.platforms.douyin.detail.run", fake_detail_run)
    monkeypatch.setattr("douyinks.platforms.douyin.download.download_videos", fake_download_videos)
    monkeypatch.setattr("douyinks.downloader.asyncio.sleep", no_sleep)
    monkeypatch.setattr(service, "ensure_daemon", noop)
    monkeypatch.setattr(service, "wait_for_extension_connection", noop)

    result = await service.run(DownloadCommand(platform="douyin", source="like", count=41, range_start=60, range_end=100))

    assert received["scrape_limit"] == 100
    assert received["detail_ids"][0] == "id-60"
    assert received["detail_ids"][-1] == "id-100"
    assert len(received["detail_ids"]) == 41
    assert received["max_count"] == 41
    assert result["requested"] == 41
    assert result["range"] == "60-100"
