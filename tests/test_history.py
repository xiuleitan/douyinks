from pathlib import Path

from douyinks.history import DownloadHistory


def test_download_history_records_successful_download(tmp_path):
    history_path = tmp_path / "download_history.json"
    video_path = tmp_path / "douyin" / "likes" / "author_123_999.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")

    history = DownloadHistory(history_path)
    history.record_success(
        platform="douyin",
        video_id="999",
        file_path=video_path,
        filename=video_path.name,
    )

    loaded = DownloadHistory(history_path)
    assert loaded.is_successfully_downloaded("douyin", "999")
    assert loaded.get("douyin", "999")["filename"] == "author_123_999.mp4"


def test_download_history_ignores_missing_files(tmp_path):
    history_path = tmp_path / "download_history.json"
    missing_path = tmp_path / "missing.mp4"

    history = DownloadHistory(history_path)
    history.record_success(
        platform="kuaishou",
        video_id="abc",
        file_path=missing_path,
        filename=missing_path.name,
    )

    loaded = DownloadHistory(history_path)
    assert not loaded.is_successfully_downloaded("kuaishou", "abc")


def test_separate_downloaders_preserve_each_others_history(tmp_path):
    history_path = tmp_path / "download_history.json"
    douyin = DownloadHistory(history_path)
    kuaishou = DownloadHistory(history_path)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    douyin.record_success("douyin", "first", video, video.name)
    kuaishou.record_success("kuaishou", "first", video, video.name)
    douyin.record_success("douyin", "second", video, video.name)

    loaded = DownloadHistory(history_path)
    assert loaded.is_successfully_downloaded("douyin", "first")
    assert loaded.is_successfully_downloaded("kuaishou", "first")
    assert loaded.is_successfully_downloaded("douyin", "second")


def test_stale_downloader_does_not_restore_another_platforms_old_record(tmp_path):
    history_path = tmp_path / "download_history.json"
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    kuaishou = DownloadHistory(history_path)
    kuaishou.record_success("kuaishou", "first", video, "old.mp4")
    douyin = DownloadHistory(history_path)

    kuaishou.record_success("kuaishou", "first", video, "updated.mp4")
    douyin.record_success("douyin", "first", video, video.name)

    loaded = DownloadHistory(history_path)
    assert loaded.get("kuaishou", "first")["filename"] == "updated.mp4"
