from pathlib import Path
import re
from urllib.parse import urlparse

from pypinyin import lazy_pinyin

from ...history import DownloadHistory
from ..common import download_single, pause_between_items, sanitize_filename


async def download_videos(
    videos: list[dict],
    output_dir: str,
    delay: float = 2.0,
    max_count: int = 0,
    history: DownloadHistory | None = None,
) -> dict:
    if max_count > 0:
        videos = videos[:max_count]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    for file in out.iterdir():
        if file.suffix == ".mp4":
            for part in file.stem.split("_"):
                if part.isdigit() and len(part) > 10:
                    existing_ids.add(part)
                    break

    results = {"success": 0, "failed": 0, "skipped": 0, "files": [], "items": []}
    for index, video in enumerate(videos, 1):
        aweme_id = video.get("aweme_id", "")
        play_url = video.get("play_url", "")
        author_id = _author_prefix(video.get("author_douyin_id", ""), video.get("author", ""))
        create_time = str(video.get("create_time", 0))
        media_type = video.get("media_type") or "video"
        image_urls = [str(url) for url in video.get("image_urls", []) if url]
        child_video_urls = [str(url) for url in video.get("video_urls", []) if url]
        base_name = f"{author_id}_{create_time}_{aweme_id}" if aweme_id else f"{author_id}_{create_time}_{index}"
        filename = f"{base_name}.mp4"
        if media_type in {"image", "mixed"}:
            media_result = await _download_media_post(
                video_id=aweme_id,
                base_name=base_name,
                media_urls=[
                    *[{"url": url, "kind": "video"} for url in child_video_urls],
                    *[{"url": url, "kind": "image"} for url in image_urls],
                ],
                output_dir=out,
                history=history,
            )
            for key in ("success", "failed", "skipped"):
                results[key] += media_result[key]
            results["files"].extend(media_result["files"])
            results["items"].extend(media_result["items"])
            await pause_between_items(index, len(videos), delay)
            continue

        if not play_url:
            results["skipped"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "skipped"})
            continue
        if history and aweme_id and history.is_successfully_downloaded("douyin", aweme_id):
            results["skipped"] += 1
            history_item = history.get("douyin", aweme_id) or {}
            results["items"].append({
                "filename": history_item.get("filename", filename),
                "success": False,
                "status": "skipped",
            })
            continue
        if aweme_id and aweme_id in existing_ids:
            if history:
                matching_file = _find_existing_file(out, aweme_id)
                if matching_file:
                    history.record_success("douyin", aweme_id, matching_file, matching_file.name)
                    filename = matching_file.name
            results["skipped"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "skipped"})
            continue

        filepath = out / filename
        if filepath.exists():
            if history and aweme_id:
                history.record_success("douyin", aweme_id, filepath, filename)
            results["skipped"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "skipped"})
            continue

        ok = await download_single(play_url, filepath, referer="https://www.douyin.com/")
        if ok:
            results["success"] += 1
            results["files"].append(str(filepath))
            results["items"].append({"filename": filename, "success": True, "status": "success"})
            if aweme_id:
                existing_ids.add(aweme_id)
                if history:
                    history.record_success("douyin", aweme_id, filepath, filename)
        else:
            results["failed"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "failed"})
        await pause_between_items(index, len(videos), delay)

    return results


def _find_existing_file(output_dir: Path, video_id: str) -> Path | None:
    for file in output_dir.iterdir():
        if file.suffix == ".mp4" and video_id in file.stem.split("_"):
            return file
    return None


async def _download_media_post(
    *,
    video_id: str,
    base_name: str,
    media_urls: list[dict],
    output_dir: Path,
    history: DownloadHistory | None,
) -> dict:
    results = {"success": 0, "failed": 0, "skipped": 0, "files": [], "items": []}
    media_files = [
        _media_file(output_dir, base_name, idx, item["url"], item["kind"])
        for idx, item in enumerate(media_urls, 1)
    ]

    if not media_urls:
        results["skipped"] += 1
        results["items"].append({"filename": f"{base_name}_001.jpg", "success": False, "status": "skipped"})
        return results

    if history and video_id and history.is_successfully_downloaded("douyin", video_id):
        for file_path in media_files:
            results["skipped"] += 1
            results["items"].append({"filename": file_path.name, "success": False, "status": "skipped"})
        return results

    if all(file_path.exists() for file_path in media_files):
        if history and video_id:
            history.record_success("douyin", video_id, media_files[0], media_files[0].name)
        for file_path in media_files:
            results["skipped"] += 1
            results["items"].append({"filename": file_path.name, "success": False, "status": "skipped"})
        return results

    downloaded_files: list[Path] = []
    failed = False
    for item, file_path in zip(media_urls, media_files, strict=True):
        if file_path.exists():
            downloaded_files.append(file_path)
            results["items"].append({"filename": file_path.name, "success": False, "status": "skipped"})
            continue
        ok = await download_single(item["url"], file_path, referer="https://www.douyin.com/")
        if ok:
            downloaded_files.append(file_path)
            results["files"].append(str(file_path))
            results["items"].append({"filename": file_path.name, "success": True, "status": "success"})
        else:
            failed = True
            results["items"].append({"filename": file_path.name, "success": False, "status": "failed"})

    if failed:
        results["failed"] += 1
    else:
        results["success"] += 1
        if history and video_id:
            history.record_success("douyin", video_id, downloaded_files[0], downloaded_files[0].name)
    return results


def _media_file(output_dir: Path, base_name: str, index: int, url: str, kind: str) -> Path:
    suffix = Path(urlparse(url).path).suffix.lower()
    if kind == "video":
        if suffix not in {".mp4", ".mov", ".m4v"}:
            suffix = ".mp4"
    elif suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    return output_dir / f"{base_name}_{index:03d}{suffix}"


def _author_prefix(author_douyin_id: str, author_name: str) -> str:
    author_id = sanitize_filename(author_douyin_id, max_len=30)
    if author_id != "unknown":
        return author_id
    nickname = _nickname_pascal_slug(author_name)
    return nickname[:30] if nickname else "unknown"


def _nickname_pascal_slug(name: str) -> str:
    parts: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z]+|\d+", name):
        if token.isdigit():
            parts.append(token)
        elif re.fullmatch(r"[A-Za-z]+", token):
            parts.append(token[:1].upper() + token[1:])
        else:
            parts.extend(item.capitalize() for item in lazy_pinyin(token) if item)
    return "".join(parts)
