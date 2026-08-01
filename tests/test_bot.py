import asyncio
import logging
from types import SimpleNamespace

import pytest

from douyinks.bot import MatrixDownloadBot
from douyinks.bot import format_download_result_markdown
from douyinks.commands import DownloadCommand
from douyinks.config import Settings


class FakeClient:
    def __init__(self):
        self.sent = []

    async def room_send(self, room_id, message_type, content):
        self.sent.append((room_id, message_type, content))


class FakeSyncClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.event_callbacks = []
        self.response_callbacks = []
        self.sync_calls = []
        self.sync_forever_calls = []

    async def login(self, _password):
        return SimpleNamespace(access_token="token")

    def add_event_callback(self, callback, event_type):
        self.event_callbacks.append((callback, event_type))

    def add_response_callback(self, callback, response_type):
        self.response_callbacks.append((callback, response_type))

    async def sync(self, **kwargs):
        self.sync_calls.append(kwargs)
        return SimpleNamespace(next_batch="initial-token")

    async def sync_forever(self, **kwargs):
        self.sync_forever_calls.append(kwargs)


class FakeDownloader:
    def __init__(self):
        self.commands = []
        self.capture_started = 0
        self.capture_count_requested = 0

    async def run(self, command):
        self.commands.append(command)
        return {
            "platform": command.platform,
            "source": command.source,
            "requested": command.count,
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "output_dir": "/tmp/downloads/douyin/likes",
            "files": ["/tmp/downloads/douyin/likes/a.mp4"],
            "items": [{"filename": "a.mp4", "success": True}],
        }

    async def start_kuaishou_liked_capture(self):
        self.capture_started += 1
        return {"tabId": 123, "url": "https://www.kuaishou.com/profile/abc", "captured": 0}

    async def count_kuaishou_liked_capture(self):
        self.capture_count_requested += 1
        return {"video_count": 123, "response_count": 7, "error_count": 0}


class FailingDownloader:
    async def run(self, _command):
        raise RuntimeError("extension disconnected")


class FakeRuntimeServices:
    def __init__(self):
        self.started = 0
        self.scheduled = 0
        self.stopped = 0

    async def start_for_download(self):
        self.started += 1

    def schedule_idle_stop(self):
        self.scheduled += 1

    async def stop(self):
        self.stopped += 1


class FakeIpProvider:
    def __init__(self, ips):
        self.ips = ips
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.ips


def make_settings():
    return Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": "/tmp/downloads",
        }
    )


def make_sync_settings():
    return Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": "/tmp/downloads",
            "SYNC_SERVER_ENABLED": "true",
            "SYNC_SERVER_HOST": "0.0.0.0",
            "SYNC_SERVER_PORT": "19827",
            "SYNC_TOKEN": "test-sync-token",
        }
    )


@pytest.mark.asyncio
async def test_bot_ignores_non_whitelisted_rooms():
    client = FakeClient()
    downloader = FakeDownloader()
    bot = MatrixDownloadBot(make_settings(), client=client, downloader=downloader)

    await bot.handle_text_message("!other:example", "@user:example", "download douyin like 20")

    assert downloader.commands == []
    assert client.sent == []


@pytest.mark.asyncio
async def test_bot_replies_with_lan_ip_without_starting_download_services():
    client = FakeClient()
    downloader = FakeDownloader()
    runtime_services = FakeRuntimeServices()
    ip_provider = FakeIpProvider(["192.168.1.23"])
    bot = MatrixDownloadBot(
        make_sync_settings(),
        client=client,
        downloader=downloader,
        runtime_services=runtime_services,
        ip_provider=ip_provider,
    )

    await bot.handle_text_message("!allowed:example", "@user:example", "查询 ip")

    assert ip_provider.calls == 1
    assert downloader.commands == []
    assert runtime_services.started == 0
    assert client.sent == [
        (
            "!allowed:example",
            "m.room.message",
            {
                "msgtype": "m.text",
                "body": "当前局域网 IP: 192.168.1.23\n手机同步地址: http://192.168.1.23:19827",
            },
        )
    ]
    assert "com.talk.kind" not in client.sent[0][2]


