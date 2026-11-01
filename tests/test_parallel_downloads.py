import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from douyinks.config import Settings
from douyinks.daemon import create_app
from douyinks.history import DownloadHistory
from douyinks.platforms.douyin.scrape_ids import EXTRACT_IDS_JS


@pytest.mark.asyncio
async def test_platform_downloads_overlap_through_one_bridge_and_preserve_history(tmp_path):
    app = create_app()
    media_started = set()
    both_downloading = asyncio.Event()
    douyin_id = "1234567890123"

    async def media(request):
        platform = request.match_info["platform"]
        media_started.add(platform)
        if len(media_started) == 2:
            both_downloading.set()
        # Neither download can finish until the other process starts downloading.
        await asyncio.wait_for(both_downloading.wait(), timeout=10)
        return web.Response(body=platform.encode(), content_type="video/mp4")

    app.router.add_get("/{platform}.mp4", media)
    async with TestServer(app) as server, ClientSession() as browser:
        settings = Settings(str(tmp_path / "downloads"), daemon_port=server.port, download_delay_seconds=0)
        env_file = tmp_path / ".env"
        env_file.write_text("")
        env = os.environ.copy()
        for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            env.pop(key, None)
        env.update({
            "DOUYINKS_ENV_FILE": str(env_file),
            "DOWNLOAD_ROOT": settings.download_root,
            "DOUYINKS_DAEMON_HOST": settings.daemon_host,
            "DOUYINKS_DAEMON_PORT": str(server.port),
            "DOWNLOAD_DELAY_SECONDS": "0",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        })

        async with browser.ws_connect(server.make_url("/ext")) as extension:
            await extension.send_json({"type": "hello", "version": "test"})

            async def respond_to_commands():
                async for message in extension:
                    request = json.loads(message.data)
                    if request["workspace"] == "site:kuaishou":
                        assert (request["action"], request["op"]) == ("kuaishouLikedCapture", "read")
                        data = {"responses": [{"data": {"feeds": [{
                            "photo": {"id": "ks1", "timestamp": 1,
                                      "photoUrls": [{"url": str(server.make_url("/kuaishou.mp4"))}]},
                            "author": {"id": "ks"},
                        }]}}], "pending": 0, "failed": 0, "dropped": 0}
                    else:
                        assert request["workspace"] == "site:douyin"
                        if request["action"] == "navigate":
                            data = {"tabId": 101}
                        elif request["code"] == EXTRACT_IDS_JS:
                            assert request["tabId"] == 101
                            data = [douyin_id]
                        else:
                            assert "/aweme/detail/" in request["code"]
                            assert request["tabId"] == 101
                            data = {"aweme_detail": {
                                "aweme_id": douyin_id, "create_time": 1,
                                "author": {"unique_id": "dy"},
                                "video": {"play_addr": {"url_list": [str(server.make_url("/douyin.mp4"))]}},
                            }}
                    await extension.send_json({"id": request["id"], "ok": True, "data": data})

            responder = asyncio.create_task(respond_to_commands())
            processes = []
            readers = []
            try:
                for platform in ("douyin", "kuaishou"):
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "douyinks", platform, "download", "1",
                        cwd=tmp_path, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    )
                    processes.append(process)
                    readers.append(asyncio.create_task(process.communicate()))
                outputs = await asyncio.wait_for(asyncio.gather(*readers), timeout=15)
                if responder.done():
                    responder.result()

                for platform, process, (stdout, stderr) in zip(("douyin", "kuaishou"), processes, outputs, strict=True):
                    output = (stdout + stderr).decode()
                    assert process.returncode == 0, output
                    assert "下载进度 1/1" in output
                    assert "下载汇总" in output
                    summary = json.loads((Path(settings.download_root) / f"{platform}_last_download.json").read_text())
                    assert (summary["success"], summary["failed"], summary["skipped"]) == (1, 0, 0)

                assert media_started == {"douyin", "kuaishou"}
                assert (Path(settings.douyin_likes_dir) / f"dy_1_{douyin_id}.mp4").read_bytes() == b"douyin"
                assert (Path(settings.kuaishou_likes_dir) / "ks_1_ks1.mp4").read_bytes() == b"kuaishou"
                history = DownloadHistory(settings.download_history_path)
                assert history.is_successfully_downloaded("douyin", douyin_id)
                assert history.is_successfully_downloaded("kuaishou", "ks1")
            finally:
                for process in processes:
                    if process.returncode is None:
                        process.kill()
                await asyncio.gather(*(process.wait() for process in processes))
                await asyncio.gather(*readers, return_exceptions=True)
                responder.cancel()
                await asyncio.gather(responder, return_exceptions=True)
