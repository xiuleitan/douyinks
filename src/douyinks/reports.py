import json
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings


def summary_path(settings: Settings, platform: str) -> Path:
    return Path(settings.download_root) / f"{platform}_last_download.json"


def save_summary(settings: Settings, platform: str, result: dict, elapsed_seconds: float) -> dict:
    # Keep counters and metadata, without storing temporary media URLs.
    summary = {
        "platform": platform,
        "source": result.get("source", ""),
        "requested": result["requested"],
        "available": result.get("available", result["requested"]),
        "success": result["success"],
        "failed": result["failed"],
        "skipped": result["skipped"],
        "output_dir": result["output_dir"],
        "elapsed_seconds": round(elapsed_seconds, 1),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    path = summary_path(settings, platform)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return summary


def load_summary(settings: Settings, platform: str) -> dict:
    path = summary_path(settings, platform)
    if not path.exists():
        raise ValueError("尚无已保存的下载汇总，请查看执行下载命令的终端；新任务结束后会自动保存。")
    summary = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or summary.get("platform") != platform:
        raise ValueError("下载汇总文件格式不正确。")
    for key in ("requested", "available", "success", "failed", "skipped"):
        if not isinstance(summary.get(key), int) or summary[key] < 0:
            raise ValueError("下载汇总文件中的数量不正确。")
    if not isinstance(summary.get("output_dir"), str):
        raise ValueError("下载汇总文件中缺少保存目录。")
    return summary