@pytest.mark.asyncio
async def test_bot_queues_download_and_replies_with_summary():
    client = FakeClient()
    downloader = FakeDownloader()
    runtime_services = FakeRuntimeServices()
    bot = MatrixDownloadBot(make_settings(), client=client, downloader=downloader, runtime_services=runtime_services)

    await bot.handle_text_message("!allowed:example", "@user:example", "download douyin like 20")
    await bot.queue.join()
    await asyncio.wait_for(bot.stop_worker(), timeout=1)

    assert downloader.commands == [DownloadCommand(platform="douyin", source="like", count=20)]
    assert runtime_services.started == 1
    assert runtime_services.scheduled == 1
    assert runtime_services.stopped == 1
    bodies = [content["body"] for _, _, content in client.sent]
    assert bodies == [
        "正在下载: douyin like 20",
        (
            "| 序号 | 文件名 | 是否成功 |\n"
            "| --- | --- | --- |\n"
            "| 1 | a.mp4 | 成功 |\n"
            "\n"
            "总计：共 1 个，成功下载 1 个，跳过 0 个，失败 0 个。"
        ),
    ]
    assert "com.talk.kind" not in client.sent[0][2]
    assert "com.talk.kind" not in client.sent[1][2]
    assert client.sent[1][2]["format"] == "org.matrix.custom.html"
    assert "<table>" in client.sent[1][2]["formatted_body"]


@pytest.mark.asyncio
async def test_bot_starts_kuaishou_capture_without_queueing_download():
    client = FakeClient()
    downloader = FakeDownloader()
    runtime_services = FakeRuntimeServices()
    bot = MatrixDownloadBot(make_settings(), client=client, downloader=downloader, runtime_services=runtime_services)

    await bot.handle_text_message("!allowed:example", "@user:example", "kuaishou capture start")

    assert downloader.capture_started == 1
    assert downloader.commands == []
    assert runtime_services.started == 1
    assert runtime_services.scheduled == 1
    assert client.sent == [
        (
            "!allowed:example",
            "m.room.message",
            {
                "msgtype": "m.text",
                "body": "快手点赞监听已启动，可以刷新网页、进入点赞页面并向下滚动鼠标了。加载完成后发送 download kuaishou captured <数量>。",
            },
        )
    ]
    assert "com.talk.kind" not in client.sent[0][2]


@pytest.mark.asyncio
async def test_bot_reports_kuaishou_captured_count_without_queueing_download():
    client = FakeClient()
    downloader = FakeDownloader()
    runtime_services = FakeRuntimeServices()
    bot = MatrixDownloadBot(make_settings(), client=client, downloader=downloader, runtime_services=runtime_services)

    await bot.handle_text_message("!allowed:example", "@user:example", "captured num")

    assert downloader.capture_count_requested == 1
    assert downloader.commands == []
    assert runtime_services.started == 1
    assert runtime_services.scheduled == 1
    assert client.sent == [
        (
            "!allowed:example",
            "m.room.message",
            {
                "msgtype": "m.text",
                "body": "当前已捕获 123 个快手点赞视频。",
            },
        )
    ]


@pytest.mark.asyncio
async def test_bot_queues_kuaishou_captured_download():
    client = FakeClient()
    downloader = FakeDownloader()
    runtime_services = FakeRuntimeServices()
    bot = MatrixDownloadBot(make_settings(), client=client, downloader=downloader, runtime_services=runtime_services)

    await bot.handle_text_message("!allowed:example", "@user:example", "download kuaishou captured 3")
    await bot.queue.join()
    await asyncio.wait_for(bot.stop_worker(), timeout=1)

    assert downloader.commands == [DownloadCommand(platform="kuaishou", source="captured", count=3)]
    assert client.sent[0][2]["body"] == "正在下载: kuaishou captured 3"


@pytest.mark.asyncio
async def test_bot_shows_range_in_download_start_message():
    client = FakeClient()
    downloader = FakeDownloader()
    runtime_services = FakeRuntimeServices()
    bot = MatrixDownloadBot(make_settings(), client=client, downloader=downloader, runtime_services=runtime_services)

    await bot.handle_text_message("!allowed:example", "@user:example", "download douyin like 60-100")
    await bot.queue.join()
    await asyncio.wait_for(bot.stop_worker(), timeout=1)

    assert client.sent[0][2]["body"] == "正在下载: douyin like 60-100"


@pytest.mark.asyncio
async def test_bot_sends_download_failure_as_plain_text():
    client = FakeClient()
    bot = MatrixDownloadBot(
        make_settings(),
        client=client,
        downloader=FailingDownloader(),
        runtime_services=FakeRuntimeServices(),
    )

    await bot.handle_text_message("!allowed:example", "@user:example", "download douyin like 20")
    await bot.queue.join()
    await asyncio.wait_for(bot.stop_worker(), timeout=1)

    assert client.sent[-1][2]["body"] == "下载失败: extension disconnected"
    assert "com.talk.kind" not in client.sent[-1][2]


