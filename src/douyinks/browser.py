import asyncio
import uuid
from typing import Any

import httpx

from .config import (
    CUSTOM_HEADER,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
    DOUYIN_WORKSPACE,
)


class DaemonNotRunningError(Exception):
    """Raised when the browser daemon is not reachable."""


class BrowserCommandError(Exception):
    """Raised when the browser daemon reports command failure."""


def _urls(host: str = DEFAULT_DAEMON_HOST, port: int = DEFAULT_DAEMON_PORT) -> tuple[str, str]:
    base = f"http://{host}:{port}"
    return f"{base}/ping", f"{base}/command"


async def check_daemon(host: str = DEFAULT_DAEMON_HOST, port: int = DEFAULT_DAEMON_PORT) -> bool:
    ping_url, _ = _urls(host, port)
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(ping_url, timeout=2.0)
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False


async def send_command(
    action: str,
    workspace: str = DOUYIN_WORKSPACE,
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
    host: str = DEFAULT_DAEMON_HOST,
    port: int = DEFAULT_DAEMON_PORT,
    **kwargs: Any,
) -> Any:
    _, command_url = _urls(host, port)
    cmd_id = uuid.uuid4().hex[:12]
    payload = {
        "id": cmd_id,
        "action": action,
        "workspace": workspace,
        "timeout": timeout,
        **kwargs,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                command_url,
                json=payload,
                headers={CUSTOM_HEADER: "1", "Content-Type": "application/json"},
                timeout=timeout + 5,
            )
        except httpx.ConnectError as exc:
            raise DaemonNotRunningError("无法连接 Douyinks daemon，请先启动 douyinks daemon") from exc

    result = response.json()
    if not result.get("ok"):
        raise BrowserCommandError(result.get("error", "Unknown browser command error"))
    return result.get("data")


class BrowserPage:
    def __init__(
        self,
        workspace: str = DOUYIN_WORKSPACE,
        host: str = DEFAULT_DAEMON_HOST,
        port: int = DEFAULT_DAEMON_PORT,
    ):
        self.workspace = workspace
        self.host = host
        self.port = port
        self.tab_id: int | None = None

    async def goto(self, url: str) -> dict:
        data = await send_command(
            "navigate",
            workspace=self.workspace,
            host=self.host,
            port=self.port,
            url=url,
        )
        if isinstance(data, dict) and "tabId" in data:
            self.tab_id = data["tabId"]
        return data

    async def evaluate(self, js: str) -> Any:
        kwargs = {"tabId": self.tab_id} if self.tab_id is not None else {}
        return await send_command(
            "exec",
            workspace=self.workspace,
            host=self.host,
            port=self.port,
            code=js,
            **kwargs,
        )

    async def wait(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
