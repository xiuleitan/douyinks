import pytest

from douyinks.history import DownloadHistory
from douyinks.platforms.douyin import download as douyin_download
from douyinks.platforms.kuaishou import download as kuaishou_download


@pytest.mark.asyncio
async def test_douyin_download_skips_video_already_in_history(tmp_path, monkeypatch):
    output_dir = tmp_path / "douyin" / "likes"
    output_dir.mkdir(parents=True)
    existing = output_dir / "alice_123_999999999999.mp4"
    existing.write_bytes(b"old")
    history = DownloadHistory(tmp_path / "download_history.json")
    history.record_success("douyin", "999999999999", existing, existing.name)

    async def fail_download(*args, **kwargs):
        raise AssertionError("download should not be called")

    monkeypatch.setattr(douyin_download, "download_single", fail_download)

    result = await douyin_download.download_videos(
        [{
            "aweme_id": "999999999999",
            "author_douyin_id": "alice",
            "create_time": 123,
            "play_url": "https://example.test/video.mp4",
        }],
        str(output_dir),
        history=history,
    )

    assert result["success"] == 0
    assert result["skipped"] == 1
    assert result["items"] == [{"filename": "alice_123_999999999999.mp4", "success": False, "status": "skipped"}]


@pytest.mark.asyncio
async def test_douyin_download_skips_identical_filename_and_backfills_history(tmp_path, monkeypatch):
    output_dir = tmp_path / "douyin" / "likes"
    output_dir.mkdir(parents=True)
    existing = output_dir / "alice_123_999999999999.mp4"
    existing.write_bytes(b"old")
    history = DownloadHistory(tmp_path / "download_history.json")

    async def fail_download(*args, **kwargs):
        raise AssertionError("download should not be called")

    monkeypatch.setattr(douyin_download, "download_single", fail_download)

    result = await douyin_download.download_videos(
        [{
            "aweme_id": "999999999999",
            "author_douyin_id": "alice",
            "create_time": 123,
            "play_url": "https://example.test/video.mp4",
        }],
        str(output_dir),
        history=history,
    )

    assert result["skipped"] == 1
    assert history.is_successfully_downloaded("douyin", "999999999999")
    assert result["items"] == [{"filename": "alice_123_999999999999.mp4", "success": False, "status": "skipped"}]


@pytest.mark.asyncio
async def test_douyin_download_records_history_after_success(tmp_path, monkeypatch):
    output_dir = tmp_path / "douyin" / "likes"
    history = DownloadHistory(tmp_path / "download_history.json")

    async def fake_download(_url, output_path, referer):
        output_path.write_bytes(b"new")
        return True

    monkeypatch.setattr(douyin_download, "download_single", fake_download)

    result = await douyin_download.download_videos(
        [{
            "aweme_id": "999999999999",
            "author_douyin_id": "alice",
            "create_time": 123,
            "play_url": "https://example.test/video.mp4",
        }],
        str(output_dir),
        delay=0,
        history=history,
    )

    assert result["success"] == 1
    assert history.is_successfully_downloaded("douyin", "999999999999")
    assert result["items"] == [{"filename": "alice_123_999999999999.mp4", "success": True, "status": "success"}]


@pytest.mark.asyncio
async def test_douyin_download_saves_all_images_with_video_style_names(tmp_path, monkeypatch):
    output_dir = tmp_path / "douyin" / "likes"
    history = DownloadHistory(tmp_path / "download_history.json")
    downloaded = []

    async def fake_download(url, output_path, referer):
        downloaded.append((url, output_path.name, referer))
        output_path.write_bytes(b"image")
        return True

    monkeypatch.setattr(douyin_download, "download_single", fake_download)

    result = await douyin_download.download_videos(
        [{
            "aweme_id": "999999999999",
            "author_douyin_id": "alice",
            "create_time": 123,
            "media_type": "image",
            "image_urls": [
                "https://example.test/one.jpeg",
                "https://example.test/two.webp",
            ],
        }],
        str(output_dir),
        delay=0,
        history=history,
    )

    assert downloaded == [
        ("https://example.test/one.jpeg", "alice_123_999999999999_001.jpeg", "https://www.douyin.com/"),
        ("https://example.test/two.webp", "alice_123_999999999999_002.webp", "https://www.douyin.com/"),
    ]
    assert result["success"] == 1
    assert result["items"] == [
        {"filename": "alice_123_999999999999_001.jpeg", "success": True, "status": "success"},
        {"filename": "alice_123_999999999999_002.webp", "success": True, "status": "success"},
    ]
    assert history.is_successfully_downloaded("douyin", "999999999999")


@pytest.mark.asyncio
async def test_douyin_download_saves_child_videos_with_indexed_names(tmp_path, monkeypatch):
    output_dir = tmp_path / "douyin" / "likes"
    history = DownloadHistory(tmp_path / "download_history.json")
    downloaded = []

    async def fake_download(url, output_path, referer):
        downloaded.append((url, output_path.name, referer))
        output_path.write_bytes(b"video")
        return True

    monkeypatch.setattr(douyin_download, "download_single", fake_download)

    result = await douyin_download.download_videos(
        [{
            "aweme_id": "999999999999",
            "author_douyin_id": "alice",
            "create_time": 123,
            "media_type": "mixed",
            "video_urls": [
                "https://example.test/one.mp4",
                "https://example.test/two.mp4",
            ],
        }],
        str(output_dir),
        delay=0,
        history=history,
    )

    assert downloaded == [
        ("https://example.test/one.mp4", "alice_123_999999999999_001.mp4", "https://www.douyin.com/"),
        ("https://example.test/two.mp4", "alice_123_999999999999_002.mp4", "https://www.douyin.com/"),
    ]
    assert result["success"] == 1
    assert result["items"] == [
        {"filename": "alice_123_999999999999_001.mp4", "success": True, "status": "success"},
        {"filename": "alice_123_999999999999_002.mp4", "success": True, "status": "success"},
    ]
    assert history.is_successfully_downloaded("douyin", "999999999999")


@pytest.mark.asyncio
async def test_kuaishou_download_uses_history_for_photo_id(tmp_path, monkeypatch):
    output_dir = tmp_path / "kuaishou" / "likes"
    output_dir.mkdir(parents=True)
    existing = output_dir / "author_456_abc123.mp4"
    existing.write_bytes(b"old")
    history = DownloadHistory(tmp_path / "download_history.json")
    history.record_success("kuaishou", "abc123", existing, existing.name)

    async def fail_download(*args, **kwargs):
        raise AssertionError("download should not be called")

    monkeypatch.setattr(kuaishou_download, "download_single", fail_download)

    result = await kuaishou_download.download_videos(
        [{
            "photo_id": "abc123",
            "author_id": "author",
            "timestamp": 456,
            "play_url": "https://example.test/video.mp4",
        }],
        str(output_dir),
        history=history,
    )

    assert result["success"] == 0
    assert result["skipped"] == 1
    assert result["items"] == [{"filename": "author_456_abc123.mp4", "success": False, "status": "skipped"}]
