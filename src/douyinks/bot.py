import asyncio
import logging
from html import escape
from typing import Any

from nio import AsyncClient, MatrixRoom, RoomMessageText, SyncResponse

from .commands import CommandParseError, DownloadCommand, parse_download_command
from .config import Settings
from .downloader import DownloadService
from .sync_state import MatrixSyncState

logger = logging.getLogger("douyinks.bot")


class MatrixDownloadBot:
    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        downloader: Any | None = None,
    ):
        self.settings = settings
        self.client = client or AsyncClient(settings.matrix_homeserver_url, settings.matrix_username)
        self.downloader = downloader or DownloadService(settings)
        self.sync_state = MatrixSyncState(settings.matrix_sync_state_path)
        self.queue: asyncio.Queue[tuple[str, DownloadCommand]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        logger.info("Bot starting for %s", self.settings.matrix_username)
        response = await self.client.login(self.settings.matrix_password)
        if getattr(response, "access_token", None) is None:
            logger.error("Matrix login failed for %s: %s", self.settings.matrix_username, response)
            raise RuntimeError(f"Matrix 登录失败: {response}")
        logger.info("Matrix login succeeded for %s", self.settings.matrix_username)

        since = self.sync_state.load_next_batch()
        if since is None:
            logger.info("No sync token found; performing initial sync without processing messages")
            initial_response = await self.client.sync(timeout=0, full_state=True)
            since = getattr(initial_response, "next_batch", None)
            self.sync_state.save_next_batch(since)
            logger.info("Initial sync completed; token saved=%s", bool(since))
        else:
            logger.info("Loaded existing Matrix sync token")

        self.client.add_event_callback(self._on_room_message, RoomMessageText)
        self.client.add_response_callback(self._on_sync_response, SyncResponse)
        self._ensure_worker()
        logger.info("Starting Matrix sync loop")
        await self.client.sync_forever(timeout=30000, since=since, full_state=True)

    async def _on_sync_response(self, response: SyncResponse) -> None:
        self.sync_state.save_next_batch(getattr(response, "next_batch", None))

    async def _on_room_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        await self.handle_text_message(room.room_id, event.sender, event.body)

    async def handle_text_message(self, room_id: str, sender: str, body: str) -> None:
        if room_id not in self.settings.matrix_allowed_room_ids:
            logger.debug("Ignoring message from non-allowed room room=%s sender=%s", room_id, sender)
            return
        if sender == self.settings.matrix_username:
            logger.debug("Ignoring message sent by bot user room=%s", room_id)
            return

        try:
            command = parse_download_command(body)
        except CommandParseError:
            logger.debug("Ignoring unsupported message room=%s sender=%s", room_id, sender)
            return

        self._ensure_worker()
        await self.queue.put((room_id, command))
        logger.info(
            "Queued download command platform=%s source=%s count=%s room=%s sender=%s",
            command.platform,
            command.source,
            command.count,
            room_id,
            sender,
        )

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            room_id, command = await self.queue.get()
            try:
                logger.info(
                    "Download task starting platform=%s source=%s count=%s room=%s",
                    command.platform,
                    command.source,
                    command.count,
                    room_id,
                )
                await self.send_text(room_id, f"正在下载: {command.platform} {command.source} {command.count}")
                result = await self.downloader.run(command)
                body, formatted_body = format_download_result_markdown(result)
                await self.send_markdown(room_id, body, formatted_body)
                logger.info(
                    "Download task completed platform=%s source=%s count=%s success=%s failed=%s skipped=%s",
                    command.platform,
                    command.source,
                    command.count,
                    result.get("success", 0),
                    result.get("failed", 0),
                    result.get("skipped", 0),
                )
            except Exception as exc:
                logger.exception(
                    "Download task failed platform=%s source=%s count=%s",
                    command.platform,
                    command.source,
                    command.count,
                )
                await self.send_text(room_id, f"下载失败: {exc}")
            finally:
                self.queue.task_done()

    async def stop_worker(self) -> None:
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass

    async def send_text(self, room_id: str, body: str) -> None:
        await self.client.room_send(
            room_id,
            "m.room.message",
            {"msgtype": "m.text", "body": body},
        )

    async def send_markdown(self, room_id: str, body: str, formatted_body: str) -> None:
        await self.client.room_send(
            room_id,
            "m.room.message",
            {
                "msgtype": "m.text",
                "body": body,
                "format": "org.matrix.custom.html",
                "formatted_body": formatted_body,
            },
        )


def format_download_result(result: dict) -> str:
    return (
        f"下载完成: {result.get('platform')} {result.get('source')}，"
        f"请求 {result.get('requested')}，"
        f"成功 {result.get('success', 0)}，"
        f"失败 {result.get('failed', 0)}，"
        f"跳过 {result.get('skipped', 0)}。\n"
        f"保存目录: {result.get('output_dir')}"
    )


def format_download_result_markdown(result: dict) -> tuple[str, str]:
    items = result.get("items") or []
    lines = ["| 文件名 | 是否成功 |", "| --- | --- |"]
    html_rows = ["<table>", "<thead><tr><th>文件名</th><th>是否成功</th></tr></thead>", "<tbody>"]

    if not items:
        items = [{"filename": "无文件", "success": False, "status": "skipped"}]

    for item in items:
        filename = str(item.get("filename") or "")
        status = _status_label(item)
        lines.append(f"| {filename} | {status} |")
        html_rows.append(f"<tr><td>{escape(filename)}</td><td>{escape(status)}</td></tr>")

    html_rows.extend(["</tbody>", "</table>"])
    return "\n".join(lines), "".join(html_rows)


def _status_label(item: dict) -> str:
    if item.get("success") is True:
        return "成功"
    status = item.get("status")
    if status == "skipped":
        return "跳过"
    if status == "failed":
        return "失败"
    return "失败"
