import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress

import httpx

from .browser import BrowserPage, DaemonNotRunningError, check_daemon
from .commands import DownloadCommand
from .config import DOUYIN_WORKSPACE, KUAISHOU_WORKSPACE, Settings
from .history import DownloadHistory
from .platforms.common import DownloadProgress

logger = logging.getLogger("douyinks.downloader")
WAIT_STATUS_INTERVAL_SECONDS = 10.0


class DownloadService:
    def __init__(
        self,
        settings: Settings,
        *,
        progress: DownloadProgress | None = None,
        status_callback: Callable[[str], None] | None = None,
    ):
        self.settings = settings
        self.progress = progress
        self.status_callback = status_callback
        self._activity = ""
        self._activity_started = 0.0

    def _set_activity(self, message: str, *, announce: bool = True) -> None:
        self._activity = message
        self._activity_started = time.monotonic()
        if announce and self.status_callback:
            self.status_callback(message)

    async def _report_waiting(self) -> None:
        while True:
            await asyncio.sleep(WAIT_STATUS_INTERVAL_SECONDS)
            elapsed = time.monotonic() - self._activity_started
            if self._activity and elapsed >= WAIT_STATUS_INTERVAL_SECONDS and self.status_callback:
                self.status_callback(f"{self._activity} | 已等待 {int(elapsed)} 秒，仍在处理中。")

    def _report_download_progress(self, completed: int, total: int, counters: dict) -> None:
        self._set_activity(f"正在下载文件 {min(completed + 1, total)}/{total}", announce=False)
        if self.progress:
            self.progress(completed, total, counters)

    def _report_list_progress(self, completed: int, total: int) -> None:
        self._set_activity(f"读取点赞列表 {completed}/{total}")

    async def ensure_daemon(self) -> None:
        if await check_daemon(self.settings.daemon_host, self.settings.daemon_port):
            return

        raise DaemonNotRunningError("本地后台未运行，请先在另一个终端执行 douyinks 并保持运行。")

    async def run(self, command: DownloadCommand) -> dict:
        waiting_reporter = asyncio.create_task(self._report_waiting()) if self.status_callback else None
        try:
            self._set_activity("正在检查本地后台连接。")
            await self.ensure_daemon()
            self._set_activity("正在等待浏览器扩展连接。")
            await self.wait_for_extension_connection()
            if command.platform == "douyin":
                return await self._download_douyin_likes(command)
            if command.platform == "kuaishou":
                if command.source == "captured":
                    return await self._download_kuaishou_captured_likes(command.count)
                return await self._download_kuaishou_likes(command.count)
            raise ValueError(f"Unsupported platform: {command.platform}")
        finally:
            if waiting_reporter:
                waiting_reporter.cancel()
                with suppress(asyncio.CancelledError):
                    await waiting_reporter

    async def wait_for_extension_connection(self, *, timeout: float = 30.0) -> None:
        attempts = max(1, int(timeout))
        last_error = ""
        for attempt in range(attempts):
            try:
                status = await self.status()
            except Exception as exc:
                last_error = str(exc)
            else:
                if status.get("extensionConnected"):
                    return
                last_error = "extensionConnected=false"
            if attempt < attempts - 1:
                await asyncio.sleep(1.0)
        raise RuntimeError(
            "浏览器扩展暂未连接到 Douyinks daemon。请打开 Chrome 或刷新 Douyinks Browser Bridge 扩展，"
            f"然后重试。最后状态: {last_error}"
        )

    async def _download_douyin_likes(self, command: DownloadCommand) -> dict:
        from .platforms.douyin import detail, download, scrape_ids

        count = command.count
        scrape_limit = command.range_end or count
        range_start = command.range_start or 1
        range_end = command.range_end or count
        page = BrowserPage(
            workspace=DOUYIN_WORKSPACE,
            host=self.settings.daemon_host,
            port=self.settings.daemon_port,
        )
        self._set_activity(f"正在读取并滚动抖音点赞列表，目标 {scrape_limit} 条。")
        ids = await scrape_ids.run(page, limit=scrape_limit, progress=self._report_list_progress)
        selected_ids = ids[range_start - 1:range_end]
        if not selected_ids:
            raise RuntimeError("未读取到指定范围内的抖音点赞内容，请确认浏览器已登录、点赞列表可见且范围内有内容。")
        self._set_activity(f"已获取 {len(selected_ids)} 条内容，开始读取详情；详情读取完成后下载文件。")
        videos: list[dict] = []
        detail_failures = 0
        for index, aweme_id in enumerate(selected_ids, 1):
            self._set_activity(f"读取详情 {index}/{len(selected_ids)} | 失败 {detail_failures} | 当前 {aweme_id}")
            try:
                videos.extend(await detail.run(page, aweme_id=aweme_id))
            except Exception as exc:
                detail_failures += 1
                logger.warning("读取抖音内容 %s 失败: %s", aweme_id, exc)
                continue
            if index < len(selected_ids):
                await asyncio.sleep(1)

        self._set_activity(
            f"详情读取完成 {len(selected_ids)}/{len(selected_ids)} | 失败 {detail_failures} | "
            f"开始下载 {len(videos)} 条内容的文件。"
        )
        results = await download.download_videos(
            videos,
            self.settings.douyin_likes_dir,
            delay=self.settings.download_delay_seconds,
            max_count=len(selected_ids),
            history=DownloadHistory(self.settings.download_history_path),
            progress=self._report_download_progress,
        )
        results["failed"] += detail_failures
        result = {"platform": "douyin", "source": "like", "requested": count, "available": len(selected_ids),
                  "output_dir": self.settings.douyin_likes_dir, **results}
        if command.range_start is not None and command.range_end is not None:
            result["range"] = f"{command.range_start}-{command.range_end}"
            result["scraped"] = len(ids)
        return result

    async def _download_kuaishou_likes(self, count: int) -> dict:
        from .platforms.kuaishou import download, liked

        page = BrowserPage(
            workspace=KUAISHOU_WORKSPACE,
            host=self.settings.daemon_host,
            port=self.settings.daemon_port,
        )
        self._set_activity(f"正在读取快手点赞列表，目标 {count} 条。")
        videos = await liked.run(page, limit=count)
        if not videos:
            raise RuntimeError("未读取到快手点赞内容，请确认浏览器已登录且点赞列表可见。")
        self._set_activity(f"已获取 {len(videos)} 条内容，开始下载文件。")
        results = await download.download_videos(
            videos,
            self.settings.kuaishou_likes_dir,
            delay=self.settings.download_delay_seconds,
            max_count=count,
            history=DownloadHistory(self.settings.download_history_path),
            progress=self._report_download_progress,
        )
        return {"platform": "kuaishou", "source": "like", "requested": count, "available": len(videos),
                "output_dir": self.settings.kuaishou_likes_dir, **results}

    async def start_kuaishou_liked_capture(self) -> dict:
        await self.ensure_daemon()
        await self.wait_for_extension_connection()

        from .platforms.kuaishou import liked

        page = BrowserPage(
            workspace=KUAISHOU_WORKSPACE,
            host=self.settings.daemon_host,
            port=self.settings.daemon_port,
        )
        return await liked.start_capture(page)

    async def _download_kuaishou_captured_likes(self, count: int) -> dict:
        from .platforms.kuaishou import download, liked

        page = BrowserPage(
            workspace=KUAISHOU_WORKSPACE,
            host=self.settings.daemon_host,
            port=self.settings.daemon_port,
        )
        self._set_activity(f"正在读取快手点赞监听结果，目标 {count} 条。")
        videos = await liked.read_captured(page, limit=count)
        self._set_activity(f"已获取 {len(videos)} 条内容，开始下载文件。")
        results = await download.download_videos(
            videos,
            self.settings.kuaishou_likes_dir,
            delay=self.settings.download_delay_seconds,
            max_count=count,
            history=DownloadHistory(self.settings.download_history_path),
            progress=self._report_download_progress,
        )
        return {"platform": "kuaishou", "source": "captured", "requested": count, "available": len(videos),
                "output_dir": self.settings.kuaishou_likes_dir, **results}

    async def count_kuaishou_liked_capture(self) -> dict:
        await self.ensure_daemon()
        await self.wait_for_extension_connection()

        from .platforms.kuaishou import liked

        page = BrowserPage(
            workspace=KUAISHOU_WORKSPACE,
            host=self.settings.daemon_host,
            port=self.settings.daemon_port,
        )
        return await liked.captured_summary(page)

    async def status(self) -> dict:
        url = self.settings.daemon_status_url
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(url, headers={"X-Douyinks": "1"}, timeout=5.0)
            response.raise_for_status()
            return response.json()
