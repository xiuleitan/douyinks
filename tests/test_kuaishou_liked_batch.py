import json

import pytest
from click.testing import CliRunner

from douyinks.config import Settings
from douyinks.main import cli
from douyinks.platforms.kuaishou.browser_fetch import KuaishouAPIError
from douyinks.platforms.kuaishou import liked_batch


def make_settings(tmp_path):
    return Settings.from_mapping({
        "MATRIX_HOMESERVER_URL": "https://matrix.example",
        "MATRIX_USERNAME": "@bot:example",
        "MATRIX_PASSWORD": "secret",
        "MATRIX_ALLOWED_ROOM_IDS": "!room:example",
        "DOWNLOAD_ROOT": str(tmp_path / "downloads"),
    })


@pytest.mark.asyncio
async def test_export_liked_file_writes_jsonl_until_no_more(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    output = tmp_path / "kuaishou_liked.jsonl"
    calls = []

    async def fake_fetch_page(page, pcursor):
        calls.append(pcursor)
        if pcursor == "":
            return {
                "pcursor": "cursor-2",
                "feeds": [{
                    "photo_id": "p1",
                    "author_id": "a1",
                    "caption": "first",
                    "timestamp": 111,
                    "play_url": "https://example.test/1.mp4",
                }],
            }
        return {
            "pcursor": "no_more",
            "feeds": [{
                "photo_id": "p2",
                "author_id": "a2",
                "caption": "second",
                "timestamp": 222,
                "play_url": "https://example.test/2.mp4",
            }],
        }

    monkeypatch.setattr(liked_batch, "_fetch_liked_page", fake_fetch_page)

    result = await liked_batch.export_liked_file(settings, output, ensure_daemon=False, page_delay=0)

    assert calls == ["", "cursor-2"]
    assert result == {"output_file": str(output), "exported": 2, "pages": 2, "existing": 0}
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "index": 1,
            "photo_id": "p1",
            "author_id": "a1",
            "caption": "first",
            "timestamp": 111,
            "play_url": "https://example.test/1.mp4",
            "pcursor": "",
        },
        {
            "index": 2,
            "photo_id": "p2",
            "author_id": "a2",
            "caption": "second",
            "timestamp": 222,
            "play_url": "https://example.test/2.mp4",
            "pcursor": "cursor-2",
        },
    ]


@pytest.mark.asyncio
async def test_export_liked_file_ensures_daemon_by_default(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    events = []

    class FakeService:
        def __init__(self, service_settings):
            assert service_settings is settings

        async def ensure_daemon(self):
            events.append("daemon")

    async def fake_wait_for_extension_connection(service):
        events.append("extension")

    async def fake_fetch_page(page, pcursor):
        return {"pcursor": "no_more", "feeds": []}

    monkeypatch.setattr(liked_batch, "DownloadService", FakeService)
    monkeypatch.setattr(liked_batch, "wait_for_extension_connection", fake_wait_for_extension_connection)
    monkeypatch.setattr(liked_batch, "_fetch_liked_page", fake_fetch_page)

    await liked_batch.export_liked_file(settings, tmp_path / "kuaishou_liked.jsonl")

    assert events == ["daemon", "extension"]


@pytest.mark.asyncio
async def test_export_liked_file_resumes_existing_file_without_duplicates(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    output = tmp_path / "kuaishou_liked.jsonl"
    output.write_text(
        "\n".join([
            json.dumps({
                "index": 1,
                "photo_id": "p1",
                "author_id": "a1",
                "timestamp": 111,
                "play_url": "https://example.test/1.mp4",
                "pcursor": "",
            }),
            json.dumps({
                "index": 2,
                "photo_id": "p2",
                "author_id": "a2",
                "timestamp": 222,
                "play_url": "https://example.test/2.mp4",
                "pcursor": "cursor-2",
            }),
        ]) + "\n",
        encoding="utf-8",
    )
    calls = []

    async def fake_fetch_page(page, pcursor):
        calls.append(pcursor)
        if pcursor == "cursor-2":
            return {
                "pcursor": "cursor-3",
                "feeds": [
                    {
                        "photo_id": "p2",
                        "author_id": "a2",
                        "timestamp": 222,
                        "play_url": "https://example.test/2.mp4",
                    },
                    {
                        "photo_id": "p3",
                        "author_id": "a3",
                        "timestamp": 333,
                        "play_url": "https://example.test/3.mp4",
                    },
                ],
            }
        return {"pcursor": "no_more", "feeds": []}

    monkeypatch.setattr(liked_batch, "_fetch_liked_page", fake_fetch_page)

    result = await liked_batch.export_liked_file(settings, output, ensure_daemon=False, page_delay=0)

    assert calls == ["cursor-2", "cursor-3"]
    assert result["existing"] == 2
    assert result["exported"] == 1
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["photo_id"] for row in rows] == ["p1", "p2", "p3"]
    assert rows[-1]["index"] == 3


@pytest.mark.asyncio
async def test_export_liked_file_returns_partial_result_on_api_error(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    output = tmp_path / "kuaishou_liked.jsonl"

    async def fake_fetch_page(page, pcursor):
        if pcursor == "":
            return {
                "pcursor": "cursor-2",
                "feeds": [{
                    "photo_id": "p1",
                    "author_id": "a1",
                    "timestamp": 111,
                    "play_url": "https://example.test/1.mp4",
                }],
            }
        raise KuaishouAPIError("Kuaishou API error 2: None")

    monkeypatch.setattr(liked_batch, "_fetch_liked_page", fake_fetch_page)

    result = await liked_batch.export_liked_file(settings, output, ensure_daemon=False, page_delay=0)

    assert result["exported"] == 1
    assert result["stopped_reason"] == "Kuaishou API error 2: None"
    assert output.read_text(encoding="utf-8").count("\n") == 1


@pytest.mark.asyncio
async def test_download_liked_file_uses_line_range(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    liked_file = tmp_path / "kuaishou_liked.jsonl"
    liked_file.write_text(
        "\n".join([
            json.dumps({"photo_id": "p1", "author_id": "a1", "timestamp": 111, "play_url": "https://example.test/1.mp4"}),
            json.dumps({"photo_id": "p2", "author_id": "a2", "timestamp": 222, "play_url": "https://example.test/2.mp4"}),
            json.dumps({"photo_id": "p3", "author_id": "a3", "timestamp": 333, "play_url": "https://example.test/3.mp4"}),
        ]),
        encoding="utf-8",
    )
    captured = {}

    async def fake_download_videos(videos, output_dir, delay, max_count, history):
        captured["videos"] = videos
        captured["output_dir"] = output_dir
        captured["delay"] = delay
        captured["max_count"] = max_count
        captured["history"] = history
        return {"success": 2, "failed": 0, "skipped": 0, "files": ["a.mp4", "b.mp4"], "items": []}

    monkeypatch.setattr(liked_batch.download, "download_videos", fake_download_videos)

    result = await liked_batch.download_liked_file(settings, liked_file, line_range="2-3", delay=0.5)

    assert [video["photo_id"] for video in captured["videos"]] == ["p2", "p3"]
    assert captured["output_dir"] == settings.kuaishou_likes_dir
    assert captured["delay"] == 0.5
    assert captured["max_count"] == 0
    assert result["requested"] == 2
    assert result["processed"] == 2
    assert result["success"] == 2


def test_cli_exposes_kuaishou_liked_commands():
    runner = CliRunner()

    assert runner.invoke(cli, ["export-kuaishou-liked", "--help"]).exit_code == 0
    assert runner.invoke(cli, ["download-kuaishou-liked", "--help"]).exit_code == 0
