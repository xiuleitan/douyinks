import asyncio
import json
from pathlib import Path
from typing import Any

from ...browser import BrowserCommandError, BrowserPage
from ...config import DOUYIN_WORKSPACE, Settings
from ...downloader import DownloadService
from ...history import DownloadHistory
from . import detail, download


DONE_STATUSES = {"success", "skipped"}


def default_progress_path(settings: Settings) -> Path:
    return Path(settings.download_root) / "douyin_links_progress.json"


async def download_links_file(
    settings: Settings,
    links_path: str | Path,
    *,
    delay: float = 1.0,
    progress_path: str | Path | None = None,
    ensure_daemon: bool = True,
    detail_retries: int = 3,
    max_consecutive_detail_failures: int = 10,
    line_range: str | None = None,
) -> dict[str, Any]:
    links = _read_links(links_path, line_range=line_range)
    progress = LinkBatchProgress(progress_path or default_progress_path(settings))

    if ensure_daemon:
        service = DownloadService(settings)
        await service.ensure_daemon()
        await wait_for_extension_connection(service)

    page = BrowserPage(
        workspace=DOUYIN_WORKSPACE,
        host=settings.daemon_host,
        port=settings.daemon_port,
    )
    if ensure_daemon:
        await prepare_douyin_page(page)
    history = DownloadHistory(settings.download_history_path)
    output_dir = settings.douyin_likes_dir
    result: dict[str, Any] = {
        "platform": "douyin",
        "source": "links",
        "requested": len(links),
        "processed": 0,
        "already_done": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "items": [],
        "files": [],
        "output_dir": output_dir,
        "progress_file": str(progress.path),
    }

    pending = [link for link in links if not progress.is_done(link)]
    result["already_done"] = len(links) - len(pending)
    consecutive_detail_failures = 0
    for index, link in enumerate(pending, 1):
        try:
            aweme_id = detail.extract_aweme_id(link)
            videos = await fetch_detail_with_retries(page, aweme_id, attempts=detail_retries)
            item_result = await download.download_videos(
                videos,
                output_dir,
                delay=0,
                max_count=0,
                history=history,
            )
            status = _status_from_download_result(item_result)
            progress.record(link, status, aweme_id=aweme_id)
            _merge_download_result(result, item_result)
            consecutive_detail_failures = 0
        except BrowserCommandError as exc:
            if _is_bridge_unavailable(exc):
                raise RuntimeError(
                    "浏览器扩展未连接到 Douyinks daemon。请确认 Chrome 扩展已加载并保持开启，"
                    "然后重新运行同一个 download-links 命令。"
                ) from exc
            aweme_id = _extract_id_or_empty(link)
            progress.record(link, "failed", aweme_id=aweme_id, error=str(exc))
            result["failed"] += 1
            result["items"].append(
                {
                    "filename": link,
                    "success": False,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        except Exception as exc:
            aweme_id = _extract_id_or_empty(link)
            progress.record(link, "failed", aweme_id=aweme_id, error=str(exc))
            result["failed"] += 1
            result["items"].append(
                {
                    "filename": link,
                    "success": False,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            if _is_detail_fetch_failure(exc):
                consecutive_detail_failures += 1
                if consecutive_detail_failures >= max_consecutive_detail_failures:
                    raise RuntimeError(
                        f"连续 {consecutive_detail_failures} 条链接详情请求失败，已停止批量下载。"
                        "这通常是抖音页面登录态失效、请求被限流，或浏览器页面 fetch 被拦截。"
                        "请等待一段时间，确认浏览器中的 douyin.com 已登录后重新运行命令。"
                    ) from exc

        result["processed"] += 1
        if index < len(pending) and delay > 0:
            await asyncio.sleep(delay)

    return result


class LinkBatchProgress:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self._load()

    def is_done(self, link: str) -> bool:
        item = self.data["links"].get(link)
        return isinstance(item, dict) and item.get("status") in DONE_STATUSES

    def record(self, link: str, status: str, *, aweme_id: str = "", error: str = "") -> None:
        item: dict[str, Any] = {"status": status}
        if aweme_id:
            item["aweme_id"] = aweme_id
        if error:
            item["error"] = error
        self.data["links"][link] = item
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "links": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "links": {}}
        if not isinstance(data, dict):
            return {"version": 1, "links": {}}
        links = data.get("links")
        if not isinstance(links, dict):
            data["links"] = {}
        data.setdefault("version", 1)
        return data


def parse_line_range(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    start_text, separator, end_text = value.partition("-")
    if not separator or not start_text or not end_text:
        raise ValueError("范围格式必须是 start-end，例如 1-20。")
    try:
        start = int(start_text)
        end = int(end_text)
    except ValueError as exc:
        raise ValueError("范围格式必须是 start-end，例如 1-20。") from exc
    if start < 1 or end < 1:
        raise ValueError("范围起止行号必须大于等于 1。")
    if start > end:
        raise ValueError("范围起始行号不能大于结束行号。")
    return start, end


def _read_links(path: str | Path, *, line_range: str | None = None) -> list[str]:
    parsed_range = parse_line_range(line_range)
    seen: set[str] = set()
    links: list[str] = []
    with Path(path).open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            if parsed_range is not None:
                start, end = parsed_range
                if line_number < start or line_number > end:
                    continue
            link = line.strip()
            if not link or link.startswith("#") or link in seen:
                continue
            detail.extract_aweme_id(link)
            seen.add(link)
            links.append(link)
    return links


def _status_from_download_result(result: dict[str, Any]) -> str:
    if result.get("failed", 0) > 0:
        return "failed"
    if result.get("success", 0) > 0:
        return "success"
    return "skipped"


def _merge_download_result(total: dict[str, Any], item: dict[str, Any]) -> None:
    for key in ("success", "failed", "skipped"):
        total[key] += int(item.get(key, 0))
    total["files"].extend(item.get("files") or [])
    total["items"].extend(item.get("items") or [])


def _extract_id_or_empty(link: str) -> str:
    try:
        return detail.extract_aweme_id(link)
    except ValueError:
        return ""


def _is_bridge_unavailable(exc: BrowserCommandError) -> bool:
    message = str(exc)
    return "Extension not connected" in message or "Extension disconnected" in message


async def wait_for_extension_connection(service: DownloadService, *, timeout: float = 30.0) -> None:
    attempts = max(1, int(timeout))
    last_error = ""
    for attempt in range(attempts):
        try:
            status = await service.status()
        except Exception as exc:
            last_error = str(exc)
        else:
            if status.get("extensionConnected"):
                return
            last_error = "extensionConnected=false"
        if attempt < attempts - 1:
            await asyncio.sleep(1.0)
    raise RuntimeError(
        "浏览器扩展未连接到 Douyinks daemon。请确认 Chrome 扩展已加载并保持开启，"
        f"然后重新运行同一个 download-links 命令。最后状态: {last_error}"
    )


async def prepare_douyin_page(page: BrowserPage) -> None:
    await page.goto("https://www.douyin.com/")
    await page.wait(1.0)


async def fetch_detail_with_retries(page: BrowserPage, aweme_id: str, *, attempts: int) -> list[dict]:
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        try:
            return await detail.run(page, aweme_id=aweme_id)
        except Exception as exc:
            if not _is_detail_fetch_failure(exc) or attempt >= attempts:
                raise
            await prepare_douyin_page(page)
            await asyncio.sleep(float(attempt * 3))
    raise RuntimeError(f"无法获取视频详情: {aweme_id}")


def _is_detail_fetch_failure(exc: Exception) -> bool:
    return "Failed to fetch" in str(exc)
