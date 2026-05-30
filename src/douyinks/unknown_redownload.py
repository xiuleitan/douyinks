import asyncio
import json
from pathlib import Path
from typing import Any

from .browser import BrowserPage
from .config import DOUYIN_WORKSPACE, KUAISHOU_WORKSPACE, Settings
from .downloader import DownloadService
from .platforms.douyin import detail as douyin_detail
from .platforms.douyin import download as douyin_download
from .platforms.douyin.link_batch import prepare_douyin_page
from .platforms.kuaishou import download as kuaishou_download
from .platforms.kuaishou.liked_batch import parse_line_range


def find_unknown_history_items(
    history_path: str | Path,
    *,
    platform: str,
    line_range: str | None = None,
) -> list[dict[str, Any]]:
    selected_platform = platform.lower()
    if selected_platform not in {"douyin", "kuaishou", "all"}:
        raise ValueError("platform 必须是 douyin、kuaishou 或 all")
    parsed_range = parse_line_range(line_range)
    data = json.loads(Path(history_path).read_text(encoding="utf-8"))
    downloads = data.get("downloads", {})
    if not isinstance(downloads, dict):
        return []
    items: list[dict[str, Any]] = []
    for key, item in downloads.items():
        if not isinstance(item, dict) or item.get("status") != "success":
            continue
        item_platform = str(item.get("platform", ""))
        if selected_platform != "all" and item_platform != selected_platform:
            continue
        filename = str(item.get("filename", ""))
        file_path = str(item.get("file_path", ""))
        if "unknown" not in filename.lower() and "unknown" not in file_path.lower():
            continue
        video_id = str(item.get("video_id") or key.partition(":")[2])
        if not video_id:
            continue
        items.append({**item, "history_key": key, "video_id": video_id, "platform": item_platform})

    if parsed_range is None:
        return items
    start, end = parsed_range
    return items[start - 1:end]


async def redownload_unknown_history(
    settings: Settings,
    history_path: str | Path,
    *,
    platform: str,
    line_range: str | None = None,
    output_dir: str | Path | None = None,
    delay: float = 1.0,
) -> dict[str, Any]:
    items = find_unknown_history_items(history_path, platform=platform, line_range=line_range)
    root = Path(output_dir) if output_dir else Path(settings.download_root) / "redownload_unknown"
    service = DownloadService(settings)
    await service.ensure_daemon()
    await service.wait_for_extension_connection()

    result: dict[str, Any] = {
        "platform": platform,
        "source": "unknown-history",
        "requested": len(items),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "files": [],
        "items": [],
        "output_dir": str(root),
    }

    pages: dict[str, BrowserPage] = {}
    for index, item in enumerate(items, 1):
        item_platform = item["platform"]
        item_output = root / item_platform
        item_output.mkdir(parents=True, exist_ok=True)
        result["output_dir"] = str(item_output) if platform != "all" else str(root)
        try:
            item_result = await _redownload_item(settings, pages, item, item_output)
            _merge_result(result, item_result)
        except Exception as exc:
            result["failed"] += 1
            result["items"].append(
                {
                    "filename": f"{item_platform}:{item.get('video_id', '')}",
                    "success": False,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        result["processed"] += 1
        if index < len(items) and delay > 0:
            await asyncio.sleep(delay)

    return result


async def _redownload_item(
    settings: Settings,
    pages: dict[str, BrowserPage],
    item: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    platform = item["platform"]
    if platform == "douyin":
        page = pages.get("douyin")
        if page is None:
            page = BrowserPage(DOUYIN_WORKSPACE, host=settings.daemon_host, port=settings.daemon_port)
            pages["douyin"] = page
            await prepare_douyin_page(page)
        videos = await douyin_detail.run(page, aweme_id=item["video_id"])
        return await douyin_download.download_videos(videos, str(output_dir), delay=0, max_count=0, history=None)

    if platform == "kuaishou":
        page = pages.get("kuaishou")
        if page is None:
            page = BrowserPage(KUAISHOU_WORKSPACE, host=settings.daemon_host, port=settings.daemon_port)
            pages["kuaishou"] = page
        play_url = item.get("play_url", "")
        if not play_url:
            raise RuntimeError("快手历史记录中没有 play_url，无法仅凭 download_history 重新下载。")
        video = {
            "photo_id": item["video_id"],
            "author_id": "",
            "timestamp": 0,
            "play_url": play_url,
        }
        return await kuaishou_download.download_videos([video], str(output_dir), delay=0, max_count=0, history=None)

    raise ValueError(f"不支持的平台: {platform}")


def _merge_result(total: dict[str, Any], item_result: dict[str, Any]) -> None:
    for key in ("success", "failed", "skipped"):
        total[key] += item_result.get(key, 0)
    total["files"].extend(item_result.get("files") or [])
    total["items"].extend(item_result.get("items") or [])
