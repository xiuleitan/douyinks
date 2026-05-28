import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DownloadHistory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "downloads": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "downloads": {}}
        if not isinstance(data, dict):
            return {"version": 1, "downloads": {}}
        downloads = data.get("downloads")
        if not isinstance(downloads, dict):
            data["downloads"] = {}
        data.setdefault("version", 1)
        return data

    @staticmethod
    def make_key(platform: str, video_id: str) -> str:
        return f"{platform}:{video_id}"

    def get(self, platform: str, video_id: str) -> dict[str, Any] | None:
        item = self._data["downloads"].get(self.make_key(platform, video_id))
        return item if isinstance(item, dict) else None

    def is_successfully_downloaded(self, platform: str, video_id: str) -> bool:
        item = self.get(platform, video_id)
        if not item or item.get("status") != "success":
            return False
        file_path = item.get("file_path")
        return bool(file_path and Path(file_path).exists())

    def record_success(self, platform: str, video_id: str, file_path: str | Path, filename: str) -> None:
        if not video_id:
            return
        path = Path(file_path)
        self._data["downloads"][self.make_key(platform, video_id)] = {
            "platform": platform,
            "video_id": video_id,
            "status": "success",
            "filename": filename,
            "file_path": str(path),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)
