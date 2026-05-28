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
