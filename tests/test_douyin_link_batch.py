import json

import pytest

from douyinks.config import Settings
from douyinks.browser import BrowserCommandError
from douyinks.platforms.douyin import link_batch


def make_settings(tmp_path):
    return Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": str(tmp_path / "downloads"),
        }
    )


@pytest.mark.asyncio
async def test_download_links_file_skips_success_progress_and_retries_failed(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    links_file = tmp_path / "links.txt"
    links_file.write_text(
        "\n".join(
            [
                "//www.douyin.com/video/1111111111111",
                "/video/2222222222222",
                "/note/3333333333333",
            ]
        ),
        encoding="utf-8",
    )
    progress_file = tmp_path / "progress.json"
    progress_file.write_text(
        json.dumps(
            {
                "version": 1,
                "links": {
                    "//www.douyin.com/video/1111111111111": {"status": "success", "aweme_id": "1111111111111"},
                    "/video/2222222222222": {"status": "failed", "aweme_id": "2222222222222"},
                },
            }
        ),
        encoding="utf-8",
    )
    processed_ids = []
    sleep_delays = []

    async def fake_detail_run(_page, aweme_id):
        processed_ids.append(aweme_id)
        return [{"aweme_id": aweme_id, "play_url": f"https://example.test/{aweme_id}.mp4"}]

    async def fake_download_videos(videos, output_dir, delay, max_count, history):
        return {
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "files": [f"{output_dir}/{videos[0]['aweme_id']}.mp4"],
            "items": [{"filename": f"{videos[0]['aweme_id']}.mp4", "success": True, "status": "success"}],
        }

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    monkeypatch.setattr(link_batch.detail, "run", fake_detail_run)
    monkeypatch.setattr(link_batch.download, "download_videos", fake_download_videos)
    monkeypatch.setattr(link_batch.asyncio, "sleep", fake_sleep)

    result = await link_batch.download_links_file(
        settings,
        links_file,
        delay=1.0,
        progress_path=progress_file,
        ensure_daemon=False,
    )

    assert processed_ids == ["2222222222222", "3333333333333"]
    assert sleep_delays == [1.0]
    assert result["requested"] == 3
    assert result["processed"] == 2
    assert result["already_done"] == 1
    assert result["success"] == 2
    assert result["failed"] == 0
    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    assert progress["links"]["//www.douyin.com/video/1111111111111"]["status"] == "success"
    assert progress["links"]["/video/2222222222222"]["status"] == "success"
    assert progress["links"]["/note/3333333333333"]["status"] == "success"


@pytest.mark.asyncio
async def test_download_links_file_records_detail_failures_and_continues(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    links_file = tmp_path / "links.txt"
    links_file.write_text("/video/4444444444444\n/video/5555555555555\n", encoding="utf-8")
    progress_file = tmp_path / "progress.json"
    processed_ids = []

    async def fake_detail_run(_page, aweme_id):
        processed_ids.append(aweme_id)
        if aweme_id == "4444444444444":
            raise RuntimeError("detail failed")
        return [{"aweme_id": aweme_id, "play_url": f"https://example.test/{aweme_id}.mp4"}]

    async def fake_download_videos(videos, output_dir, delay, max_count, history):
        return {
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "files": [],
            "items": [{"filename": f"{videos[0]['aweme_id']}.mp4", "success": True, "status": "success"}],
        }

    monkeypatch.setattr(link_batch.detail, "run", fake_detail_run)
    monkeypatch.setattr(link_batch.download, "download_videos", fake_download_videos)
    monkeypatch.setattr(link_batch.asyncio, "sleep", lambda _delay: _completed_sleep())

    result = await link_batch.download_links_file(
        settings,
        links_file,
        delay=1.0,
        progress_path=progress_file,
        ensure_daemon=False,
    )

    assert processed_ids == ["4444444444444", "5555555555555"]
    assert result["success"] == 1
    assert result["failed"] == 1
    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    assert progress["links"]["/video/4444444444444"]["status"] == "failed"
    assert progress["links"]["/video/5555555555555"]["status"] == "success"


@pytest.mark.asyncio
async def test_download_links_file_limits_links_by_file_line_range(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    links_file = tmp_path / "links.txt"
    links_file.write_text(
        "\n".join(
            [
                "/video/1000000000001",
                "",
                "/video/1000000000002",
                "# /video/1000000000003",
                "/video/1000000000004",
            ]
        ),
        encoding="utf-8",
    )
    progress_file = tmp_path / "progress.json"
    processed_ids = []

    async def fake_detail_run(_page, aweme_id):
        processed_ids.append(aweme_id)
        return [{"aweme_id": aweme_id, "play_url": f"https://example.test/{aweme_id}.mp4"}]

    async def fake_download_videos(videos, output_dir, delay, max_count, history):
        return {
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "files": [],
            "items": [{"filename": f"{videos[0]['aweme_id']}.mp4", "success": True, "status": "success"}],
        }

    monkeypatch.setattr(link_batch.detail, "run", fake_detail_run)
    monkeypatch.setattr(link_batch.download, "download_videos", fake_download_videos)

    result = await link_batch.download_links_file(
        settings,
        links_file,
        delay=0,
        progress_path=progress_file,
        ensure_daemon=False,
        line_range="2-5",
    )

    assert processed_ids == ["1000000000002", "1000000000004"]
    assert result["requested"] == 2
    assert result["processed"] == 2


def test_parse_line_range_rejects_invalid_ranges():
    with pytest.raises(ValueError, match="范围格式"):
        link_batch.parse_line_range("1:")
    with pytest.raises(ValueError, match="大于等于 1"):
        link_batch.parse_line_range("0-10")
    with pytest.raises(ValueError, match="不能大于"):
        link_batch.parse_line_range("10-1")


@pytest.mark.asyncio
async def test_download_links_file_stops_without_recording_when_extension_disconnects(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    links_file = tmp_path / "links.txt"
    links_file.write_text("/video/6666666666666\n/video/7777777777777\n", encoding="utf-8")
    progress_file = tmp_path / "progress.json"

    async def fake_detail_run(_page, aweme_id):
        raise BrowserCommandError("Extension not connected. Load the Douyinks Browser Bridge extension.")

    monkeypatch.setattr(link_batch.detail, "run", fake_detail_run)

    with pytest.raises(RuntimeError, match="浏览器扩展未连接"):
        await link_batch.download_links_file(
            settings,
            links_file,
            delay=1.0,
            progress_path=progress_file,
            ensure_daemon=False,
        )

    assert not progress_file.exists()


@pytest.mark.asyncio
async def test_download_links_file_waits_for_extension_connection(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    links_file = tmp_path / "links.txt"
    links_file.write_text("/video/8888888888888\n", encoding="utf-8")
    progress_file = tmp_path / "progress.json"
    statuses = [{"extensionConnected": False}, {"extensionConnected": True}]
    sleep_delays = []
    pages = []

    async def fake_ensure_daemon(self):
        return None

    async def fake_status(self):
        return statuses.pop(0)

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    async def fake_detail_run(_page, aweme_id):
        return [{"aweme_id": aweme_id, "play_url": f"https://example.test/{aweme_id}.mp4"}]

    async def fake_download_videos(videos, output_dir, delay, max_count, history):
        return {
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "files": [],
            "items": [{"filename": f"{videos[0]['aweme_id']}.mp4", "success": True, "status": "success"}],
        }

    class FakeBrowserPage:
        def __init__(self, **_kwargs):
            self.gotourls = []
            self.waits = []
            pages.append(self)

        async def goto(self, url):
            self.gotourls.append(url)

        async def wait(self, seconds):
            self.waits.append(seconds)

    monkeypatch.setattr(link_batch.DownloadService, "ensure_daemon", fake_ensure_daemon)
    monkeypatch.setattr(link_batch.DownloadService, "status", fake_status)
    monkeypatch.setattr(link_batch, "BrowserPage", FakeBrowserPage)
    monkeypatch.setattr(link_batch.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(link_batch.detail, "run", fake_detail_run)
    monkeypatch.setattr(link_batch.download, "download_videos", fake_download_videos)

    result = await link_batch.download_links_file(
        settings,
        links_file,
        delay=1.0,
        progress_path=progress_file,
        ensure_daemon=True,
    )

    assert sleep_delays == [1.0]
    assert pages[0].gotourls == ["https://www.douyin.com/"]
    assert pages[0].waits == [1.0]
    assert result["success"] == 1


@pytest.mark.asyncio
async def test_download_links_file_retries_transient_fetch_errors(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    links_file = tmp_path / "links.txt"
    links_file.write_text("/video/9999999999999\n", encoding="utf-8")
    progress_file = tmp_path / "progress.json"
    attempts = []
    pages = []
    sleep_delays = []

    class FakeBrowserPage:
        def __init__(self, **_kwargs):
            self.gotourls = []
            self.waits = []
            pages.append(self)

        async def goto(self, url):
            self.gotourls.append(url)

        async def wait(self, seconds):
            self.waits.append(seconds)

    async def fake_detail_run(_page, aweme_id):
        attempts.append(aweme_id)
        if len(attempts) == 1:
            raise RuntimeError("TypeError: Failed to fetch\n    at <anonymous>:3:25")
        return [{"aweme_id": aweme_id, "play_url": f"https://example.test/{aweme_id}.mp4"}]

    async def fake_download_videos(videos, output_dir, delay, max_count, history):
        return {
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "files": [],
            "items": [{"filename": f"{videos[0]['aweme_id']}.mp4", "success": True, "status": "success"}],
        }

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    monkeypatch.setattr(link_batch, "BrowserPage", FakeBrowserPage)
    monkeypatch.setattr(link_batch.detail, "run", fake_detail_run)
    monkeypatch.setattr(link_batch.download, "download_videos", fake_download_videos)
    monkeypatch.setattr(link_batch.asyncio, "sleep", fake_sleep)

    result = await link_batch.download_links_file(
        settings,
        links_file,
        delay=1.0,
        progress_path=progress_file,
        ensure_daemon=False,
    )

    assert attempts == ["9999999999999", "9999999999999"]
    assert pages[0].gotourls == ["https://www.douyin.com/"]
    assert sleep_delays == [3.0]
    assert result["success"] == 1


@pytest.mark.asyncio
async def test_download_links_file_stops_after_too_many_consecutive_fetch_failures(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    links_file = tmp_path / "links.txt"
    links_file.write_text(
        "\n".join(
            [
                "/video/1000000000001",
                "/video/1000000000002",
                "/video/1000000000003",
            ]
        ),
        encoding="utf-8",
    )
    progress_file = tmp_path / "progress.json"

    async def fake_detail_run(_page, aweme_id):
        raise RuntimeError("TypeError: Failed to fetch\n    at <anonymous>:3:25")

    monkeypatch.setattr(link_batch.detail, "run", fake_detail_run)
    monkeypatch.setattr(link_batch.asyncio, "sleep", lambda _delay: _completed_sleep())

    with pytest.raises(RuntimeError, match="连续 2 条链接详情请求失败"):
        await link_batch.download_links_file(
            settings,
            links_file,
            delay=1.0,
            progress_path=progress_file,
            ensure_daemon=False,
            detail_retries=1,
            max_consecutive_detail_failures=2,
        )

    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    assert len(progress["links"]) == 2
    assert progress["links"]["/video/1000000000001"]["status"] == "failed"
    assert progress["links"]["/video/1000000000002"]["status"] == "failed"
    assert "/video/1000000000003" not in progress["links"]


async def _completed_sleep():
    return None
