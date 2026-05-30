import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


REQUIRED_ENV = (
    "MATRIX_HOMESERVER_URL",
    "MATRIX_USERNAME",
    "MATRIX_PASSWORD",
    "MATRIX_ALLOWED_ROOM_IDS",
    "DOWNLOAD_ROOT",
)


@dataclass(frozen=True)
class Settings:
    matrix_homeserver_url: str
    matrix_username: str
    matrix_password: str
    matrix_allowed_room_ids: set[str]
    download_root: str
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 19826
    download_delay_seconds: float = 3.0
    sync_server_enabled: bool = False
    sync_server_host: str = "127.0.0.1"
    sync_server_port: int = 19827
    sync_token: str = ""
    transient_service_idle_seconds: float = 30 * 60

    @classmethod
    def load(cls, env_file: str | None = ".env") -> "Settings":
        if env_file:
            load_dotenv(env_file)
        return cls.from_mapping(os.environ)

    @staticmethod
    def validate_mapping(values: Mapping[str, str]) -> list[str]:
        return [key for key in REQUIRED_ENV if not values.get(key, "").strip()]

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "Settings":
        missing = cls.validate_mapping(values)
        if missing:
            raise ValueError("缺少必填配置: " + ", ".join(missing))

        rooms = {
            item.strip()
            for item in values["MATRIX_ALLOWED_ROOM_IDS"].split(",")
            if item.strip()
        }
        if not rooms:
            raise ValueError("MATRIX_ALLOWED_ROOM_IDS 至少需要一个房间 ID")

        return cls(
            matrix_homeserver_url=values["MATRIX_HOMESERVER_URL"].strip(),
            matrix_username=values["MATRIX_USERNAME"].strip(),
            matrix_password=values["MATRIX_PASSWORD"],
            matrix_allowed_room_ids=rooms,
            download_root=values["DOWNLOAD_ROOT"].strip(),
            daemon_host=values.get("DOUYINKS_DAEMON_HOST", "127.0.0.1").strip() or "127.0.0.1",
            daemon_port=int(values.get("DOUYINKS_DAEMON_PORT", "19826")),
            download_delay_seconds=float(values.get("DOWNLOAD_DELAY_SECONDS", "3")),
            sync_server_enabled=_env_bool(values.get("SYNC_SERVER_ENABLED", "false")),
            sync_server_host=values.get("SYNC_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1",
            sync_server_port=int(values.get("SYNC_SERVER_PORT", "19827")),
            sync_token=values.get("SYNC_TOKEN", "").strip(),
            transient_service_idle_seconds=float(values.get("TRANSIENT_SERVICE_IDLE_SECONDS", "1800")),
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

    @property
    def matrix_sync_state_path(self) -> str:
        return str(Path(self.download_root) / "matrix_sync_state.json")

    @property
    def sync_state_path(self) -> str:
        return str(Path(self.download_root) / "sync_state.json")


def _env_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 19826
CUSTOM_HEADER = "X-Douyinks"
DEFAULT_COMMAND_TIMEOUT = 120
DAEMON_IDLE_TIMEOUT = 5 * 60
DOUYIN_WORKSPACE = "site:douyin"
KUAISHOU_WORKSPACE = "site:kuaishou"
