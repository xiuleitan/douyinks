import json

import pytest

from douyinks.config import Settings
from douyinks.platforms.douyin import detail as douyin_detail
from douyinks.platforms.douyin import download as douyin_download
import douyinks.unknown_redownload as unknown_redownload
from douyinks.unknown_redownload import find_unknown_history_items, redownload_unknown_history


def make_settings(tmp_path):
    return Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": str(tmp_path),
        }
    )


def write_history(path, downloads):
    path.write_text(json.dumps({"version": 1, "downloads": downloads}, ensure_ascii=False), encoding="utf-8")


def test_find_unknown_history_items_filters_platform_and_range(tmp_path):
    history_path = tmp_path / "download_history.json"
    write_history(
        history_path,
        {
            "douyin:1": {"platform": "douyin", "video_id": "1", "filename": "unknown_1.mp4", "status": "success"},
            "kuaishou:2": {"platform": "kuaishou", "video_id": "2", "filename": "unknown_2.mp4", "status": "success"},
            "douyin:3": {"platform": "douyin", "video_id": "3", "filename": "alice_3.mp4", "status": "success"},
            "douyin:4": {"platform": "douyin", "video_id": "4", "file_path": "/tmp/unknown_4.mp4", "status": "success"},
        },
    )

    items = find_unknown_history_items(history_path, platform="douyin", line_range="2-2")

    assert [item["video_id"] for item in items] == ["4"]


@pytest.mark.asyncio
async def test_redownload_unknown_history_downloads_douyin_range_to_separate_folder(tmp_path, monkeypatch):
    history_path = tmp_path / "download_history.json"
    output_root = tmp_path / "fixed"
    write_history(
        history_path,
        {
            "douyin:1": {"platform": "douyin", "video_id": "1", "filename": "unknown_1.mp4", "status": "success"},
            "douyin:2": {"platform": "douyin", "video_id": "2", "filename": "unknown_2.mp4", "status": "success"},
        },
    )
    settings = make_settings(tmp_path)
    calls = []

    async def fake_ensure_daemon(self):
        calls.append("ensure_daemon")

    async def fake_wait_for_extension(self):
        calls.append("wait_for_extension")

    async def fake_prepare_page(_page):
        calls.append("prepare_page")

    async def fake_detail_run(_page, aweme_id):
        return [{
            "aweme_id": aweme_id,
            "author_douyin_id": "alice",
            "create_time": 123,
            "play_url": f"https://example.test/{aweme_id}.mp4",
        }]

    async def fake_download_videos(videos, output_dir, delay, max_count, history):
        calls.append((videos[0]["aweme_id"], output_dir, history))
        return {
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "files": [f"{output_dir}/{videos[0]['aweme_id']}.mp4"],
            "items": [{"filename": f"{videos[0]['aweme_id']}.mp4", "success": True, "status": "success"}],
        }

    monkeypatch.setattr("douyinks.unknown_redownload.DownloadService.ensure_daemon", fake_ensure_daemon)
    monkeypatch.setattr("douyinks.unknown_redownload.DownloadService.wait_for_extension_connection", fake_wait_for_extension)
    monkeypatch.setattr(unknown_redownload, "prepare_douyin_page", fake_prepare_page)
    monkeypatch.setattr(douyin_detail, "run", fake_detail_run)
    monkeypatch.setattr(douyin_download, "download_videos", fake_download_videos)

    result = await redownload_unknown_history(
        settings,
        history_path,
        platform="douyin",
        line_range="2-2",
        output_dir=output_root,
        delay=0,
    )

    assert calls[0:2] == ["ensure_daemon", "wait_for_extension"]
    assert calls[2] == "prepare_page"
    assert calls[3] == ("2", str(output_root / "douyin"), None)
    assert result["requested"] == 1
    assert result["success"] == 1
    assert result["output_dir"] == str(output_root / "douyin")
