import asyncio
import subprocess
import sys

import httpx

from .browser import BrowserPage, check_daemon
from .commands import DownloadCommand
from .config import DOUYIN_WORKSPACE, KUAISHOU_WORKSPACE, Settings
from .history import DownloadHistory


class DownloadService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def ensure_daemon(self) -> None:
        if await check_daemon(self.settings.daemon_host, self.settings.daemon_port):
            return

        subprocess.Popen(
            build_daemon_command(self.settings),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(20):
            await asyncio.sleep(0.5)
            if await check_daemon(self.settings.daemon_host, self.settings.daemon_port):
                return
        raise RuntimeError("Douyinks daemon 启动超时，请手动运行: douyinks daemon")

    async def run(self, command: DownloadCommand) -> dict:
        await self.ensure_daemon()
        if command.platform == "douyin":
            return await self._download_douyin_likes(command.count)
        if command.platform == "kuaishou":
            return await self._download_kuaishou_likes(command.count)
        raise ValueError(f"Unsupported platform: {command.platform}")

    async def _download_douyin_likes(self, count: int) -> dict:
        from .platforms.douyin import detail, download, scrape_ids

        page = BrowserPage(
            workspace=DOUYIN_WORKSPACE,
            host=self.settings.daemon_host,
            port=self.settings.daemon_port,
        )
        ids = await scrape_ids.run(page, limit=count)
        videos: list[dict] = []
        for index, aweme_id in enumerate(ids, 1):
            try:
                videos.extend(await detail.run(page, aweme_id=aweme_id))
            except Exception:
                continue
            if index < len(ids):
                await asyncio.sleep(1)

        results = await download.download_videos(
            videos,
            self.settings.douyin_likes_dir,
            delay=self.settings.download_delay_seconds,
            max_count=count,
            history=DownloadHistory(self.settings.download_history_path),
        )
        return {"platform": "douyin", "source": "like", "requested": count, "output_dir": self.settings.douyin_likes_dir, **results}

    async def _download_kuaishou_likes(self, count: int) -> dict:
        from .platforms.kuaishou import download, liked

        page = BrowserPage(
            workspace=KUAISHOU_WORKSPACE,
            host=self.settings.daemon_host,
            port=self.settings.daemon_port,
        )
        videos = await liked.run(page, limit=count)
        results = await download.download_videos(
            videos,
            self.settings.kuaishou_likes_dir,
            delay=self.settings.download_delay_seconds,
            max_count=count,
            history=DownloadHistory(self.settings.download_history_path),
        )
        return {"platform": "kuaishou", "source": "like", "requested": count, "output_dir": self.settings.kuaishou_likes_dir, **results}

    async def status(self) -> dict:
        url = self.settings.daemon_status_url
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"X-Douyinks": "1"}, timeout=5.0)
            response.raise_for_status()
            return response.json()


def build_daemon_command(settings: Settings) -> list[str]:
    return [
        sys.executable,
        "-m",
        "douyinks",
        "daemon",
        "--host",
        settings.daemon_host,
        "--port",
        str(settings.daemon_port),
    ]
