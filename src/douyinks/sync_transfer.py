import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SyncTransferState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "baseline_at": None, "files": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "files": {}}
        if not isinstance(data, dict):
            return {"version": 1, "files": {}}
        files = data.get("files")
        if not isinstance(files, dict):
            data["files"] = {}
        data.setdefault("version", 1)
        data.setdefault("baseline_at", None)
        return data

    def pending_from_history(self, history_path: str | Path) -> list[dict[str, Any]]:
        history = self._load_history(history_path)
        pending: list[dict[str, Any]] = []
        baseline_at = _parse_datetime(self._data.get("baseline_at"))
        for file_id, item in sorted(history.get("downloads", {}).items()):
            if not isinstance(item, dict) or item.get("status") != "success":
                continue
            if self._data["files"].get(file_id, {}).get("sync_status") in {"synced", "baseline"}:
                continue
            downloaded_at = _parse_datetime(item.get("downloaded_at"))
            if baseline_at and downloaded_at and downloaded_at <= baseline_at:
                continue
            file_path = Path(str(item.get("file_path", "")))
            if not file_path.exists() or not file_path.is_file():
                continue
            platform = str(item.get("platform", ""))
            video_id = str(item.get("video_id", ""))
            filename = str(item.get("filename") or file_path.name)
            pending.append(
                {
                    "id": file_id,
                    "platform": platform,
                    "video_id": video_id,
                    "filename": filename,
                    "media_type": media_type_for_path(file_path),
                    "size": file_path.stat().st_size,
                    "downloaded_at": str(item.get("downloaded_at", "")),
                }
            )
        return pending

    def initialize_baseline(self, history_path: str | Path) -> int:
        if self.path.exists() or self._data.get("baseline_at"):
            return 0
        self._data["baseline_at"] = datetime.now(timezone.utc).isoformat()
        self.save()
        return 0

    def file_path_from_history(self, history_path: str | Path, file_id: str) -> Path | None:
        history = self._load_history(history_path)
        item = history.get("downloads", {}).get(file_id)
        if not isinstance(item, dict) or item.get("status") != "success":
            return None
        file_path = Path(str(item.get("file_path", "")))
        if not file_path.exists() or not file_path.is_file():
            return None
        return file_path

    def mark_synced(self, file_ids: list[str], device_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for file_id in file_ids:
            if not file_id:
                continue
            record = self._data["files"].setdefault(file_id, {})
            devices = record.setdefault("synced_devices", [])
            if device_id and device_id not in devices:
                devices.append(device_id)
            record["sync_status"] = "synced"
            record["synced_at"] = now
            count += 1
        self.save()
        return count

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    @staticmethod
    def _load_history(history_path: str | Path) -> dict[str, Any]:
        path = Path(history_path)
        if not path.exists():
            return {"version": 1, "downloads": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "downloads": {}}
        return data if isinstance(data, dict) else {"version": 1, "downloads": {}}


def media_type_for_path(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        return "file"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("image/"):
        return "image"
    return "file"


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
