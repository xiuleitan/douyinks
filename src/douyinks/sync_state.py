import json
from pathlib import Path


class MatrixSyncState:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load_next_batch(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        token = data.get("next_batch") if isinstance(data, dict) else None
        return token if isinstance(token, str) and token else None

    def save_next_batch(self, token: str | None) -> None:
        if not token:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"next_batch": token}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)
