import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from click.testing import CliRunner

from douyinks.browser import check_daemon, send_command
from douyinks.config import CUSTOM_HEADER, Settings
from douyinks.downloader import DownloadService
from douyinks.main import cli


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["ping", "command", "download_status", "cli_status"])
async def test_local_service_requests_bypass_configured_proxy(tmp_path, monkeypatch, operation):
    proxy_requests = []
    local_requests = []

    async def reject_proxy(request):
        proxy_requests.append(request.path)
        return web.Response(status=502)

    async def local_service(request):
        local_requests.append(request.path)
        if request.path in {"/command", "/status"}:
            assert request.headers[CUSTOM_HEADER] == "1"
        if request.path == "/command":
            payload = await request.json()
            return web.json_response({"ok": True, "data": {"action": payload["action"]}})
        return web.json_response({"ok": True, "extensionConnected": True, "extensionVersion": "test"})

    proxy_app = web.Application()
    proxy_app.router.add_route("*", "/{path:.*}", reject_proxy)
    local_app = web.Application()
    local_app.router.add_route("*", "/{path:.*}", local_service)

    async with TestServer(proxy_app) as proxy, TestServer(local_app) as server:
        for name in ("http_proxy", "https_proxy", "all_proxy"):
            monkeypatch.setenv(name, str(proxy.make_url("/")))
            monkeypatch.setenv(name.upper(), str(proxy.make_url("/")))
        for name in ("no_proxy", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)

        settings = Settings(
            download_root=str(tmp_path),
            daemon_host="127.0.0.1",
            daemon_port=server.port,
        )
        if operation == "ping":
            assert await check_daemon(settings.daemon_host, settings.daemon_port)
            assert local_requests == ["/ping"]
        elif operation == "command":
            result = await send_command("exec", host=settings.daemon_host, port=settings.daemon_port, code="1 + 1")
            assert result == {"action": "exec"}
            assert local_requests == ["/command"]
        elif operation == "download_status":
            assert (await DownloadService(settings).status())["extensionConnected"]
            assert local_requests == ["/status"]
        else:
            monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
            result = await asyncio.to_thread(CliRunner().invoke, cli, ["status"])
            assert result.exit_code == 0, result.output
            assert "扩展已连接" in result.output
            assert local_requests == ["/ping", "/status"]

        assert proxy_requests == []
