import asyncio
import json

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from click.testing import CliRunner

import douyinks.main as main
from douyinks.commands import DownloadCommand
from douyinks.config import Settings
from douyinks.daemon import create_app
from douyinks.downloader import DownloadService
from douyinks.platforms.kuaishou.browser_fetch import KuaishouAPIError


def test_bare_douyinks_starts_local_daemon_with_configured_address(monkeypatch, tmp_path):
    settings = Settings(str(tmp_path), daemon_host="127.0.0.2", daemon_port=19999)
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    started = []
    monkeypatch.setattr("douyinks.daemon.main", lambda **kwargs: started.append(kwargs))

    result = CliRunner().invoke(main.cli, [])

    assert result.exit_code == 0, result.output
    assert started == [{"host": "127.0.0.2", "port": 19999}]
    assert "另一个终端" in result.output


def test_daemon_subcommand_honors_address_override(monkeypatch):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: Settings.from_mapping({})))
    started = []
    monkeypatch.setattr("douyinks.daemon.main", lambda **kwargs: started.append(kwargs))

    result = CliRunner().invoke(main.cli, ["daemon", "--host", "127.0.0.2", "--port", "19998"])

    assert result.exit_code == 0, result.output
    assert started == [{"host": "127.0.0.2", "port": 19998}]


@pytest.mark.parametrize("command,args,expected", [
    (main.cli, ["douyin", "download", "300"], DownloadCommand("douyin", "like", 300)),
    (main.cli, ["douyin", "download", "41", "--start", "60"], DownloadCommand("douyin", "like", 41, 60, 100)),
    (main.cli, ["kuaishou", "download", "300"], DownloadCommand("kuaishou", "captured", 300)),
    (main.cli, ["kuaishou", "download", "300", "--source", "like"], DownloadCommand("kuaishou", "like", 300)),
    (main.cli, ["download-kuaishou-captured", "300"], DownloadCommand("kuaishou", "captured", 300)),
])
def test_download_cli_submits_quantity_and_source(monkeypatch, tmp_path, command, args, expected):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: Settings(str(tmp_path))))
    received = []

    async def download(self, request):
        received.append(request)
        return {"requested": request.count, "success": request.count, "failed": 0, "skipped": 0,
                "output_dir": str(tmp_path)}

    monkeypatch.setattr(DownloadService, "run", download)
    result = CliRunner().invoke(command, args)

    assert result.exit_code == 0, result.output
    assert received == [expected]
    assert f"请求 {expected.count}" in result.output
    assert "保存目录" in result.output


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
@pytest.mark.parametrize("count", ["0", "-1", "501", "abc", "1-20"])
def test_download_cli_rejects_invalid_quantity(platform, count):
    result = CliRunner().invoke(main.cli, [platform, "download", "--", count])
    assert result.exit_code == 2


def test_download_failure_is_reported_as_cli_error(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: Settings(str(tmp_path))))

    async def fail(self, command):
        raise KuaishouAPIError("请先运行 douyinks kuaishou capture start")

    monkeypatch.setattr(DownloadService, "run", fail)
    result = CliRunner().invoke(main.cli, ["kuaishou", "download", "300"])

    assert result.exit_code == 1
    assert "请先运行 douyinks kuaishou capture start" in result.output
    assert "Traceback" not in result.output


def test_partial_download_failure_returns_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: Settings(str(tmp_path))))

    async def download(self, request):
        return {"requested": 2, "success": 1, "failed": 1, "skipped": 0, "output_dir": str(tmp_path)}

    monkeypatch.setattr(DownloadService, "run", download)
    result = CliRunner().invoke(main.cli, ["douyin", "download", "2"])

    assert result.exit_code == 1
    assert "成功 1" in result.output
    assert "失败 1" in result.output
    report = json.loads((tmp_path / "douyin_last_download.json").read_text())
    assert report["requested"] == 2
    assert report["success"] == 1
    assert report["failed"] == 1
    assert report["skipped"] == 0

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Reading a summary must not start a download")

    monkeypatch.setattr(DownloadService, "run", unexpected_download)
    result = CliRunner().invoke(main.cli, ["douyin", "summary"])
    assert result.exit_code == 0, result.output
    assert "下载汇总" in result.output
    assert "成功 1" in result.output
    assert "失败 1" in result.output
    assert "完成时间" in result.output


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
def test_summary_reports_missing_result_without_inventing_counts(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: Settings(str(tmp_path))))

    result = CliRunner().invoke(main.cli, [platform, "summary"])

    assert result.exit_code == 1
    assert "尚无已保存的下载汇总" in result.output
    assert "成功 0" not in result.output


@pytest.mark.parametrize("command_path", [[], ["douyin"], ["kuaishou"], ["help"]])
def test_help_needs_no_configuration(monkeypatch, command_path):
    def unexpected_load(cls):
        raise AssertionError("Help must not load settings or start a service")

    monkeypatch.setattr(Settings, "load", classmethod(unexpected_load))
    assert CliRunner().invoke(main.cli, [*command_path, "--help"]).exit_code == 0


