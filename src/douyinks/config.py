import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    download_root: str
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 19826
    download_delay_seconds: float = 3.0

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Settings":
        # Editable installs always use the project's configuration, even when
        # the two terminals are opened in different working directories.
        if env_file is None:
            env_file = os.environ.get("DOUYINKS_ENV_FILE") or default_env_file()
        env_file = Path(env_file).expanduser()
        values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
        values.update(os.environ)
        return cls.from_mapping(values, base_dir=env_file.resolve().parent)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str], *, base_dir: Path | None = None) -> "Settings":
        root = Path(values.get("DOWNLOAD_ROOT", "").strip() or "~/Downloads/douyinks").expanduser()
        if not root.is_absolute():
            root = (base_dir or Path.cwd()) / root
        try:
            port = int(values.get("DOUYINKS_DAEMON_PORT", "19826"))
        except ValueError as exc:
            raise ValueError("DOUYINKS_DAEMON_PORT 必须是 1–65535 的整数") from exc
        if not 1 <= port <= 65535:
            raise ValueError("DOUYINKS_DAEMON_PORT 必须是 1–65535 的整数")
        try:
            delay = float(values.get("DOWNLOAD_DELAY_SECONDS", "3"))
        except ValueError as exc:
            raise ValueError("DOWNLOAD_DELAY_SECONDS 必须是非负数字") from exc
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("DOWNLOAD_DELAY_SECONDS 必须是非负数字")
        return cls(
            download_root=str(root.resolve()),
            daemon_host=values.get("DOUYINKS_DAEMON_HOST", "127.0.0.1").strip() or "127.0.0.1",
            daemon_port=port,
            download_delay_seconds=delay,
        )

    @property
    def daemon_url(self) -> str:
        return f"http://{self.daemon_host}:{self.daemon_port}"

    @property
    def daemon_command_url(self) -> str:
        return f"{self.daemon_url}/command"

    @property
    def daemon_ping_url(self) -> str:
        return f"{self.daemon_url}/ping"

    @property
    def daemon_status_url(self) -> str:
        return f"{self.daemon_url}/status"

    @property
    def douyin_likes_dir(self) -> str:
        return str(Path(self.download_root) / "douyin" / "likes")

    @property
    def kuaishou_likes_dir(self) -> str:
        return str(Path(self.download_root) / "kuaishou" / "likes")

    @property
    def download_history_path(self) -> str:
        return str(Path(self.download_root) / "download_history.json")


def default_env_file() -> Path:
    project_dir = Path(__file__).resolve().parents[2]
    if (project_dir / "pyproject.toml").is_file():
        return project_dir / ".env"
    return Path.home() / ".config" / "douyinks" / ".env"


DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 19826
CUSTOM_HEADER = "X-Douyinks"
DEFAULT_COMMAND_TIMEOUT = 120
DOUYIN_WORKSPACE = "site:douyin"
KUAISHOU_WORKSPACE = "site:kuaishou"
