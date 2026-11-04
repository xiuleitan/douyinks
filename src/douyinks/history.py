import fcntl
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class DownloadHistory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()
        self._pending: dict[str, dict[str, Any]] = {}

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
        if isinstance(item.get("files"), list):
            return bool(item["files"]) and all(
                Path(file["file_path"]).is_file() for file in item["files"]
            )
        file_path = item.get("file_path")
        return bool(file_path and Path(file_path).exists())

    def record_success(self, platform: str, video_id: str, file_path: str | Path, filename: str) -> None:
        if not video_id:
            return
        path = Path(file_path)
        key = self.make_key(platform, video_id)
        item = {
            "platform": platform,
            "video_id": video_id,
            "status": "success",
            "filename": filename,
            "file_path": str(path),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._data["downloads"][key] = item
        self._pending[key] = item
        self.save()

    def record_media_files(
        self, platform: str, video_id: str, file_paths: list[Path], *, complete: bool = True,
    ) -> None:
        """Keep a post for deduplication and a separate sync identity for each file."""
        self._record_media_files(platform, video_id, file_paths, complete=complete)
        if self._pending:
            self.save()

    def _record_media_files(
        self, platform: str, video_id: str, file_paths: list[Path], *, complete: bool,
    ) -> int:
        if not video_id or not file_paths:
            return 0
        key = self.make_key(platform, video_id)
        previous = self.get(platform, video_id) or {}
        files = {file["filename"]: dict(file) for file in previous.get("files", [])}
        if not files and previous.get("file_path"):
            # The original ID must continue to refer to the original file, so
            # existing phone acknowledgments never suppress its siblings.
            name = previous.get("filename") or Path(previous["file_path"]).name
            files[name] = {
                "id": key, "filename": name, "file_path": previous["file_path"],
                "downloaded_at": previous.get("downloaded_at", ""), "status": "success",
            }
        added = 0
        for path in file_paths:
            old_file = files.get(path.name, {})
            if not old_file:
                added += 1
            files[path.name] = {
                "id": old_file.get("id") or (f"{key}:{path.name}" if files else key),
                "filename": path.name,
                "file_path": str(path),
                "downloaded_at": old_file.get("downloaded_at") or datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc,
                ).isoformat(),
                "status": "success",
            }
        primary = next(file for file in files.values() if file["id"] == key)
        item = {
            **previous, "platform": platform, "video_id": video_id,
            "status": "success" if complete else "partial",
            "filename": primary["filename"], "file_path": primary["file_path"],
            "downloaded_at": primary["downloaded_at"], "files": list(files.values()),
        }
        if item != previous:
            self._data["downloads"][key] = item
            self._pending[key] = item
        return added

    def recover_douyin_media(self, output_dir: str | Path) -> int:
        """Index old image downloads and indexed album files without downloading again."""
        directory = Path(output_dir)
        if not directory.is_dir():
            return 0
        if self.path.exists():
            # Automatic recovery must not replace an unreadable original history.
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("downloads"), dict):
                    raise ValueError("invalid download history")
            except (OSError, ValueError) as exc:
                raise ValueError(f"无法补录图片，请保留并检查下载历史: {self.path}") from exc
        posts: dict[str, list[Path]] = {}
        image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        video_suffixes = {".mp4", ".mov", ".m4v"}
        for path in sorted(directory.iterdir()):
            suffix = path.suffix.lower()
            if suffix not in image_suffixes | video_suffixes:
                continue
            match = re.fullmatch(r".+_\d+_(\d{11,})(_\d{3,})?", path.stem)
            if not match or (suffix in video_suffixes and not match[2]):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            posts.setdefault(match[1], []).append(path)
        added = 0
        for video_id, paths in posts.items():
            previous = self.get("douyin", video_id) or {}
            added += self._record_media_files(
                "douyin", video_id, paths, complete=previous.get("status") != "partial",
            )
        if self._pending:
            self.save()
        return added

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the lock on a separate file: replacing the JSON changes its inode.
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            latest = self._load()
            # Merge only this process's new records, preserving other writers' updates.
            latest["downloads"].update(self._pending)
            tmp_path = None
            try:
                with NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent,
                    prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
                ) as temporary:
                    tmp_path = Path(temporary.name)
                    json.dump(latest, temporary, ensure_ascii=False, indent=2, sort_keys=True)
                tmp_path.replace(self.path)
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
            self._data = latest
            self._pending.clear()
