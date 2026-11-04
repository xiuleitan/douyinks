import json
import os
from pathlib import Path

import httpx
import pytest
from aiohttp.test_utils import TestServer

from douyinks.config import Settings
from douyinks.history import DownloadHistory
from douyinks.platforms.douyin import download as douyin_download
from douyinks.sync_server import create_sync_app
from douyinks.sync_transfer import SyncTransferState


VIDEO_ID = "999999999999"
POST_ID = f"douyin:{VIDEO_ID}"
HEADERS = {"Authorization": "Bearer image-sync-token"}


def make_settings(tmp_path):
    return Settings(str(tmp_path), sync_token="image-sync-token")


def old_baseline(tmp_path):
    path = tmp_path / "sync_state.json"
    path.write_text(json.dumps({"version": 1, "baseline_at": "2020-01-01T00:00:00+00:00", "files": {}}))
    return SyncTransferState(path)


def write_media(tmp_path, filename):
    path = tmp_path / "douyin" / "likes" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(filename.encode())
    return path


@pytest.mark.parametrize("mixed", [False, True])
async def test_all_album_files_can_be_downloaded_and_acknowledged_separately(tmp_path, monkeypatch, mixed):
    settings = make_settings(tmp_path)
    history = DownloadHistory(settings.download_history_path)

    async def download(url, path, referer):
        path.write_bytes(path.name.encode())
        return True

    monkeypatch.setattr(douyin_download, "download_single", download)
    async with TestServer(create_sync_app(settings)) as server, httpx.AsyncClient(trust_env=False) as client:
        result = await douyin_download.download_videos([{
            "aweme_id": VIDEO_ID, "author_douyin_id": "alice", "create_time": 123,
            "media_type": "mixed" if mixed else "image",
            "video_urls": ["https://example.test/clip.mp4"] if mixed else [],
            "image_urls": [f"https://example.test/image.{ext}" for ext in ("jpg", "png", "webp")],
        }], settings.douyin_likes_dir, delay=0, history=history)
        assert result["success"] == 1
        pending = (await client.get(str(server.make_url("/sync/pending")), headers=HEADERS)).json()["files"]
        assert len(pending) == (4 if mixed else 3)
        assert len({item["id"] for item in pending}) == len(pending)
        assert [item["media_type"] for item in pending] == (["video"] if mixed else []) + ["image"] * 3
        assert pending[0]["id"] == POST_ID
        for item in pending:
            url = str(server.make_url(item["download_url"]))
            assert (await client.get(url)).status_code == 401
            response = await client.get(url, headers=HEADERS)
            assert response.content == item["filename"].encode()
            assert response.headers["content-type"].startswith(item["media_type"] + "/")
        response = await client.post(str(server.make_url("/sync/ack")), headers=HEADERS,
                                     json={"device_id": "phone", "file_ids": [pending[0]["id"]]})
        assert response.json() == {"ok": True, "synced": 1}
        remaining = (await client.get(str(server.make_url("/sync/pending")), headers=HEADERS)).json()["files"]
        assert {item["id"] for item in remaining} == {item["id"] for item in pending[1:]}
        assert (await client.get(str(server.make_url("/sync/files/douyin%3A999999999999%3A..%2F.env")),
                                 headers=HEADERS)).status_code == 404
        response = await client.post(str(server.make_url("/sync/ack")), headers=HEADERS,
                                     json={"device_id": "phone", "file_ids": [item["id"] for item in remaining]})
        assert response.json()["synced"] == len(remaining)
        assert (await client.get(str(server.make_url("/sync/pending")), headers=HEADERS)).json() == {"files": []}

    ledger_bytes = Path(settings.sync_state_path).read_bytes()
    create_sync_app(settings)
    assert Path(settings.sync_state_path).read_bytes() == ledger_bytes
    assert SyncTransferState(settings.sync_state_path).pending_from_history(history.path) == []


@pytest.mark.parametrize("first_suffix", ["jpg", "mp4"])
def test_recovery_keeps_legacy_first_file_ack_and_queues_its_siblings(tmp_path, first_suffix):
    settings = make_settings(tmp_path)
    first = write_media(tmp_path, f"alice_123_{VIDEO_ID}_001.{first_suffix}")
    history = DownloadHistory(settings.download_history_path)
    history.record_success("douyin", VIDEO_ID, first, first.name)
    original_time = history.get("douyin", VIDEO_ID)["downloaded_at"]
    state = old_baseline(tmp_path)
    state.mark_synced([POST_ID], "original-phone")
    original_ledger = Path(settings.sync_state_path).read_bytes()
    second = write_media(tmp_path, f"alice_123_{VIDEO_ID}_002.webp")
    third = write_media(tmp_path, f"alice_123_{VIDEO_ID}_003.jpg")

    create_sync_app(settings)

    assert Path(settings.sync_state_path).read_bytes() == original_ledger
    pending = SyncTransferState(settings.sync_state_path).pending_from_history(settings.download_history_path)
    assert {file["filename"] for file in pending} == {second.name, third.name}
    assert all(file["id"] != POST_ID for file in pending)
    updated = DownloadHistory(history.path).get("douyin", VIDEO_ID)
    assert updated["downloaded_at"] == original_time
    assert updated["file_path"] == str(first)
    assert len(updated["files"]) == 3
    for file in pending:
        assert state.file_path_from_history(history.path, file["id"]).name == file["filename"]


