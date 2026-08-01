import asyncio
import logging
from html import escape
from typing import Any

from nio import AsyncClient, MatrixRoom, RoomMessageText, SyncResponse

from .commands import CaptureCommand, CommandParseError, DownloadCommand, parse_capture_command, parse_download_command
from .config import Settings
from .downloader import DownloadService
from .network import get_lan_ips
from .sync_state import MatrixSyncState
from .transient_services import TransientRuntimeServices

logger = logging.getLogger("douyinks.bot")


class MatrixDownloadBot:
    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        downloader: Any | None = None,
        runtime_services: Any | None = None,
        ip_provider: Any | None = None,
    ):
        self.settings = settings
        self.client = client or AsyncClient(settings.matrix_homeserver_url, settings.matrix_username)
        self.downloader = downloader or DownloadService(settings)
        self.runtime_services = runtime_services or TransientRuntimeServices(settings)
        self.ip_provider = ip_provider or get_lan_ips
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

        if is_ip_query(body):
            await self.send_text(room_id, format_ip_reply(self.ip_provider(), self.settings))
            return

        try:
            capture_command = parse_capture_command(body)
        except CommandParseError:
            capture_command = None
        if capture_command is not None:
            await self._handle_capture_command(room_id, capture_command)
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

    async def _handle_capture_command(self, room_id: str, command: CaptureCommand) -> None:
        try:
            await self.runtime_services.start_for_download()
            if command.platform == "kuaishou" and command.target == "liked" and command.action == "start":
                await self.downloader.start_kuaishou_liked_capture()
                await self.send_text(
                    room_id,
                    "快手点赞监听已启动，可以刷新网页、进入点赞页面并向下滚动鼠标了。加载完成后发送 download kuaishou captured <数量>。",
                )
                return
            if command.platform == "kuaishou" and command.target == "liked" and command.action == "num":
                summary = await self.downloader.count_kuaishou_liked_capture()
                await self.send_text(room_id, format_capture_count(summary))
                return
            await self.send_text(room_id, "不支持的捕获命令。")
        except Exception as exc:
            logger.exception("Capture command failed platform=%s target=%s action=%s", command.platform, command.target, command.action)
            prefix = "查询失败" if command.action == "num" else "监听失败"
            await self.send_text(room_id, f"{prefix}: {exc}")
        finally:
            self.runtime_services.schedule_idle_stop()

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
                await self.send_text(room_id, f"正在下载: {format_command_label(command)}")
                await self.runtime_services.start_for_download()
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
                self.runtime_services.schedule_idle_stop()
                self.queue.task_done()

    async def stop_worker(self) -> None:
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        await self.runtime_services.stop()

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


def format_command_label(command: DownloadCommand) -> str:
    count_text = str(command.count)
    if command.range_start is not None and command.range_end is not None:
        count_text = f"{command.range_start}-{command.range_end}"
    return f"{command.platform} {command.source} {count_text}"


def format_capture_count(summary: dict) -> str:
    parts = [f"当前已捕获 {summary.get('video_count', 0)} 个快手点赞视频"]
    pending = summary.get("pending_response_count", 0)
    failed = summary.get("error_count", 0)
    dropped = summary.get("dropped_response_count", 0)
    if isinstance(pending, int) and pending > 0:
        parts.append(f"{pending} 条响应仍在写入")
    if isinstance(failed, int) and failed > 0:
        parts.append(f"{failed} 条响应读取失败")
    if isinstance(dropped, int) and dropped > 0:
        parts.append(f"{dropped} 条响应超出缓存上限")
    return "，".join(parts) + "。"


def format_download_result_markdown(result: dict) -> tuple[str, str]:
    items = result.get("items") or []
    actual_items = items
    lines = ["| 序号 | 文件名 | 是否成功 |", "| --- | --- | --- |"]
    html_rows = [
        "<table>",
        "<thead><tr><th>序号</th><th>文件名</th><th>是否成功</th></tr></thead>",
        "<tbody>",
    ]

    if not items:
        items = [{"filename": "无文件", "success": False, "status": "skipped"}]

    for index, item in enumerate(items, start=1):
        filename = _display_filename(str(item.get("filename") or ""))
        status = _status_label(item)
        lines.append(f"| {index} | {filename} | {status} |")
        html_rows.append(f"<tr><td>{index}</td><td>{escape(filename)}</td><td>{escape(status)}</td></tr>")

    summary = format_download_summary(result, actual_items)
    lines.extend(["", summary])
    html_rows.extend(["</tbody>", "</table>"])
    html_rows.append(f"<p>{escape(summary)}</p>")
    return "\n".join(lines), "".join(html_rows)


def format_download_summary(result: dict, items: list[dict]) -> str:
    success = _result_count(result, "success", sum(item.get("success") is True for item in items))
    skipped = _result_count(result, "skipped", sum(item.get("status") == "skipped" for item in items))
    failed = _result_count(result, "failed", sum(_status_label(item) == "失败" for item in items))
    total = success + skipped + failed
    return f"总计：共 {total} 个，成功下载 {success} 个，跳过 {skipped} 个，失败 {failed} 个。"


def _result_count(result: dict, key: str, fallback: int) -> int:
    value = result.get(key)
    return value if isinstance(value, int) and value >= 0 else fallback


def _display_filename(filename: str) -> str:
    return filename.split("_", 1)[0] if "_" in filename else filename


def _status_label(item: dict) -> str:
    if item.get("success") is True:
        return "成功"
    status = item.get("status")
    if status == "skipped":
        return "跳过"
    if status == "failed":
        return "失败"
    return "失败"


def is_ip_query(message: str) -> bool:
    normalized = " ".join(message.strip().lower().split())
    return normalized in {"ip", "查询 ip", "查询ip", "局域网 ip", "局域网ip"}


def format_ip_reply(ips: list[str], settings: Settings) -> str:
    if not ips:
        return "未找到可用的局域网 IP。请确认笔记本已连接 Wi-Fi 或局域网。"
    lines = [f"当前局域网 IP: {', '.join(ips)}"]
    if settings.sync_server_enabled:
        lines.append(f"手机同步地址: http://{ips[0]}:{settings.sync_server_port}")
    return "\n".join(lines)
