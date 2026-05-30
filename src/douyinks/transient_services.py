import asyncio
import logging
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from .browser import check_daemon
from .config import Settings
from .downloader import build_daemon_command


logger = logging.getLogger("douyinks.transient_services")


CheckDaemon = Callable[[str, int], Awaitable[bool]]
CheckSyncServer = Callable[[Settings], Awaitable[bool]]
PopenFactory = Callable[..., subprocess.Popen]


@dataclass
class OwnedProcess:
    name: str
    process: subprocess.Popen


class TransientRuntimeServices:
    def __init__(
        self,
        settings: Settings,
        *,
        log_level: str = "INFO",
        idle_seconds: float | None = None,
        check_daemon_func: CheckDaemon = check_daemon,
        check_sync_server_func: CheckSyncServer | None = None,
        popen: PopenFactory = subprocess.Popen,
    ):
        self.settings = settings
        self.log_level = log_level
        self.idle_seconds = idle_seconds if idle_seconds is not None else settings.transient_service_idle_seconds
        self._check_daemon = check_daemon_func
        self._check_sync_server = check_sync_server_func or check_sync_server
        self._popen = popen
        self._owned: dict[str, OwnedProcess] = {}
        self._idle_task: asyncio.Task | None = None

    async def start_for_download(self) -> None:
        self._cancel_idle_stop()
        await self._ensure_daemon()
        if self.settings.sync_server_enabled:
            await self._ensure_sync_server()

    def schedule_idle_stop(self) -> None:
        self._cancel_idle_stop()
        self._idle_task = asyncio.create_task(self._stop_after_idle())

    async def stop(self) -> None:
        current = asyncio.current_task()
        if self._idle_task is not None and self._idle_task is not current:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
        self._idle_task = None
        owned = list(self._owned.values())
        self._owned.clear()
        for item in owned:
            _terminate_process(item)

    async def _ensure_daemon(self) -> None:
        if await self._check_daemon(self.settings.daemon_host, self.settings.daemon_port):
            return
        self._launch("daemon", build_daemon_command(self.settings))
        await self._wait_until(
            lambda: self._check_daemon(self.settings.daemon_host, self.settings.daemon_port),
            "Douyinks daemon 启动超时",
        )

    async def _ensure_sync_server(self) -> None:
        if await self._check_sync_server(self.settings):
            return
        self._launch("sync-server", build_sync_server_command(self.settings, self.log_level))
        await self._wait_until(
            lambda: self._check_sync_server(self.settings),
            "Douyinks sync-server 启动超时",
        )

    def _launch(self, name: str, command: list[str]) -> None:
        logger.info("Starting transient %s: %s", name, " ".join(command))
        self._owned[name] = OwnedProcess(
            name=name,
            process=self._popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            ),
        )

    async def _wait_until(self, check: Callable[[], Awaitable[bool]], timeout_message: str) -> None:
        for _ in range(20):
            if await check():
                return
            await asyncio.sleep(0.5)
        raise RuntimeError(timeout_message)

    def _cancel_idle_stop(self) -> None:
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    async def _stop_after_idle(self) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
            await self.stop()
        except asyncio.CancelledError:
            pass


async def check_sync_server(settings: Settings) -> bool:
    host = "127.0.0.1" if settings.sync_server_host == "0.0.0.0" else settings.sync_server_host
    url = f"http://{host}:{settings.sync_server_port}/sync/health"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=2.0)
            return response.status_code == 200
    except Exception:
        return False


def build_sync_server_command(settings: Settings, log_level: str = "INFO") -> list[str]:
    return [
        sys.executable,
        "-m",
        "douyinks",
        "sync-server",
        "--host",
        settings.sync_server_host,
        "--port",
        str(settings.sync_server_port),
        "--log-level",
        log_level,
    ]


def _terminate_process(item: OwnedProcess) -> None:
    process = item.process
    if process.poll() is not None:
        return
    logger.info("Stopping transient %s", item.name)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("Killing transient %s after graceful shutdown timeout", item.name)
        process.kill()
        process.wait()