def test_format_download_result_markdown_includes_failed_and_skipped_items():
    body, html = format_download_result_markdown(
        {
            "items": [
                {"filename": "3xxr5j529n5wbx2_1781254040084_3xghaii7rshtb8g.mp4", "success": True},
                {"filename": "skip_1781254040084_abc.mp4", "success": False, "status": "skipped"},
                {"filename": "bad_1781254040084_def.mp4", "success": False, "status": "failed"},
            ]
        }
    )

    assert body == (
        "| 序号 | 文件名 | 是否成功 |\n"
        "| --- | --- | --- |\n"
        "| 1 | 3xxr5j529n5wbx2 | 成功 |\n"
        "| 2 | skip | 跳过 |\n"
        "| 3 | bad | 失败 |\n"
        "\n"
        "总计：共 3 个，成功下载 1 个，跳过 1 个，失败 1 个。"
    )
    assert "<th>序号</th>" in html
    assert "<td>3</td><td>bad</td><td>失败</td>" in html
    assert "<td>3xxr5j529n5wbx2</td>" in html
    assert "<p>总计：共 3 个，成功下载 1 个，跳过 1 个，失败 1 个。</p>" in html
    assert "1781254040084" not in body
    assert "1781254040084" not in html


def test_format_download_result_markdown_uses_download_result_counts_for_summary():
    body, html = format_download_result_markdown(
        {
            "success": 2,
            "skipped": 1,
            "failed": 3,
            "items": [{"filename": "first.mp4", "success": True}],
        }
    )

    summary = "总计：共 6 个，成功下载 2 个，跳过 1 个，失败 3 个。"
    assert body.endswith(summary)
    assert f"<p>{summary}</p>" in html


@pytest.mark.asyncio
async def test_start_bootstraps_sync_token_before_registering_message_callback(tmp_path):
    settings = make_settings()
    object.__setattr__(settings, "download_root", str(tmp_path))
    client = FakeSyncClient()
    bot = MatrixDownloadBot(settings, client=client, downloader=FakeDownloader())

    await bot.start()
    await bot.stop_worker()

    assert client.sync_calls == [{"timeout": 0, "full_state": True}]
    assert len(client.event_callbacks) == 1
    assert client.sync_forever_calls == [{"timeout": 30000, "since": "initial-token", "full_state": True}]


@pytest.mark.asyncio
async def test_start_uses_persisted_sync_token_without_initial_history_sync(tmp_path):
    settings = make_settings()
    object.__setattr__(settings, "download_root", str(tmp_path))
    sync_state_path = tmp_path / "matrix_sync_state.json"
    sync_state_path.write_text('{"next_batch": "saved-token"}', encoding="utf-8")
    client = FakeSyncClient()
    bot = MatrixDownloadBot(settings, client=client, downloader=FakeDownloader())

    await bot.start()
    await bot.stop_worker()

    assert client.sync_calls == []
    assert len(client.event_callbacks) == 1
    assert client.sync_forever_calls == [{"timeout": 30000, "since": "saved-token", "full_state": True}]


@pytest.mark.asyncio
async def test_start_logs_key_lifecycle_events(tmp_path, caplog):
    settings = make_settings()
    object.__setattr__(settings, "download_root", str(tmp_path))
    client = FakeSyncClient()
    bot = MatrixDownloadBot(settings, client=client, downloader=FakeDownloader())

    with caplog.at_level(logging.INFO, logger="douyinks.bot"):
        await bot.start()
        await bot.stop_worker()

    messages = [record.getMessage() for record in caplog.records]
    assert "Bot starting for @bot:example" in messages
    assert "Matrix login succeeded for @bot:example" in messages
    assert "No sync token found; performing initial sync without processing messages" in messages
    assert "Starting Matrix sync loop" in messages


@pytest.mark.asyncio
async def test_handle_text_message_logs_accepted_command(tmp_path, caplog):
    settings = make_settings()
    object.__setattr__(settings, "download_root", str(tmp_path))
    bot = MatrixDownloadBot(settings, client=FakeClient(), downloader=FakeDownloader())

    with caplog.at_level(logging.INFO, logger="douyinks.bot"):
        await bot.handle_text_message("!allowed:example", "@user:example", "download douyin like 20")
        await bot.queue.join()
        await asyncio.wait_for(bot.stop_worker(), timeout=1)

    messages = [record.getMessage() for record in caplog.records]
    assert "Queued download command platform=douyin source=like count=20 room=!allowed:example sender=@user:example" in messages
    assert "Download task completed platform=douyin source=like count=20 success=1 failed=0 skipped=0" in messages