def test_unindexed_legacy_images_are_recovered_once_using_original_file_times(tmp_path):
    settings = make_settings(tmp_path)
    state = old_baseline(tmp_path)
    image = write_media(tmp_path, f"some_author_123_{VIDEO_ID}.webp")
    os.utime(image, (1700000000, 1700000000))
    write_media(tmp_path, "cover.jpg")
    write_media(tmp_path, "alice_123_111111111111.mp4")
    (image.parent / "alice_123_222222222222.webp").symlink_to(image)

    create_sync_app(settings)

    history_path = Path(settings.download_history_path)
    history_bytes = history_path.read_bytes()
    pending = state.pending_from_history(history_path)
    assert len(pending) == 1
    assert pending[0]["id"] == POST_ID
    assert pending[0]["media_type"] == "image"
    assert pending[0]["downloaded_at"] == "2023-11-14T22:13:20+00:00"
    assert state.file_path_from_history(history_path, POST_ID) == image
    create_sync_app(settings)
    assert history_path.read_bytes() == history_bytes


def test_first_sync_baseline_still_excludes_images_already_on_disk(tmp_path):
    settings = make_settings(tmp_path)
    write_media(tmp_path, f"alice_123_{VIDEO_ID}.webp")

    create_sync_app(settings)

    assert DownloadHistory(settings.download_history_path).is_successfully_downloaded("douyin", VIDEO_ID)
    assert SyncTransferState(settings.sync_state_path).pending_from_history(settings.download_history_path) == []


@pytest.mark.parametrize("missing_index", [1, 2])
async def test_partial_album_retries_missing_image_without_resending_acknowledged_files(tmp_path, monkeypatch, missing_index):
    settings = make_settings(tmp_path)
    history = DownloadHistory(settings.download_history_path)
    state = old_baseline(tmp_path)
    fail_one = True
    calls = []

    async def download(url, path, referer):
        calls.append(path.name)
        if fail_one and path.stem.endswith(f"_{missing_index:03d}"):
            return False
        path.write_bytes(b"image")
        return True

    monkeypatch.setattr(douyin_download, "download_single", download)
    post = {"aweme_id": VIDEO_ID, "author_douyin_id": "alice", "create_time": 123,
            "media_type": "image", "image_urls": [f"https://example.test/{i}.jpg" for i in range(3)]}
    first = await douyin_download.download_videos([post], settings.douyin_likes_dir, delay=0, history=history)
    assert first["failed"] == 1
    assert not history.is_successfully_downloaded("douyin", VIDEO_ID)
    pending = state.pending_from_history(history.path)
    assert len(pending) == 2
    state.mark_synced([pending[0]["id"]], "phone")
    third_id = pending[1]["id"]
    create_sync_app(settings)
    assert DownloadHistory(history.path).get("douyin", VIDEO_ID)["status"] == "partial"

    fail_one = False
    calls.clear()
    second = await douyin_download.download_videos([post], settings.douyin_likes_dir, delay=0, history=history)

    assert second["success"] == 1
    missing_name = f"alice_123_{VIDEO_ID}_{missing_index:03d}.jpg"
    assert calls == [missing_name]
    remaining = state.pending_from_history(history.path)
    assert {file["filename"] for file in remaining} == {missing_name, f"alice_123_{VIDEO_ID}_003.jpg"}
    assert third_id in {file["id"] for file in remaining}
    assert history.is_successfully_downloaded("douyin", VIDEO_ID)
    (Path(settings.douyin_likes_dir) / missing_name).unlink()
    assert not history.is_successfully_downloaded("douyin", VIDEO_ID)


async def test_legacy_first_image_record_does_not_skip_missing_album_images(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    first = write_media(tmp_path, f"alice_123_{VIDEO_ID}_001.jpg")
    history = DownloadHistory(settings.download_history_path)
    history.record_success("douyin", VIDEO_ID, first, first.name)
    calls = []

    async def download(url, path, referer):
        calls.append(path.name)
        path.write_bytes(b"image")
        return True

    monkeypatch.setattr(douyin_download, "download_single", download)
    result = await douyin_download.download_videos([{
        "aweme_id": VIDEO_ID, "author_douyin_id": "alice", "create_time": 123,
        "media_type": "image", "image_urls": ["https://example.test/1.jpg", "https://example.test/2.jpg"],
    }], settings.douyin_likes_dir, delay=0, history=history)

    assert result["success"] == 1
    assert calls == [f"alice_123_{VIDEO_ID}_002.jpg"]
    assert len(history.get("douyin", VIDEO_ID)["files"]) == 2


def test_corrupt_download_history_is_not_overwritten_by_image_recovery(tmp_path):
    settings = make_settings(tmp_path)
    write_media(tmp_path, f"alice_123_{VIDEO_ID}.webp")
    path = Path(settings.download_history_path)
    path.write_text("{broken original history")

    with pytest.raises(ValueError, match="保留"):
        create_sync_app(settings)

    assert path.read_text() == "{broken original history"
    assert not Path(settings.sync_state_path).exists()