def test_help_command_lists_all_actions_and_examples_without_starting_daemon(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("Help must not start a service or load configuration")

    monkeypatch.setattr(Settings, "load", classmethod(unexpected_call))
    monkeypatch.setattr(main, "start_daemon", unexpected_call)

    result = CliRunner().invoke(main.cli, ["help"])

    assert result.exit_code == 0, result.output
    for command in (
        "douyinks daemon", "douyinks status", "douyinks help",
        "douyinks douyin download COUNT", "douyinks douyin download 300",
        "douyinks kuaishou capture start", "douyinks kuaishou count",
        "douyinks kuaishou download COUNT", "douyinks kuaishou download 300",
        "douyinks download-links LINKS_FILE [LINE_RANGE]",
        "douyinks export-kuaishou-liked OUTPUT_FILE",
        "douyinks download-kuaishou-liked LIKED_FILE [LINE_RANGE]",
        "douyinks redownload-unknown-history HISTORY_FILE",
        "douyinks start-kuaishou-liked-capture", "douyinks download-kuaishou-captured COUNT",
    ):
        assert command in result.output
    assert "网页刷新" in result.output
    assert result.output == CliRunner().invoke(main.cli, ["--help"]).output


@pytest.mark.parametrize("path,usage,option", [
    (["douyin", "download"], "douyinks douyin download [OPTIONS] COUNT", "--start"),
    (["kuaishou", "download"], "douyinks kuaishou download [OPTIONS] COUNT", "--source"),
    (["kuaishou", "capture", "start"], "douyinks kuaishou capture start [OPTIONS]", "--log-level"),
])
def test_help_command_describes_nested_command_parameters(path, usage, option):
    result = CliRunner().invoke(main.cli, ["help", *path])

    assert result.exit_code == 0, result.output
    assert usage in result.output
    assert option in result.output


@pytest.mark.parametrize("path", [["unknown"], ["kuaishou", "unknown"], ["douyin", "download", "unknown"]])
def test_help_command_reports_unknown_command_paths(path):
    result = CliRunner().invoke(main.cli, ["help", *path])

    assert result.exit_code == 2
    assert "未知命令路径" in result.output
    assert "douyinks help" in result.output


@pytest.mark.parametrize("command", ["bot", "sync-server", "serve"])
def test_removed_service_commands_are_unavailable(command):
    result = CliRunner().invoke(main.cli, [command])
    assert result.exit_code == 2
    assert "No such command" in result.output


@pytest.mark.asyncio
async def test_kuaishou_cli_capture_count_download_and_dedup_over_local_bridge(tmp_path, monkeypatch):
    """Exercise separate CLI loops through real HTTP/WebSocket and file downloads."""
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    app = create_app()
    media_requests = []

    async def media(request):
        media_requests.append(request.path)
        return web.Response(body=b"test-video-content", content_type="video/mp4")

    app.router.add_get("/test.mp4", media)
    async with TestServer(app) as server, ClientSession() as browser:
        settings = Settings(str(tmp_path), daemon_port=server.port, download_delay_seconds=0)
        monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
        async with browser.ws_connect(server.make_url("/ext")) as extension:
            await extension.send_json({"type": "hello", "version": "test"})
            commands = []

            async def respond_to_extension_commands():
                async for message in extension:
                    request = json.loads(message.data)
                    commands.append((request["action"], request.get("op")))
                    assert request["workspace"] == "site:kuaishou"
                    if request.get("op") == "start":
                        data = {"url": "https://www.kuaishou.com/profile/test"}
                    else:
                        data = {"responses": [{"data": {"feeds": [{
                            "photo": {"id": "p1", "timestamp": 1,
                                      "photoUrls": [{"url": str(server.make_url("/test.mp4"))}]},
                            "author": {"id": "a1"},
                        }]}}], "pending": 0, "failed": 0, "dropped": 0}
                    await extension.send_json({"id": request["id"], "ok": True, "data": data})

            responder = asyncio.create_task(respond_to_extension_commands())
            try:
                for args in (["capture", "start"], ["count"], ["download", "1"], ["download", "1"], ["summary"]):
                    result = await asyncio.wait_for(
                        asyncio.to_thread(CliRunner().invoke, main.cli, ["kuaishou", *args]), timeout=10,
                    )
                    assert result.exit_code == 0, result.output
                    if args == ["count"]:
                        assert "已捕获视频: 1" in result.output
                    if args[0] == "download":
                        assert "下载进度 1/1" in result.output
                        assert "下载汇总" in result.output
                        assert "再次查看: douyinks kuaishou summary" in result.output
                assert "跳过 1" in result.output
                report = json.loads((tmp_path / "kuaishou_last_download.json").read_text())
                assert (report["requested"], report["success"], report["failed"], report["skipped"]) == (1, 0, 0, 1)
                assert media_requests == ["/test.mp4"]
                assert (tmp_path / "kuaishou/likes/a1_1_p1.mp4").read_bytes() == b"test-video-content"
                history = json.loads((tmp_path / "download_history.json").read_text())
                assert history["downloads"]["kuaishou:p1"]["status"] == "success"
                assert commands == [("kuaishouLikedCapture", "start"), *[("kuaishouLikedCapture", "read")] * 3]
            finally:
                responder.cancel()
                await asyncio.gather(responder, return_exceptions=True)
