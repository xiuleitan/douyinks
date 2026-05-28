from pathlib import Path

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

    existing_ids = {file.stem.split("_")[-1] for file in out.iterdir() if file.suffix == ".mp4" and "_" in file.stem}
    results = {"success": 0, "failed": 0, "skipped": 0, "files": [], "items": []}
    for index, video in enumerate(videos, 1):
        photo_id = video.get("photo_id", "")
        play_url = video.get("play_url", "")
        author_id = sanitize_filename(video.get("author_id", ""), max_len=30)
        timestamp = str(video.get("timestamp", 0))
        filename = f"{author_id}_{timestamp}_{photo_id}.mp4" if photo_id else f"{author_id}_{timestamp}_{index}.mp4"
        if not play_url:
            results["skipped"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "skipped"})
            continue
        if history and photo_id and history.is_successfully_downloaded("kuaishou", photo_id):
            results["skipped"] += 1
            history_item = history.get("kuaishou", photo_id) or {}
            results["items"].append({
                "filename": history_item.get("filename", filename),
                "success": False,
                "status": "skipped",
            })
            continue
        if photo_id and photo_id in existing_ids:
            if history:
                matching_file = _find_existing_file(out, photo_id)
                if matching_file:
                    history.record_success("kuaishou", photo_id, matching_file, matching_file.name)
                    filename = matching_file.name
            results["skipped"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "skipped"})
            continue

        filepath = out / filename
        if filepath.exists():
            if history and photo_id:
                history.record_success("kuaishou", photo_id, filepath, filename)
            results["skipped"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "skipped"})
            continue

        ok = await download_single(play_url, filepath, referer="https://www.kuaishou.com/")
        if ok:
            results["success"] += 1
            results["files"].append(str(filepath))
            results["items"].append({"filename": filename, "success": True, "status": "success"})
            if photo_id:
                existing_ids.add(photo_id)
                if history:
                    history.record_success("kuaishou", photo_id, filepath, filename)
        else:
            results["failed"] += 1
            results["items"].append({"filename": filename, "success": False, "status": "failed"})
        await pause_between_items(index, len(videos), delay)

    return results


def _find_existing_file(output_dir: Path, video_id: str) -> Path | None:
    for file in output_dir.iterdir():
        if file.suffix == ".mp4" and file.stem.split("_")[-1] == video_id:
            return file
    return None
