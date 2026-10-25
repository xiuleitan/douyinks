import pytest

from douyinks.history import DownloadHistory
from douyinks.platforms.douyin import download as douyin_download
from douyinks.platforms.kuaishou import download as kuaishou_download


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,downloader,id_key", [
    ("douyin", douyin_download, "aweme_id"),
    ("kuaishou", kuaishou_download, "photo_id"),
])
async def test_progress_counts_success_failure_and_skips_in_selected_batch(tmp_path, monkeypatch, platform, downloader, id_key):
    output_dir = tmp_path / platform
    output_dir.mkdir()
    existing = output_dir / "author_1_existing.mp4"
    existing.write_bytes(b"existing")
    history = DownloadHistory(tmp_path / "history.json")
    history.record_success(platform, "existing", existing, existing.name)
    snapshots = []

    async def download(url, path, referer):
        if url.endswith("/failed"):
            return False
        path.write_bytes(b"downloaded")
        return True

    def progress(completed, total, result):
        snapshots.append((completed, total, result["success"], result["failed"], result["skipped"]))

    monkeypatch.setattr(downloader, "download_single", download)
    videos = [{id_key: name, "play_url": f"https://example.test/{name}"}
              for name in ("existing", "success", "failed", "outside-selected-batch")]

    result = await downloader.download_videos(videos, str(output_dir), delay=0, max_count=3,
                                              history=history, progress=progress)

    assert snapshots == [(0, 3, 0, 0, 0), (1, 3, 0, 0, 1), (2, 3, 1, 0, 1), (3, 3, 1, 1, 1)]
    assert (result["success"], result["failed"], result["skipped"]) == (1, 1, 1)
