import asyncio
import json
from pathlib import Path
from typing import Any

from ...browser import BrowserPage
from ...config import KUAISHOU_WORKSPACE, Settings
from ...downloader import DownloadService
from ...history import DownloadHistory
from ..douyin.link_batch import wait_for_extension_connection
from . import download
from .browser_fetch import KuaishouAPIError, browser_fetch
from .liked import _pick_best_url


async def export_liked_file(
    settings: Settings,
    output_path: str | Path,
    *,
    max_pages: int = 0,
    limit: int = 0,
    ensure_daemon: bool = True,
    page_delay: float = 4.0,
    resume: bool = True,
) -> dict[str, Any]:
    if ensure_daemon:
        service = DownloadService(settings)
        await service.ensure_daemon()
        await wait_for_extension_connection(service)

    page = BrowserPage(
        workspace=KUAISHOU_WORKSPACE,
        host=settings.daemon_host,
        port=settings.daemon_port,
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    state = _load_existing_export(out) if resume else _empty_export_state()
    exported = 0
    pages = 0
    pcursor = state["pcursor"]
    mode = "a" if resume and state["existing"] > 0 else "w"
    stopped_reason = ""
    with out.open(mode, encoding="utf-8") as file:
        while True:
            try:
                data = await _fetch_liked_page(page, pcursor)
            except KuaishouAPIError as exc:
                stopped_reason = str(exc)
                break
            feeds = data.get("feeds", [])
            if not feeds:
                break
            pages += 1
            for item in feeds:
                photo_id = item.get("photo_id", "")
                if photo_id and photo_id in state["seen_photo_ids"]:
                    continue
                exported += 1
                state["next_index"] += 1
                if photo_id:
                    state["seen_photo_ids"].add(photo_id)
                row = {"index": state["next_index"], **item, "pcursor": pcursor}
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                file.flush()
                if limit > 0 and exported >= limit:
                    return _export_result(out, exported, pages, state["existing"], stopped_reason)

            next_cursor = data.get("pcursor", "")
            if not next_cursor or next_cursor == "no_more" or next_cursor == pcursor:
                break
            if max_pages > 0 and pages >= max_pages:
                break
            if page_delay > 0:
                await asyncio.sleep(page_delay)
            pcursor = next_cursor

    return _export_result(out, exported, pages, state["existing"], stopped_reason)


async def download_liked_file(
    settings: Settings,
    liked_path: str | Path,
    *,
    line_range: str | None = None,
    delay: float = 1.0,
) -> dict[str, Any]:
    videos = _read_liked_file(liked_path, line_range=line_range)
    result = await download.download_videos(
        videos,
        settings.kuaishou_likes_dir,
        delay=delay,
        max_count=0,
        history=DownloadHistory(settings.download_history_path),
    )
    return {
        "platform": "kuaishou",
        "source": "liked-file",
        "requested": len(videos),
        "processed": len(videos),
        "output_dir": settings.kuaishou_likes_dir,
        **result,
    }


async def _fetch_liked_page(page: BrowserPage, pcursor: str) -> dict[str, Any]:
    if page.tab_id is None:
        await page.goto("https://www.kuaishou.com")
        await page.wait(3)
    res = await browser_fetch(
        page,
        "POST",
        "https://www.kuaishou.com/rest/v/feed/liked",
        body={"pcursor": pcursor, "page": "private"},
        headers={"referer": "https://www.kuaishou.com/"},
    )
    if not isinstance(res, dict):
        return {"pcursor": "", "feeds": []}
    return {
        "pcursor": res.get("pcursor", ""),
        "feeds": [_feed_to_video(item) for item in res.get("feeds", [])],
    }


def _feed_to_video(item: dict[str, Any]) -> dict[str, Any]:
    photo = item.get("photo", {})
    author = item.get("author", {})
    return {
        "photo_id": photo.get("id", ""),
        "caption": photo.get("caption", ""),
        "author_name": author.get("name", ""),
        "author_id": author.get("id", ""),
        "play_url": _pick_best_url(photo),
        "timestamp": photo.get("timestamp", 0),
    }


def _read_liked_file(path: str | Path, *, line_range: str | None = None) -> list[dict[str, Any]]:
    parsed_range = parse_line_range(line_range)
    videos: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            if parsed_range is not None:
                start, end = parsed_range
                if line_number < start or line_number > end:
                    continue
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            item = json.loads(text)
            if not isinstance(item, dict):
                raise ValueError(f"第 {line_number} 行不是 JSON object。")
            videos.append(item)
    return videos


def _empty_export_state() -> dict[str, Any]:
    return {"existing": 0, "next_index": 0, "pcursor": "", "seen_photo_ids": set()}


def _load_existing_export(path: Path) -> dict[str, Any]:
    state = _empty_export_state()
    if not path.exists():
        return state
    with path.open(encoding="utf-8") as file:
        for line in file:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            item = json.loads(text)
            if not isinstance(item, dict):
                continue
            state["existing"] += 1
            state["next_index"] = max(state["next_index"], int(item.get("index") or state["existing"]))
            photo_id = item.get("photo_id", "")
            if photo_id:
                state["seen_photo_ids"].add(photo_id)
            pcursor = item.get("pcursor", "")
            if isinstance(pcursor, str):
                state["pcursor"] = pcursor
    return state


def _export_result(
    output_path: Path,
    exported: int,
    pages: int,
    existing: int,
    stopped_reason: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "output_file": str(output_path),
        "exported": exported,
        "pages": pages,
        "existing": existing,
    }
    if stopped_reason:
        result["stopped_reason"] = stopped_reason
    return result


def parse_line_range(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    start_text, separator, end_text = value.partition("-")
    if not separator or not start_text or not end_text:
        raise ValueError("范围格式必须是 start-end，例如 1-100。")
    try:
        start = int(start_text)
        end = int(end_text)
    except ValueError as exc:
        raise ValueError("范围格式必须是 start-end，例如 1-100。") from exc
    if start < 1 or end < 1:
        raise ValueError("范围起止行号必须大于等于 1。")
    if start > end:
        raise ValueError("范围起始行号不能大于结束行号。")
    return start, end
