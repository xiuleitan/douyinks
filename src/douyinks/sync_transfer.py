import fcntl
import json
import mimetypes
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
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
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"无法读取同步记录，请保留文件并从备份恢复: {self.path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"同步记录格式不正确，请保留原文件: {self.path}")
        files = data.get("files")
        if not isinstance(files, dict):
            raise ValueError(f"同步记录缺少 files 字典，请保留原文件: {self.path}")
        data.setdefault("version", 1)
        data.setdefault("baseline_at", None)
        return data

    @property
    def synced_count(self) -> int:
        return sum(1 for record in self._data["files"].values()
                   if isinstance(record, dict) and record.get("sync_status") == "synced")

    def pending_from_history(self, history_path: str | Path) -> list[dict[str, Any]]:
        history = self._load_history(history_path)
        pending: list[dict[str, Any]] = []
        baseline_at = _parse_datetime(self._data.get("baseline_at"))
        files = (
            entry for post_id, post in sorted(history.get("downloads", {}).items())
            for entry in _history_files(post_id, post)
        )
        for file_id, item in files:
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
        with self._locked():
            # An existing ledger, including its original baseline and ACKs,
            # must remain byte-for-byte unchanged when the server restarts.
            if self.path.exists():
                self._data = self._load()
                return 0
            self._data["baseline_at"] = datetime.now(timezone.utc).isoformat()
            self.save()
        return 0

    def file_path_from_history(self, history_path: str | Path, file_id: str) -> Path | None:
        history = self._load_history(history_path)
        post_id = ":".join(file_id.split(":", 2)[:2])
        post = history.get("downloads", {}).get(post_id)
        for candidate_id, item in _history_files(post_id, post):
            if candidate_id == file_id:
                file_path = Path(str(item.get("file_path", "")))
                if file_path.is_file():
                    return file_path
        return None

    def mark_synced(self, file_ids: list[str], device_id: str) -> int:
        with self._locked():
            # ACK requests can run in parallel; merge against the latest ledger.
            self._data = self._load()
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

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as temporary:
                tmp_path = Path(temporary.name)
                json.dump(self._data, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            tmp_path.replace(self.path)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

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


def _history_files(post_id: str, post: Any):
    if not isinstance(post, dict):
        return
    if isinstance(post.get("files"), list):
        for file in post["files"]:
            if isinstance(file, dict) and file.get("status") == "success" and file.get("id"):
                yield file["id"], {**post, **file}
    elif post.get("status") == "success":
        yield post_id, post


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
